from fastapi import APIRouter, Depends, Query, HTTPException
import pandas as pd
import os
from datetime import datetime, timedelta
from typing import List, Optional

from middleware.auth_middleware import verify_token
from logic.pattern_detector import get_avg_sales_map
from logic.chatbot_data import data_manager

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

def _refresh_chatbot_expiry():
    """Instantly re-sync the chatbot's expiry + product caches after a batch write."""
    try:
        data_manager._refresh_expiry_cache()
    except Exception:
        pass

def get_expiry_status(days_to_expiry: int) -> str:
    if days_to_expiry <= 0:
        return "Expired"
    elif days_to_expiry <= 7:
        return "Expiring Soon"
    elif days_to_expiry <= 15:
        return "High Risk"
    elif days_to_expiry <= 30:
        return "Caution"
    elif days_to_expiry <= 60:
        return "Monitor"
    else:
        return "Healthy"

def get_status_color(status: str) -> str:
    return {
        "Expired": "#dc3545",
        "Expiring Soon": "#fd7e14",
        "High Risk": "#f8c122",
        "Caution": "#ffc107",
        "Monitor": "#17a2b8",
        "Healthy": "#28a745",
        "Disposed": "#6c757d"
    }.get(status, "#6c757d")


def sync_expired_batches(batches_csv: str) -> "pd.DataFrame":
    """
    Read inventory_batches.csv and persist the lifecycle transition
    'active' -> 'expired' for any batch whose expiry_date has passed.
    This keeps the CSV's `status` column in sync with the computed
    dashboard status instead of only reflecting it in-memory.
    Returns the (possibly updated) DataFrame.
    """
    df = pd.read_csv(batches_csv).fillna("")
    if "status" not in df.columns or "expiry_date" not in df.columns:
        return df

    today = datetime.now()
    changed = False

    for idx, row in df.iterrows():
        if row.get("status") != "active":
            continue
        try:
            expiry_dt = datetime.strptime(str(row["expiry_date"]), "%Y-%m-%d")
        except Exception:
            continue
        days_to_expiry = (expiry_dt - today).days
        if days_to_expiry <= 0:
            df.at[idx, "status"] = "expired"
            changed = True

    if changed:
        df.to_csv(batches_csv, index=False)
        df = df.fillna("")

    return df


@router.get("/dashboard")
def get_expiry_dashboard(payload: dict = Depends(verify_token)):
    batches_csv = os.path.join(DATA_DIR, "inventory_batches.csv")
    products_csv = os.path.join(DATA_DIR, "products.csv")
    
    if not os.path.exists(batches_csv):
        return {"summary": {}, "batches": [], "charts": {}}

    df_batches = sync_expired_batches(batches_csv)
    df_products = pd.read_csv(products_csv).fillna("")
    
    # Pre-calculate sales velocity
    avg_sales_map = get_avg_sales_map()
    
    # Map product details (category, unit_price) to batches
    prod_map = df_products.set_index("sku")[["category", "unit_price", "name"]].to_dict("index")
    
    today = datetime.now()
    
    batches_data = []
    summary = {
        "total_batches": 0,
        "total_value": 0,
        "expired_qty": 0,
        "at_risk_value": 0,
        "disposed_count": int((df_batches["status"] == "disposed").sum()),
        "status_counts": {
            "Healthy": 0, "Monitor": 0, "Caution": 0, 
            "High Risk": 0, "Expiring Soon": 0, "Expired": 0
        }
    }

    for _, row in df_batches.iterrows():
        if row.get("status") not in ["active", "expired"]:
            continue
            
        sku = str(row["sku"]).strip().upper()
        p_info = prod_map.get(sku, {"category": "Unknown", "unit_price": 0, "name": row.get("product_name", sku)})
        
        qty = float(row["quantity"])
        if qty <= 0: continue
        
        unit_price = float(p_info.get("unit_price", 0))
        total_price = qty * unit_price
        
        try:
            expiry_dt = datetime.strptime(str(row["expiry_date"]), "%Y-%m-%d")
            days_to_expiry = (expiry_dt.date() - today.date()).days
        except:
            days_to_expiry = 999
            
        status = get_expiry_status(days_to_expiry)
        
        # Summary updates
        summary["total_batches"] += 1
        summary["total_value"] += total_price
        summary["status_counts"][status] += 1
        
        if status == "Expired":
            summary["expired_qty"] += qty
        if status in ["High Risk", "Expiring Soon", "Caution"]:
            summary["at_risk_value"] += total_price

        # Recommendation logic
        avg_v = avg_sales_map.get(sku, 0)
        expected_sales = avg_v * max(0, days_to_expiry)
        risk_qty = max(0, qty - expected_sales)
        
        recommendation = "Maintain"
        if status == "Expired":
            recommendation = "Dispose/Remove"
        elif risk_qty > 0:
            if status == "Expiring Soon":
                recommendation = "Clearance Sale (50% Off)"
            elif status == "High Risk":
                recommendation = "Bundle Offer / Promo"
            elif status == "Caution":
                recommendation = "Feature in 'Fresh' Section"
        
        batches_data.append({
            "sku": sku,
            "product_name": p_info.get("name", sku),
            "batch_no": row["batch_no"],
            "quantity": qty,
            "expiry_date": row["expiry_date"],
            "days_left": days_to_expiry,
            "status": status,
            "status_color": get_status_color(status),
            "value": round(total_price, 2),
            "category": p_info["category"],
            "recommendation": recommendation,
            "risk_qty": round(risk_qty, 1)
        })

    # Sort batches by expiry (closest first)
    batches_data.sort(key=lambda x: x["days_left"])

    # Chart data: Status Distribution
    status_chart = [
        {"name": k, "value": v, "color": get_status_color(k)} 
        for k, v in summary["status_counts"].items() if v > 0
    ]
    
    # Category Distribution
    cat_counts = {}
    for b in batches_data:
        c = b["category"]
        cat_counts[c] = cat_counts.get(c, 0) + b["value"]
    
    category_chart = [{"name": k, "value": round(v, 2)} for k, v in cat_counts.items()]
    category_chart.sort(key=lambda x: x["value"], reverse=True)

    return {
        "summary": summary,
        "batches": batches_data,
        "charts": {
            "status_dist": status_chart,
            "category_dist": category_chart[:10] # Top 10
        }
    }


