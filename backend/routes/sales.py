from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
import pandas as pd
import os
import json
from datetime import datetime, timedelta, timezone

from middleware.auth_middleware import verify_token
from logic.pattern_detector import load_sales, analyse_sku, get_effective_today

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


@router.get("/trends")
def get_trends(
    sku: str = Query(...),
    days: int = Query(30),
    payload: dict = Depends(verify_token),
):
    df = load_sales()
    # Robust matching: Convert to string and strip
    sku_target = str(sku).strip().upper()
    
    sku_df = df[df["StockCode"] == sku_target].copy()

    today = get_effective_today(df)
            
    cutoff = pd.Timestamp(today - timedelta(days=days))
    sku_df = sku_df[sku_df["InvoiceDate"] >= cutoff]

    daily = (
        sku_df.groupby(sku_df["InvoiceDate"].dt.date)["Quantity"]
        .sum()
        .reset_index()
    )
    daily.columns = ["date", "quantity"]
    daily["date"] = daily["date"].astype(str)

    weekly = (
        sku_df.groupby(sku_df["InvoiceDate"].dt.to_period("W"))["Quantity"]
        .sum()
        .reset_index()
    )
    weekly.columns = ["week", "quantity"]
    weekly["week"] = weekly["week"].astype(str)

    pattern = analyse_sku(sku, df)

    total = int(sku_df["Quantity"].sum())
    avg_daily = round(float(daily["quantity"].mean()), 2) if not daily.empty else 0
    peak_day = str(daily.loc[daily["quantity"].idxmax(), "date"]) if not daily.empty else None
    peak_qty = int(daily["quantity"].max()) if not daily.empty else 0

    return {
        "sku": sku,
        "daily_sales": daily.to_dict(orient="records"),
        "weekly_totals": weekly.to_dict(orient="records"),
        "pattern_dates": pattern.get("pattern_dates", []),
        "payday_spike": pattern.get("payday_spike", False),
        "declining_trend": pattern.get("declining_trend", False),
        "summary": {
            "total": total,
            "avg_daily_sales": avg_daily,
            "peak_day": peak_day,
            "peak_qty": peak_qty,
        },
    }


class SaleRequest(BaseModel):
    sku: str
    quantity: float

@router.post("/record")
def record_sale(
    body: SaleRequest,
    payload: dict = Depends(verify_token)
):
    sku = body.sku.strip().upper()
    qty_to_reduce = body.quantity
    
    if qty_to_reduce <= 0:
        raise HTTPException(status_code=400, detail="Quantity must be positive")

    batches_csv = os.path.join(DATA_DIR, "inventory_batches.csv")
    products_csv = os.path.join(DATA_DIR, "products.csv")
    sales_csv = os.path.join(DATA_DIR, "sales.csv")

    try:
        df_batches = pd.read_csv(batches_csv)
        # Ensure dates are parsed correctly for sorting
        df_batches["expiry_date"] = pd.to_datetime(df_batches["expiry_date"])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load batches: {e}")

    # 1. FEFO: Find active batches for this SKU, sorted by expiry_date
    sku_mask = (df_batches["sku"].str.upper() == sku) & (df_batches["status"] == "active") & (df_batches["quantity"] > 0)
    sku_batches = df_batches[sku_mask].sort_values("expiry_date").index.tolist()

    if not sku_batches:
         raise HTTPException(status_code=400, detail="No active batches found for this product")

    total_available = df_batches.loc[sku_batches, "quantity"].sum()
    if total_available < qty_to_reduce:
        raise HTTPException(status_code=400, detail=f"Insufficient stock. Available: {total_available}")

    # 2. Reduce stock from batches
    reduced_qty = 0
    for idx in sku_batches:
        if qty_to_reduce <= 0:
            break
        
        batch_qty = df_batches.at[idx, "quantity"]
        if batch_qty <= qty_to_reduce:
            # Consume entire batch
            df_batches.at[idx, "quantity"] = 0
            df_batches.at[idx, "status"] = "consumed"
            qty_to_reduce -= batch_qty
            reduced_qty += batch_qty
        else:
            # Partial consumption
            df_batches.at[idx, "quantity"] = batch_qty - qty_to_reduce
            reduced_qty += qty_to_reduce
            qty_to_reduce = 0

    # 3. Save Batches
    # Convert dates back to string
    df_batches["expiry_date"] = df_batches["expiry_date"].dt.strftime("%Y-%m-%d")
    df_batches.to_csv(batches_csv, index=False)

    # 4. Update Product Master Stock
    try:
        df_prods = pd.read_csv(products_csv)
        p_idx = df_prods[df_prods["sku"].str.upper() == sku].index
        if not p_idx.empty:
            df_prods.at[p_idx[0], "current_stock"] -= body.quantity
            df_prods.to_csv(products_csv, index=False)
    except Exception as e:
        print(f"Error updating product master: {e}")

    # 5. Record in Sales History
    try:
        new_sale = {
            "InvoiceNo": f"SALE-{int(datetime.now().timestamp())}",
            "StockCode": sku,
            "Description": "Manual Sale Entry",
            "Quantity": body.quantity,
            "InvoiceDate": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "UnitPrice": 0, # Should ideally pull from product
            "CustomerID": "0",
            "Country": "Online"
        }
        df_sales = pd.read_csv(sales_csv)
        df_sales = pd.concat([df_sales, pd.DataFrame([new_sale])], ignore_index=True)
        df_sales.to_csv(sales_csv, index=False)
    except Exception as e:
        print(f"Error recording sale: {e}")

    return {"message": "Sale recorded successfully", "sku": sku, "quantity": body.quantity}

