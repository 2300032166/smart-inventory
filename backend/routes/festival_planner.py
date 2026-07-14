"""
Festival Inventory Planner module.

Fully independent read-only module. Reads festival data from the provided
Excel mapping files (festival_dates_mapping.xlsx, festival_product_mapping.xlsx)
and cross-references product stock/supplier/expiry info from the existing
products.csv / inventory_batches.csv datasets.

Does NOT perform demand forecasting, reorder calculations, or touch the
Inventory Replenishment / Inventory Advisor modules in any way.
"""
from fastapi import APIRouter, Depends, HTTPException
import os
import math
from datetime import date, datetime
import pandas as pd

from middleware.auth_middleware import require_manager_or_admin

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FESTIVAL_DATES_FILE = os.path.join(DATA_DIR, "festival_dates_mapping.xlsx")
FESTIVAL_PRODUCTS_FILE = os.path.join(DATA_DIR, "festival_product_mapping.xlsx")
PRODUCTS_FILE = os.path.join(DATA_DIR, "products.csv")
BATCHES_FILE = os.path.join(DATA_DIR, "inventory_batches.csv")


def _parse_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return pd.to_datetime(value).date()


def _festival_status(start: date, end: date, today: date):
    if today < start:
        return "Upcoming", (start - today).days
    if start <= today <= end:
        return "Ongoing", 0
    return "Completed", None


def load_festival_dates() -> pd.DataFrame:
    if not os.path.exists(FESTIVAL_DATES_FILE):
        raise HTTPException(status_code=500, detail="Festival dates mapping file not found")
    df = pd.read_excel(FESTIVAL_DATES_FILE)
    df.columns = [c.strip() for c in df.columns]
    return df


def load_festival_products() -> pd.DataFrame:
    if not os.path.exists(FESTIVAL_PRODUCTS_FILE):
        raise HTTPException(status_code=500, detail="Festival product mapping file not found")
    df = pd.read_excel(FESTIVAL_PRODUCTS_FILE)
    df.columns = [c.strip() for c in df.columns]
    return df


def load_products_map() -> dict:
    """Map sku -> product dict (current_stock, reorder_threshold, supplier_name)."""
    if not os.path.exists(PRODUCTS_FILE):
        return {}
    df = pd.read_csv(PRODUCTS_FILE)
    products = {}
    for _, row in df.iterrows():
        sku = str(row.get("sku", "")).strip()
        if not sku:
            continue
        products[sku] = {
            "current_stock": float(row.get("current_stock", 0) or 0),
            "reorder_threshold": float(row.get("reorder_threshold", 0) or 0),
            "supplier_name": row.get("supplier_name") or "—",
        }
    return products


def load_earliest_expiry_map() -> dict:
    """Map sku -> earliest (soonest) non-disposed batch expiry_date (ISO string), and supplier fallback."""
    if not os.path.exists(BATCHES_FILE):
        return {}
    df = pd.read_csv(BATCHES_FILE)
    result = {}
    for _, row in df.iterrows():
        sku = str(row.get("sku", "")).strip()
        if not sku:
            continue
        status = str(row.get("status", "")).strip().lower()
        if status in ("disposed", "expired"):
            continue
        expiry_raw = row.get("expiry_date")
        if not expiry_raw or pd.isna(expiry_raw):
            continue
        try:
            expiry_dt = pd.to_datetime(expiry_raw).date()
        except Exception:
            continue
        existing = result.get(sku)
        if existing is None or expiry_dt < existing["expiry_date"]:
            result[sku] = {
                "expiry_date": expiry_dt,
                "supplier": row.get("supplier") or None,
            }
    return result


def derive_priority(rank: int, total: int) -> str:
    """Derive a priority tier since the source mapping data has no Priority column.

    Products are ranked by their order within the festival's mapping rows;
    top third = High, middle third = Medium, bottom third = Low.
    """
    if total <= 0:
        return "Medium"
    third = math.ceil(total / 3)
    if rank < third:
        return "High"
    if rank < 2 * third:
        return "Medium"
    return "Low"


def get_stock_status(current_stock, reorder_threshold, found: bool) -> str:
    if not found:
        return "Not Available"
    if current_stock <= 0:
        return "Out of Stock"
    if current_stock <= reorder_threshold:
        return "Low Stock"
    return "In Stock"


