"""Admin routes for viewing, exporting and uploading customer orders to sales data."""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
import pandas as pd
import os
import json
import threading
from datetime import datetime, timezone

from middleware.auth_middleware import require_role
from routes.inventory import deduct_stock_for_sales
from logic.chatbot_data import data_manager

def _refresh_chatbot_sales():
    """Trigger chatbot data reload so live context includes new sales instantly."""
    import threading
    def _run():
        try:
            data_manager.reload_all()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

_invoice_lock = threading.Lock()


def _next_invoice_no_unsafe(sales_csv: str, orders_csv: str) -> str:
    """Return next INV###### not present in either CSV. Caller must hold _invoice_lock."""
    used: set[int] = set()
    for path, col in [(sales_csv, "InvoiceNo"), (orders_csv, "invoice_no")]:
        if not os.path.exists(path):
            continue
        try:
            df = pd.read_csv(path, dtype=str).fillna("")
            if col in df.columns:
                for val in df[col]:
                    v = str(val).strip()
                    if v.startswith("INV") and v[3:].isdigit():
                        used.add(int(v[3:]))
        except Exception:
            pass
    next_num = (max(used) + 1) if used else 100001
    return f"INV{next_num}"

router = APIRouter()
DATA_DIR      = os.path.join(os.path.dirname(__file__), "..", "data")
ORDERS_CSV    = os.path.join(DATA_DIR, "customer_orders.csv")
SALES_CSV     = os.path.join(DATA_DIR, "sales.csv")
CUSTOMERS_CSV = os.path.join(DATA_DIR, "customers.csv")

# ── ID helpers ────────────────────────────────────────────────────────────────

def _customer_number_map() -> dict:
    """Return {uuid -> customer_number} from customers.csv.

    Self-healing: if customer_number column is missing or any row has a blank
    value, assigns sequential numeric IDs (starting at 20001) and persists them.
    """
    if not os.path.exists(CUSTOMERS_CSV):
        return {}
    try:
        df = pd.read_csv(CUSTOMERS_CSV, dtype=str).fillna("")
        if "id" not in df.columns:
            return {}
        changed = False
        if "customer_number" not in df.columns:
            df["customer_number"] = [str(20001 + i) for i in range(len(df))]
            changed = True
        else:
            # Backfill any blank/non-numeric customer_number values
            nums = pd.to_numeric(df["customer_number"], errors="coerce")
            max_num = int(nums.max()) if not nums.isna().all() else 20000
            for idx in df[nums.isna()].index:
                max_num += 1
                df.at[idx, "customer_number"] = str(max_num)
                changed = True
        if changed:
            df.to_csv(CUSTOMERS_CSV, index=False)
        return dict(zip(df["id"].str.strip(), df["customer_number"].str.strip()))
    except Exception:
        return {}


ORDER_COLS = ["order_id","invoice_no","customer_id","customer_name","customer_email","customer_mobile",
              "items_json","delivery_address","contact_number","payment_method",
              "subtotal","discount","total_amount","status","order_date","uploaded_to_sales"]


def load_orders() -> pd.DataFrame:
    if not os.path.exists(ORDERS_CSV):
        return pd.DataFrame(columns=ORDER_COLS)
    df = pd.read_csv(ORDERS_CSV, dtype=str).fillna("")
    # Backfill invoice_no for any existing orders that are missing it
    if "invoice_no" not in df.columns:
        df["invoice_no"] = ""
    missing_mask = df["invoice_no"].str.strip() == ""
    if missing_mask.any():
        with _invoice_lock:
            for idx in df[missing_mask].index:
                df.at[idx, "invoice_no"] = _next_invoice_no_unsafe(SALES_CSV, ORDERS_CSV)
                # Temporarily write to avoid re-using the same number next iteration
                df.to_csv(ORDERS_CSV, index=False)
    return df


def save_orders(df: pd.DataFrame):
    df.to_csv(ORDERS_CSV, index=False)


