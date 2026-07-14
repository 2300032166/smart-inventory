from fastapi import APIRouter, Depends
import pandas as pd
import numpy as np
import os
from datetime import datetime
from typing import List

from middleware.auth_middleware import verify_token
from logic.pattern_detector import load_sales, get_effective_today, get_avg_sales_map

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PRODUCTS_CSV = os.path.join(DATA_DIR, "products.csv")

def load_products():
    from routes.inventory import load_products as get_inv_prods
    return pd.DataFrame(get_inv_prods()).fillna("")

@router.get("/analysis")
def get_dead_stock_analysis(payload: dict = Depends(verify_token)):
    return get_analysis_data()

def get_analysis_data():
    sales_df = load_sales()
    products_df = load_products()
    today = get_effective_today(sales_df)
    # Use date-only (no time) so June 28 expiry on June 27 gives 1 day, not 0
    today_dt = pd.to_datetime(datetime.now().date())
    avg_sales_map = get_avg_sales_map()
    
    # 1. Aggregate SKU-level info
    sku_groups = products_df.groupby("sku").agg({
        "name": "first", "category": "first", "current_stock": "sum",
        "unit_price": "first", "supplier_name": "first"
    }).reset_index()
    
    last_sales = sales_df.groupby("StockCode")["InvoiceDate"].max()
    
    sku_stats = []
    summary = {
        "dead_items": 0, "slow_items": 0, "healthy_items": 0,
        "expired_items": 0, "critical_items": 0, "high_risk_items": 0, "medium_risk_items": 0,
        "potential_loss": 0, "value_locked": 0, "oldest_days": 0
    }
    
    category_temp = {}
    supplier_temp = {} # supplier -> loss

    for _, p in sku_groups.iterrows():
        sku = str(p["sku"]).strip().upper()
        stock = float(p["current_stock"])
        cat = str(p["category"]) or "Other"
        sup = str(p["supplier_name"]) or "Unknown"
        
        if cat not in category_temp: category_temp[cat] = {"dead_items": 0, "slow_items": 0, "healthy_items": 0, "value": 0, "dead_value": 0}
        if sup not in supplier_temp: supplier_temp[sup] = 0
        
        if stock <= 0: continue
        category_temp[cat]["value"] += (stock * float(p["unit_price"]))
            
        last_sale_date = last_sales.get(sku)
        days_since = (today_dt - pd.to_datetime(last_sale_date)).days if last_sale_date is not None else 999
        
        status = "Healthy"
        status_code = "healthy"
        if days_since > 30:
            status = "Dead Stock"
            status_code = "dead"
            summary["dead_items"] += 1
            summary["value_locked"] += (stock * float(p["unit_price"]))
            summary["oldest_days"] = max(summary["oldest_days"], days_since)
            category_temp[cat]["dead_items"] += 1
            category_temp[cat]["dead_value"] += (stock * float(p["unit_price"]))
        elif days_since > 15:
            status = "Slow Moving"
            status_code = "slow"
            summary["slow_items"] += 1
            category_temp[cat]["slow_items"] += 1
        else:
            summary["healthy_items"] += 1
            category_temp[cat]["healthy_items"] += 1
            
        if len(sku_stats) < 10000: # Effective limit for 3000 items
            sku_stats.append({
                "sku": sku, "name": p["name"], "category": cat,
                "current_stock": stock, "days_since_sale": int(days_since),
                "status": status, "status_code": status_code
            })

    # 2. Expiry Analysis — now from inventory_batches.csv
    BATCHES_CSV = os.path.join(DATA_DIR, "inventory_batches.csv")
    items = []             # product-level rows for the table
    product_batches = {}   # sku -> list of batch detail dicts

    if os.path.exists(BATCHES_CSV):
        batches_df = pd.read_csv(BATCHES_CSV).fillna("")
        # Only active or expired batches with stock
        batches_df = batches_df[batches_df["status"].isin(["active", "expired"])]
        batches_df["quantity"] = pd.to_numeric(batches_df["quantity"], errors="coerce").fillna(0)
        batches_df = batches_df[batches_df["quantity"] > 0]

        # Build unit price map from products
        price_map = dict(zip(
            sku_groups["sku"].str.upper(),
            pd.to_numeric(sku_groups["unit_price"], errors="coerce").fillna(0)
        ))

        # Build name map: products.csv is authoritative; fall back to
        # inventory_batches.csv "product_name" column for SKUs not in products.csv
        name_map = dict(zip(sku_groups["sku"].str.upper(), sku_groups["name"]))
        cat_map  = dict(zip(sku_groups["sku"].str.upper(), sku_groups["category"]))

        if "product_name" in batches_df.columns:
            for _, row in batches_df.iterrows():
                sku_key = str(row["sku"]).strip().upper()
                if sku_key not in name_map:
                    pname = str(row.get("product_name", "")).strip()
                    if pname and pname.lower() not in ("", "unknown"):
                        name_map[sku_key] = pname

        # Group by SKU — calculate worst risk per product
        for sku, grp in batches_df.groupby("sku"):
            sku_upper = str(sku).strip().upper()
            # Use pre-built maps: products.csv first, then batch file's product_name
            prod_name = name_map.get(sku_upper) or f"Product {sku_upper}"
            prod_cat  = cat_map.get(sku_upper, "Other")
            unit_price = price_map.get(sku_upper, 0)
            avg_v = avg_sales_map.get(sku_upper, 0)

            batch_details = []
            worst_days = None   # track worst (smallest) days_to_expiry
            worst_risk = "Low Risk"
            total_loss = 0.0

            risk_rank = {"Expired": 0, "Critical (< 7d)": 1, "High (8-21d)": 2, "Medium (22-90d)": 3, "Low Risk": 4}

            for _, b in grp.iterrows():
                expiry_dt = pd.to_datetime(b["expiry_date"], errors="coerce")
                if pd.isna(expiry_dt):
                    continue

                qty = float(b["quantity"])
                days_to_expiry = (expiry_dt - today_dt).days
                exp_sales = avg_v * max(0, days_to_expiry)
                exp_unsold = max(0, qty - exp_sales)

                if days_to_expiry < 0:
                    risk = "Expired"
                    loss = qty * unit_price
                elif days_to_expiry <= 7:
                    risk = "Critical (< 7d)"
                    loss = exp_unsold * unit_price
                elif days_to_expiry <= 21:
                    risk = "High (8-21d)"
                    loss = exp_unsold * unit_price
                elif days_to_expiry <= 90:
                    risk = "Medium (22-90d)"
                    loss = exp_unsold * unit_price
                else:
                    risk = "Low Risk"
                    loss = 0

                total_loss += loss
                sup_key = str(b.get("supplier", "Unknown"))
                if sup_key not in supplier_temp:
                    supplier_temp[sup_key] = 0
                supplier_temp[sup_key] += loss

                batch_details.append({
                    "batch_no": str(b.get("batch_no", "N/A")),
                    "quantity": qty,
                    "mfg_date": str(b.get("mfg_date", "N/A")),
                    "expiry_date": str(expiry_dt.date()),
                    "days_to_expiry": days_to_expiry,
                    "expiry_risk": risk,
                    "potential_loss": round(loss, 2),
                    "supplier": sup_key
                })

                if worst_days is None or days_to_expiry < worst_days:
                    worst_days = days_to_expiry

                if risk_rank.get(risk, 4) < risk_rank.get(worst_risk, 4):
                    worst_risk = risk

            if not batch_details:
                continue

            # Count each product ONCE in KPI counters  
            summary["potential_loss"] += total_loss
            if worst_risk == "Expired":
                summary["expired_items"] += 1
            elif worst_risk == "Critical (< 7d)":
                summary["critical_items"] += 1
            elif worst_risk == "High (8-21d)":
                summary["high_risk_items"] += 1
            elif worst_risk == "Medium (22-90d)":
                summary["medium_risk_items"] += 1

            total_stock = grp["quantity"].sum()
            product_batches[sku_upper] = batch_details

            # Always include in items list — user can expand to see all batches
            items.append({
                "sku": sku_upper,
                "product_name": prod_name,
                "name": prod_name,
                "category": prod_cat,
                "current_stock": round(float(total_stock), 2),
                "expiry_risk": worst_risk,         # worst batch risk drives the row badge
                "days_to_expiry": worst_days if worst_days is not None else 9999,
                "potential_loss": round(total_loss, 2),
                "batch_count": len(batch_details),
                "batches": batch_details           # ALL batches including healthy ones
            })

    total = len(sku_groups)
    summary["health_score"] = round((summary["healthy_items"] / total * 100)) if total > 0 else 0
    
    # 3. Format for Frontend
    category_breakdown = []
    for cat, s in category_temp.items():
        category_breakdown.append({"category": cat, "dead_items": s["dead_items"], "slow_items": s["slow_items"], "healthy_items": s["healthy_items"], "value": round(s["dead_value"], 2)})
    
    supplier_performance = []
    for sup, loss in supplier_temp.items():
        if loss > 0: supplier_performance.append({"supplier": sup, "expiry_loss": round(loss, 2)})
    supplier_performance.sort(key=lambda x: x["expiry_loss"], reverse=True)

    # Sort items by worst risk category then days_to_expiry
    risk_order = {"Expired": 0, "Critical (< 7d)": 1, "High (8-21d)": 2, "Medium (22-90d)": 3, "Low Risk": 4}
    items.sort(key=lambda x: (risk_order.get(x["expiry_risk"], 4), x["days_to_expiry"]))

    return {
        "summary": summary,
        "category_breakdown": category_breakdown,
        "sku_stats": sku_stats,
        "items": items,
        "supplier_performance": supplier_performance
    }