def build_festival_summary(row, today: date) -> dict:
    start = _parse_date(row["Start Date"])
    end = _parse_date(row["End Date"])
    status, days_remaining = _festival_status(start, end, today)
    return {
        "festival_id": str(row["Festival ID"]),
        "festival_name": str(row["Festival Name"]),
        "description": str(row.get("Description", "")),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "duration_days": int(row.get("Duration (Days)", (end - start).days + 1)),
        "status": status,
        "days_remaining": days_remaining,
    }


def _sort_key(f: dict) -> tuple:
    """Completed festivals at bottom; upcoming/ongoing at top sorted by start date."""
    status_order = {"Upcoming": 0, "Ongoing": 1, "Completed": 2}
    return (status_order.get(f["status"], 2), f["start_date"])


@router.get("/festivals")
def get_festivals(payload: dict = Depends(require_manager_or_admin())):
    """List all festivals with computed status and days remaining."""
    df = load_festival_dates()
    today = date.today()
    festivals = [build_festival_summary(row, today) for _, row in df.iterrows()]
    festivals.sort(key=_sort_key)
    return {"festivals": festivals}


@router.get("/festivals/{festival_id}")
def get_festival_detail(festival_id: str, payload: dict = Depends(require_manager_or_admin())):
    """Return festival details, mapped products (with live stock info), stats, and alerts."""
    dates_df = load_festival_dates()
    match = dates_df[dates_df["Festival ID"].astype(str) == str(festival_id)]
    if match.empty:
        raise HTTPException(status_code=404, detail="Festival not found")

    today = date.today()
    festival = build_festival_summary(match.iloc[0], today)
    festival_start = _parse_date(match.iloc[0]["Start Date"])

    products_df = load_festival_products()
    mapped = products_df[products_df["Festival ID"].astype(str) == str(festival_id)].reset_index(drop=True)

    products_map = load_products_map()
    expiry_map = load_earliest_expiry_map()

    total = len(mapped)
    products = []
    for idx, row in mapped.iterrows():
        product_id = str(row["Product ID"]).strip()
        product_name = str(row["Product Name"])
        inv = products_map.get(product_id)
        found = inv is not None
        current_stock = inv["current_stock"] if found else 0
        reorder_threshold = inv["reorder_threshold"] if found else 0
        supplier = inv["supplier_name"] if found else "—"
        stock_status = get_stock_status(current_stock, reorder_threshold, found)

        expiry_info = expiry_map.get(product_id)
        expiry_date = expiry_info["expiry_date"].isoformat() if expiry_info else None
        expires_before_festival = bool(
            expiry_info and festival["status"] != "Completed" and expiry_info["expiry_date"] < festival_start
        )
        if not found and expiry_info and expiry_info.get("supplier"):
            supplier = expiry_info["supplier"]

        products.append({
            "product_id": product_id,
            "product_name": product_name,
            "priority": derive_priority(idx, total),
            "current_stock": current_stock if found else None,
            "stock_status": stock_status,
            "supplier": supplier,
            "expiry_date": expiry_date,
            "expires_before_festival": expires_before_festival,
            "in_inventory": found,
        })

    stats = {
        "total_products": total,
        "in_stock": sum(1 for p in products if p["stock_status"] == "In Stock"),
        "low_stock": sum(1 for p in products if p["stock_status"] == "Low Stock"),
        "out_of_stock": sum(1 for p in products if p["stock_status"] == "Out of Stock"),
        "not_available": sum(1 for p in products if p["stock_status"] == "Not Available"),
    }

    alerts = []
    for p in products:
        if p["stock_status"] == "Out of Stock":
            alerts.append({
                "type": "out_of_stock",
                "severity": "critical",
                "message": f"{p['product_name']} is out of stock ahead of {festival['festival_name']}.",
                "product_id": p["product_id"],
            })
        elif p["stock_status"] == "Low Stock":
            alerts.append({
                "type": "low_stock",
                "severity": "warning",
                "message": f"{p['product_name']} has low stock ahead of {festival['festival_name']}.",
                "product_id": p["product_id"],
            })
        elif p["stock_status"] == "Not Available":
            alerts.append({
                "type": "not_available",
                "severity": "info",
                "message": f"{p['product_name']} is not currently tracked in inventory.",
                "product_id": p["product_id"],
            })
        if p["expires_before_festival"]:
            alerts.append({
                "type": "expiring_before_festival",
                "severity": "critical",
                "message": f"{p['product_name']} expires on {p['expiry_date']}, before {festival['festival_name']} starts.",
                "product_id": p["product_id"],
            })

    return {
        "festival": festival,
        "stats": stats,
        "products": products,
        "alerts": alerts,
    }