@router.get("/")
async def list_customer_orders(
    search: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    payload: dict = Depends(require_role("admin")),
):
    df = load_orders()
    if df.empty:
        summary = {"total_orders": 0, "today_orders": 0, "total_revenue": 0.0, "avg_order_value": 0.0}
        return {"orders": [], "total": 0, "page": page, "per_page": per_page, "total_pages": 0, "summary": summary}

    # Flatten orders (one row per order, items as list)
    records = []
    today_str = datetime.now().strftime("%Y-%m-%d")

    for _, row in df.iterrows():
        try:
            items = json.loads(row.get("items_json", "[]"))
        except Exception:
            items = []

        product_names = ", ".join([i.get("name", i.get("sku", "")) for i in items])
        order_date_str = str(row.get("order_date", ""))[:10]

        records.append({
            "order_id": row["order_id"],
            "customer_id": row["customer_id"],
            "customer_name": row["customer_name"],
            "customer_email": row["customer_email"],
            "customer_mobile": row["customer_mobile"],
            "items": items,
            "product_names": product_names,
            "delivery_address": row["delivery_address"],
            "contact_number": row["contact_number"],
            "payment_method": row["payment_method"],
            "subtotal": float(row.get("subtotal", 0) or 0),
            "discount": float(row.get("discount", 0) or 0),
            "total_amount": float(row.get("total_amount", 0) or 0),
            "status": row.get("status", "confirmed"),
            "order_date": row.get("order_date", ""),
            "order_date_str": order_date_str,
            "uploaded_to_sales": row.get("uploaded_to_sales", "False"),
        })

    # Summary (before filters)
    total_revenue = sum(r["total_amount"] for r in records)
    today_orders  = sum(1 for r in records if r["order_date_str"] == today_str)
    avg_val       = total_revenue / len(records) if records else 0.0
    summary = {
        "total_orders":    len(records),
        "today_orders":    today_orders,
        "total_revenue":   round(total_revenue, 2),
        "avg_order_value": round(avg_val, 2),
    }

    # Filters
    if search:
        q = search.lower()
        records = [r for r in records if
                   q in r["customer_name"].lower() or
                   q in r["customer_email"].lower() or
                   q in r["order_id"].lower() or
                   q in r["product_names"].lower()]
    if status:
        records = [r for r in records if r["status"].lower() == status.lower()]
    if date_from:
        records = [r for r in records if r["order_date_str"] >= date_from]
    if date_to:
        records = [r for r in records if r["order_date_str"] <= date_to]

    # Sort newest first
    records.sort(key=lambda x: x["order_date"], reverse=True)

    total       = len(records)
    total_pages = max(1, -(-total // per_page))
    start       = (page - 1) * per_page

    return {
        "orders":      records[start: start + per_page],
        "total":       total,
        "page":        page,
        "per_page":    per_page,
        "total_pages": total_pages,
        "summary":     summary,
    }


@router.post("/upload-to-sales")
async def upload_to_sales(payload: dict = Depends(require_role("admin"))):
    """Convert unuploaded customer orders to sales.csv rows."""
    df = load_orders()
    if df.empty:
        return {"message": "No orders found.", "appended": 0}

    pending = df[df["uploaded_to_sales"].str.lower() != "true"]
    if pending.empty:
        return {"message": "No new orders to upload.", "appended": 0}

    # Load existing sales to detect duplicates by InvoiceNo
    if os.path.exists(SALES_CSV):
        sales_df = pd.read_csv(SALES_CSV, dtype=str).fillna("")
        existing_invoices = set(sales_df["InvoiceNo"].str.strip().tolist())
    else:
        sales_df = pd.DataFrame(columns=["InvoiceNo","StockCode","Description","Quantity","InvoiceDate","UnitPrice","CustomerID","Country"])
        existing_invoices = set()

    new_sales_rows = []
    appended_order_ids = []
    already_uploaded_order_ids = []  # orders already in sales.csv but not marked as uploaded

    cust_num_map = _customer_number_map()

    for _, row in pending.iterrows():
        order_id   = row["order_id"]
        invoice_no = str(row.get("invoice_no", "")).strip()
        # Skip if this invoice already appears in sales (by invoice_no or legacy order_id)
        if invoice_no in existing_invoices or order_id in existing_invoices:
            # Already in sales.csv — just needs to be marked as uploaded
            already_uploaded_order_ids.append(order_id)
            continue
        try:
            items = json.loads(row.get("items_json", "[]"))
        except Exception:
            items = []
        customer_id = row.get("customer_id", "")
        customer_no = cust_num_map.get(customer_id, "")
        if not customer_no:
            customer_no = customer_id  # last-resort fallback only
        order_date  = str(row.get("order_date", ""))[:10] + " 00:00:00"
        for item in items:
            new_sales_rows.append({
                "InvoiceNo":   invoice_no,
                "StockCode":   item.get("sku", ""),
                "Description": item.get("name", ""),
                "Quantity":    str(item.get("quantity", 1)),
                "InvoiceDate": order_date,
                "UnitPrice":   str(item.get("unit_price", 0)),
                "CustomerID":  customer_no,
                "Country":     "India",
            })
        appended_order_ids.append(order_id)

    # Mark orders that were already in sales.csv as uploaded (fixes stale Pending state)
    all_ids_to_mark = appended_order_ids + already_uploaded_order_ids
    if not new_sales_rows and not already_uploaded_order_ids:
        return {"message": "No new records to append (all already uploaded).", "appended": 0}

    if new_sales_rows:
        new_sales_df  = pd.DataFrame(new_sales_rows)
        combined      = pd.concat([sales_df, new_sales_df], ignore_index=True)
        combined.to_csv(SALES_CSV, index=False)

        # Deduct stock for the newly uploaded sales rows (FEFO per batch)
        deduct_stock_for_sales(new_sales_rows)

    # Mark all relevant orders as uploaded
    for oid in all_ids_to_mark:
        df.loc[df["order_id"] == oid, "uploaded_to_sales"] = "True"
    save_orders(df)

    if not new_sales_rows:
        _refresh_chatbot_sales()
        return {
            "message":  f"Marked {len(already_uploaded_order_ids)} order(s) as uploaded (data was already in sales).",
            "appended": 0,
            "orders":   already_uploaded_order_ids,
        }

    _refresh_chatbot_sales()
    return {
        "message":  f"Successfully appended {len(new_sales_rows)} sales record(s) from {len(appended_order_ids)} order(s).",
        "appended": len(new_sales_rows),
        "orders":   appended_order_ids,
    }


@router.get("/export")
async def export_orders(
    search: Optional[str] = None,
    status: Optional[str] = None,
    payload: dict = Depends(require_role("admin")),
):
    """Return orders in sales.csv format (one row per item) so the exported CSV
    can be directly appended to sales.csv without reformatting."""
    df = load_orders()
    if df.empty:
        return []

    # Apply filters first (order-level)
    records = df.copy()
    if status:
        records = records[records["status"].str.lower() == status.lower()]
    if search:
        q = search.lower()
        mask = (
            records["customer_name"].str.lower().str.contains(q, na=False) |
            records["customer_email"].str.lower().str.contains(q, na=False) |
            records["order_id"].str.lower().str.contains(q, na=False)
        )
        records = records[mask]

    cust_num_map = _customer_number_map()
    rows = []

    for _, row in records.iterrows():
        invoice_no  = str(row.get("invoice_no", "")).strip()
        customer_id = row.get("customer_id", "")
        customer_no = cust_num_map.get(customer_id, "") or customer_id
        order_date  = str(row.get("order_date", ""))[:10] + " 00:00:00"
        try:
            items = json.loads(row.get("items_json", "[]"))
        except Exception:
            items = []
        for item in items:
            rows.append({
                "InvoiceNo":   invoice_no,
                "StockCode":   item.get("sku", ""),
                "Description": item.get("name", ""),
                "Quantity":    item.get("quantity", 1),
                "InvoiceDate": order_date,
                "UnitPrice":   item.get("unit_price", 0),
                "CustomerID":  customer_no,
                "Country":     "India",
            })

    return rows