@router.post("/dispose/{batch_no}")
def dispose_batch(batch_no: str, payload: dict = Depends(verify_token)):
    """Mark a batch as 'disposed' — removes it from active inventory tracking."""
    batches_csv = os.path.join(DATA_DIR, "inventory_batches.csv")
    if not os.path.exists(batches_csv):
        raise HTTPException(status_code=404, detail="Batch file not found")

    try:
        df = pd.read_csv(batches_csv)
        mask = df["batch_no"].astype(str) == str(batch_no)
        if not mask.any():
            raise HTTPException(status_code=404, detail=f"Batch '{batch_no}' not found")

        # Record disposal metadata
        original_qty = float(df.loc[mask, "quantity"].values[0])
        df.loc[mask, "status"] = "disposed"
        df.loc[mask, "disposed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        df.loc[mask, "disposed_by"] = payload.get("sub", "unknown")
        # Zero out quantity so it is excluded from stock calculations
        df.loc[mask, "quantity"] = 0.0

        df.to_csv(batches_csv, index=False)

        _refresh_chatbot_expiry()

        batch_row = df[mask].iloc[0]
        return {
            "success": True,
            "message": f"Batch {batch_no} disposed successfully.",
            "batch_no": batch_no,
            "product_name": str(batch_row.get("product_name", "")),
            "sku": str(batch_row.get("sku", "")),
            "original_qty": original_qty,
            "disposed_at": str(batch_row.get("disposed_at", ""))
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/disposed")
def get_disposed_batches(payload: dict = Depends(verify_token)):
    """Return all batches that have been disposed."""
    batches_csv = os.path.join(DATA_DIR, "inventory_batches.csv")
    products_csv = os.path.join(DATA_DIR, "products.csv")
    if not os.path.exists(batches_csv):
        return []

    try:
        df = pd.read_csv(batches_csv).fillna("")
        disposed = df[df["status"] == "disposed"].copy()

        if disposed.empty:
            return []

        # Merge product info
        if os.path.exists(products_csv):
            prods = pd.read_csv(products_csv).fillna("")
            prod_map = prods.set_index("sku")[["category", "unit_price", "name"]].to_dict("index")
        else:
            prod_map = {}

        result = []
        for _, row in disposed.iterrows():
            sku = str(row.get("sku", "")).strip().upper()
            p_info = prod_map.get(sku, {"category": "Unknown", "unit_price": 0, "name": row.get("product_name", sku)})
            result.append({
                "batch_no": row.get("batch_no", ""),
                "sku": sku,
                "product_name": p_info.get("name", row.get("product_name", sku)),
                "category": p_info.get("category", "Unknown"),
                "expiry_date": row.get("expiry_date", ""),
                "disposed_at": row.get("disposed_at", ""),
                "disposed_by": row.get("disposed_by", ""),
            })

        result.sort(key=lambda x: x["disposed_at"], reverse=True)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