@router.get("/summary")
async def get_summary(payload: dict = Depends(verify_token)):
    """
    KPI summary for the dashboard.
    stockout_risk and pending_recommendations are sourced directly from brief_log.json
    (the same cache used by advisor.py /brief/today) to guarantee consistency.
    """
    df = load_sales()
    from routes.inventory import load_products as load_inventory_products
    products_list = load_inventory_products()
    products_df = pd.DataFrame(products_list).fillna("")

    # AGGREGATE products by SKU to get total_products count
    agg_config = {
        "name": "first",
        "category": "first",
        "current_stock": "sum",
        "lead_time_days": "first"
    }
    for col in ["unit", "unit_price", "supplier_name", "reorder_threshold"]:
        if col in products_df.columns:
            agg_config[col] = "first"
    sku_agg_df = products_df.groupby("sku").agg(agg_config).reset_index()
    unique_products = sku_agg_df.fillna("").to_dict(orient="records")

    # Real 'today' for tracking decisions
    real_today = datetime.now(timezone.utc)
    real_week_start = real_today - timedelta(days=7)
    today_str = real_today.strftime("%Y-%m-%d")

    # Decision overrides
    override_path = os.path.join(DATA_DIR, "override_history.json")
    try:
        with open(override_path) as f:
            overrides = json.load(f)
    except Exception:
        overrides = []

    # -----------------------------------------------------------------------
    # KPI 1 & 2: Read directly from brief_log.json — the authoritative source.
    # This guarantees stockout_risk and pending_recommendations always match
    # what the daily brief page displays (advisor.py uses the same cache).
    # -----------------------------------------------------------------------
    brief_log_path = os.path.join(DATA_DIR, "brief_log.json")
    try:
        with open(brief_log_path) as f:
            brief_log = json.load(f)
    except Exception:
        brief_log = {}

    today_brief_items = brief_log.get(today_str, {}).get("items", [])

    # Decided SKUs within the last 48 h (status != cancelled)
    limit_ts = (real_today - timedelta(hours=48)).isoformat()
    decided_skus: set = set()
    latest_decisions: dict = {}
    for o in overrides:
        ts = o.get("timestamp", "")
        upd = o.get("last_updated", "")
        relevant_ts = max(ts, upd)
        if relevant_ts >= limit_ts:
            sku = str(o.get("sku", "")).strip().upper()
            prev_ts = max(
                latest_decisions.get(sku, {}).get("timestamp", ""),
                latest_decisions.get(sku, {}).get("last_updated", "")
            )
            if sku not in latest_decisions or relevant_ts > prev_ts:
                latest_decisions[sku] = o
    decided_skus = {
        sku for sku, rec in latest_decisions.items()
        if rec.get("status") != "cancelled"
    }

    # Pending items = brief items whose SKU has not been decided yet
    pending_items = [
        item for item in today_brief_items
        if str(item.get("sku", "")).strip().upper() not in decided_skus
    ]

    # Stockout Risk = CRITICAL_STOCKOUT items still pending
    stockout_risk = len([
        item for item in pending_items
        if item.get("risk_level") == "CRITICAL_STOCKOUT"
    ])

    # Pending Review = all pending brief items (urgent + normal)
    pending_recom_count = len(pending_items)

    # -----------------------------------------------------------------------
    # Decision metrics (unchanged)
    # -----------------------------------------------------------------------
    week_orders = [
        o for o in overrides
        if (o.get("last_updated") or o.get("timestamp", "")) >= real_week_start.isoformat()
        and o.get("status") in ("approved", "ordered", "received", "overridden")
        and o.get("status") != "cancelled"
    ]

    valid_decisions = [o for o in overrides if o.get("status") != "cancelled"]
    approved = [o for o in valid_decisions if o.get("decision") in ("approved", "ordered", "received")]
    total_decided = len([
        o for o in valid_decisions
        if o.get("decision") in ("approved", "overridden", "skipped", "ordered", "received")
    ])
    accuracy = round(len(approved) / total_decided * 100) if total_decided > 0 else 0

    return {
        "stockout_risk": stockout_risk,
        "pending_recommendations": pending_recom_count,
        "orders_this_week": len(week_orders),
        "ai_accuracy_pct": accuracy,
        "total_products": len(unique_products),
        "total_sales_rows": len(df),
    }
