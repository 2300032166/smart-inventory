from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
import pandas as pd
import os
import uuid
import json
import threading
from datetime import datetime, timezone

from middleware.auth_middleware import verify_token

CATEGORY_COLORS = {
    "Beauty & Hygiene": "#f43f5e",
    "Foodgrains, Oil & Masala": "#f59e0b",
    "Snacks & Branded Foods": "#8b5cf6",
    "Beverages": "#06b6d4",
    "Bakery, Cakes & Dairy": "#f97316",
    "Fruits & Vegetables": "#22c55e",
    "Cleaning & Household": "#3b82f6",
    "Baby Care": "#ec4899",
    "Eggs, Meat & Fish": "#ef4444",
    "Pet Care": "#84cc16",
    "Gourmet & World Food": "#a78bfa",
    "Kitchen, Garden & Pets": "#14b8a6",
}

# Per-file locks to prevent concurrent read-modify-write races on shared CSVs
_csv_locks: dict[str, threading.Lock] = {}
_locks_meta = threading.Lock()

def _get_lock(path: str) -> threading.Lock:
    with _locks_meta:
        if path not in _csv_locks:
            _csv_locks[path] = threading.Lock()
        return _csv_locks[path]

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

CART_CSV      = os.path.join(DATA_DIR, "cart.csv")
WISHLIST_CSV  = os.path.join(DATA_DIR, "wishlist.csv")
ORDERS_CSV    = os.path.join(DATA_DIR, "customer_orders.csv")
NOTIF_CSV     = os.path.join(DATA_DIR, "notifications.csv")
PRODUCTS_CSV  = os.path.join(DATA_DIR, "products.csv")
SALES_CSV     = os.path.join(DATA_DIR, "sales.csv")
CUSTOMERS_CSV = os.path.join(DATA_DIR, "customers.csv")

CART_COLS   = ["customer_id", "sku", "quantity", "added_at"]
WISH_COLS   = ["customer_id", "sku", "added_at"]

# Lock for invoice number allocation
_invoice_lock = threading.Lock()


def _next_invoice_no() -> str:
    """Allocate the next collision-free INV###### number.

    Scans both sales.csv and customer_orders.csv for existing INV-prefixed
    numbers, then returns max+1 (range 100000–999999, wraps safely above).
    Must be called while holding _invoice_lock.
    """
    used: set[int] = set()
    for csv_path in (SALES_CSV, ORDERS_CSV):
        if not os.path.exists(csv_path):
            continue
        try:
            df = pd.read_csv(csv_path, dtype=str).fillna("")
            col = "InvoiceNo" if "InvoiceNo" in df.columns else ("invoice_no" if "invoice_no" in df.columns else None)
            if col:
                for val in df[col]:
                    val = str(val).strip()
                    if val.startswith("INV") and val[3:].isdigit():
                        used.add(int(val[3:]))
        except Exception:
            pass
    next_num = (max(used) + 1) if used else 100001
    return f"INV{next_num}"
ORDER_COLS  = ["order_id","invoice_no","customer_id","customer_name","customer_email","customer_mobile",
               "items_json","delivery_address","contact_number","payment_method",
               "subtotal","discount","total_amount","status","order_date","uploaded_to_sales"]
NOTIF_COLS  = ["id","customer_id","type","title","message","is_read","created_at"]


def verify_customer(payload: dict = Depends(verify_token)):
    if payload.get("role") != "customer":
        raise HTTPException(403, "Customer access required")
    return payload


def load_csv(path: str, cols: list) -> pd.DataFrame:
    with _get_lock(path):
        if not os.path.exists(path):
            df = pd.DataFrame(columns=cols)
            df.to_csv(path, index=False)
            return df
        df = pd.read_csv(path, dtype=str)
        return df.fillna("")


def save_csv(df: pd.DataFrame, path: str):
    with _get_lock(path):
        tmp = path + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)


def get_product_info(sku: str) -> dict:
    if not os.path.exists(PRODUCTS_CSV):
        return {}
    try:
        df = pd.read_csv(PRODUCTS_CSV, dtype=str).fillna("")
        rows = df[df["sku"].astype(str).str.strip() == sku.strip()]
        if rows.empty:
            return {}
        row = rows.iloc[0].to_dict()
        return {
            "name": row.get("name", ""),
            "price": float(row.get("unit_price", 0) or 0),
            "category": row.get("category", ""),
            "supplier_name": row.get("supplier_name", ""),
            "current_stock": int(float(row.get("current_stock", 0) or 0)),
        }
    except Exception:
        return {}


def add_notification(customer_id: str, notif_type: str, title: str, message: str):
    df = load_csv(NOTIF_CSV, NOTIF_COLS)
    new_row = pd.DataFrame([{
        "id": str(uuid.uuid4()),
        "customer_id": customer_id,
        "type": notif_type,
        "title": title,
        "message": message,
        "is_read": "False",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    save_csv(df, NOTIF_CSV)


# ═══════════════════════════════════════════════════════════════════════════════
# CART
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/cart")
async def get_cart(payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(CART_CSV, CART_COLS)
    rows = df[df["customer_id"] == cid]

    items, total = [], 0.0
    for _, row in rows.iterrows():
        sku = row["sku"]
        qty = int(row.get("quantity", 1) or 1)
        p = get_product_info(sku)
        price = p.get("price", 0.0)
        sub = round(price * qty, 2)
        total += sub
        category = p.get("category", "")
        items.append({
            "sku": sku,
            "name": p.get("name", sku),
            "price": price,
            "category": category,
            "category_color": CATEGORY_COLORS.get(category, "#6366f1"),
            "quantity": qty,
            "subtotal": sub,
            "in_stock": p.get("current_stock", 0) > 0,
        })

    return {"items": items, "total": round(total, 2), "count": len(items)}


class CartItemBody(BaseModel):
    sku: str
    quantity: int = 1


@router.post("/cart")
async def add_to_cart(body: CartItemBody, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    p = get_product_info(body.sku)
    if not p:
        raise HTTPException(404, "Product not found")
    available = p.get("current_stock", 0)
    if available <= 0:
        raise HTTPException(400, "Product is out of stock")

    df = load_csv(CART_CSV, CART_COLS)
    mask = (df["customer_id"] == cid) & (df["sku"] == body.sku)
    add_qty = max(1, body.quantity)
    in_cart = int(df.loc[mask, "quantity"].values[0] or 0) if df[mask].any().any() else 0
    new_total = in_cart + add_qty

    if new_total > available:
        remaining = available - in_cart
        if remaining <= 0:
            raise HTTPException(400, f"You already have all {available} available unit{'s' if available != 1 else ''} in your cart")
        raise HTTPException(400, f"Only {available} unit{'s' if available != 1 else ''} available — you can add {remaining} more")

    if df[mask].any().any():
        df.loc[mask, "quantity"] = str(new_total)
    else:
        new_row = pd.DataFrame([{
            "customer_id": cid,
            "sku": body.sku,
            "quantity": str(add_qty),
            "added_at": datetime.now(timezone.utc).isoformat(),
        }])
        df = pd.concat([df, new_row], ignore_index=True)

    save_csv(df, CART_CSV)
    return {"message": "Added to cart"}


class UpdateQtyBody(BaseModel):
    quantity: int


@router.put("/cart/{sku}")
async def update_cart(sku: str, body: UpdateQtyBody, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(CART_CSV, CART_COLS)
    mask = (df["customer_id"] == cid) & (df["sku"] == sku)
    if not df[mask].any().any():
        raise HTTPException(404, "Item not in cart")
    if body.quantity <= 0:
        df = df[~mask]
    else:
        p = get_product_info(sku)
        available = p.get("current_stock", 0)
        if available > 0 and body.quantity > available:
            raise HTTPException(400, f"Only {available} unit{'s' if available != 1 else ''} available")
        df.loc[mask, "quantity"] = str(body.quantity)
    save_csv(df, CART_CSV)
    return {"message": "Cart updated"}


@router.delete("/cart/{sku}")
async def remove_from_cart(sku: str, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(CART_CSV, CART_COLS)
    df = df[~((df["customer_id"] == cid) & (df["sku"] == sku))]
    save_csv(df, CART_CSV)
    return {"message": "Item removed"}


@router.delete("/cart")
async def clear_cart(payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(CART_CSV, CART_COLS)
    df = df[df["customer_id"] != cid]
    save_csv(df, CART_CSV)
    return {"message": "Cart cleared"}


# ═══════════════════════════════════════════════════════════════════════════════
# WISHLIST
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/wishlist")
async def get_wishlist(payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(WISHLIST_CSV, WISH_COLS)
    rows = df[df["customer_id"] == cid]
    items = []
    for _, row in rows.iterrows():
        sku = row["sku"]
        p = get_product_info(sku)
        items.append({
            "sku": sku,
            "name": p.get("name", sku),
            "price": p.get("price", 0.0),
            "category": p.get("category", ""),
            "category_color": CATEGORY_COLORS.get(p.get("category", ""), "#6366f1"),
            "in_stock": p.get("current_stock", 0) > 0,
            "added_at": row.get("added_at", ""),
        })
    return items


@router.post("/wishlist/{sku}")
async def toggle_wishlist(sku: str, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(WISHLIST_CSV, WISH_COLS)
    mask = (df["customer_id"] == cid) & (df["sku"] == sku)
    if df[mask].any().any():
        df = df[~mask]
        save_csv(df, WISHLIST_CSV)
        return {"message": "Removed from wishlist", "in_wishlist": False}
    p = get_product_info(sku)
    if not p:
        raise HTTPException(404, "Product not found")
    new_row = pd.DataFrame([{"customer_id": cid, "sku": sku, "added_at": datetime.now(timezone.utc).isoformat()}])
    df = pd.concat([df, new_row], ignore_index=True)
    save_csv(df, WISHLIST_CSV)
    return {"message": "Added to wishlist", "in_wishlist": True}


@router.delete("/wishlist/{sku}")
async def remove_wishlist(sku: str, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(WISHLIST_CSV, WISH_COLS)
    df = df[~((df["customer_id"] == cid) & (df["sku"] == sku))]
    save_csv(df, WISHLIST_CSV)
    return {"message": "Removed from wishlist"}


@router.post("/wishlist/{sku}/move-to-cart")
async def move_wishlist_to_cart(sku: str, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    p = get_product_info(sku)
    if not p:
        raise HTTPException(404, "Product not found")

    # Remove from wishlist
    wdf = load_csv(WISHLIST_CSV, WISH_COLS)
    wdf = wdf[~((wdf["customer_id"] == cid) & (wdf["sku"] == sku))]
    save_csv(wdf, WISHLIST_CSV)

    # Add to cart if not already there
    cdf = load_csv(CART_CSV, CART_COLS)
    mask = (cdf["customer_id"] == cid) & (cdf["sku"] == sku)
    if not cdf[mask].any().any():
        new_row = pd.DataFrame([{"customer_id": cid, "sku": sku, "quantity": "1", "added_at": datetime.now(timezone.utc).isoformat()}])
        cdf = pd.concat([cdf, new_row], ignore_index=True)
        save_csv(cdf, CART_CSV)

    return {"message": "Moved to cart"}


# ═══════════════════════════════════════════════════════════════════════════════
# ORDERS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/orders")
async def get_orders(payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(ORDERS_CSV, ORDER_COLS)
    rows = df[df["customer_id"] == cid].copy()
    if not rows.empty:
        rows = rows.sort_values("order_date", ascending=False)

    result = []
    for _, row in rows.iterrows():
        try:
            items = json.loads(row.get("items_json", "[]"))
        except Exception:
            items = []
        result.append({
            "order_id": row["order_id"],
            "items": items,
            "total_amount": float(row.get("total_amount", 0) or 0),
            "status": row.get("status", "pending"),
            "payment_method": row.get("payment_method", ""),
            "delivery_address": row.get("delivery_address", ""),
            "contact_number": row.get("contact_number", ""),
            "order_date": row.get("order_date", ""),
        })
    return result


class CheckoutBody(BaseModel):
    delivery_address: str
    contact_number: str
    payment_method: str  # cod | upi | card


@router.post("/checkout")
async def checkout(body: CheckoutBody, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    cname = payload.get("name", "")
    cemail = payload.get("email", "")

    cart_df = load_csv(CART_CSV, CART_COLS)
    cart_rows = cart_df[cart_df["customer_id"] == cid]
    if cart_rows.empty:
        raise HTTPException(400, "Cart is empty")

    # Get customer mobile
    cmobile = ""
    if os.path.exists(CUSTOMERS_CSV):
        try:
            cdf = pd.read_csv(CUSTOMERS_CSV, dtype=str).fillna("")
            crow = cdf[cdf["id"] == cid]
            if not crow.empty:
                cmobile = crow.iloc[0].get("mobile", "")
        except Exception:
            pass

    # Build items & validate + deduct stock (atomic under products lock)
    items, subtotal = [], 0.0
    prod_lock = _get_lock(PRODUCTS_CSV)
    with prod_lock:
        if os.path.exists(PRODUCTS_CSV):
            prod_df = pd.read_csv(PRODUCTS_CSV, dtype=str).fillna("")
        else:
            prod_df = pd.DataFrame()

        # First pass: validate all items have sufficient stock
        for _, row in cart_rows.iterrows():
            sku = row["sku"]
            qty = int(row.get("quantity", 1) or 1)
            if not prod_df.empty:
                pmask = prod_df["sku"].astype(str).str.strip() == sku.strip()
                matched = prod_df[pmask]
                if not matched.empty:
                    cur = float(matched.iloc[0].get("current_stock", 0) or 0)
                    if qty > cur:
                        p_name = matched.iloc[0].get("name", sku)
                        raise HTTPException(
                            400,
                            f"Insufficient stock for '{p_name}': requested {qty}, available {int(cur)}"
                        )

        # Second pass: build order items only — stock values are NOT modified here.
        # Stock deduction happens when admin uploads sales data.
        for _, row in cart_rows.iterrows():
            sku = row["sku"]
            qty = int(row.get("quantity", 1) or 1)
            p = get_product_info(sku)
            price = p.get("price", 0.0)
            item_total = round(price * qty, 2)
            subtotal += item_total
            items.append({"sku": sku, "name": p.get("name", sku), "quantity": qty, "unit_price": price, "total": item_total})

    order_id = f"ORD-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    with _invoice_lock:
        invoice_no = _next_invoice_no()

    order_df = load_csv(ORDERS_CSV, ORDER_COLS)
    # Backfill invoice_no for any existing rows that are missing it
    if "invoice_no" not in order_df.columns:
        order_df["invoice_no"] = ""
    missing_mask = order_df["invoice_no"].str.strip() == ""
    if missing_mask.any():
        with _invoice_lock:
            for idx in order_df[missing_mask].index:
                order_df.at[idx, "invoice_no"] = _next_invoice_no()
                # Write after each assignment so the next call sees the new number
                save_csv(order_df, ORDERS_CSV)
                order_df = load_csv(ORDERS_CSV, ORDER_COLS)

    new_order = pd.DataFrame([{
        "order_id": order_id,
        "invoice_no": invoice_no,
        "customer_id": cid,
        "customer_name": cname,
        "customer_email": cemail,
        "customer_mobile": cmobile,
        "items_json": json.dumps(items),
        "delivery_address": body.delivery_address,
        "contact_number": body.contact_number,
        "payment_method": body.payment_method,
        "subtotal": str(round(subtotal, 2)),
        "discount": "0",
        "total_amount": str(round(subtotal, 2)),
        "status": "confirmed",
        "order_date": now,
        "uploaded_to_sales": "False",
    }])
    order_df = pd.concat([order_df, new_order], ignore_index=True)
    save_csv(order_df, ORDERS_CSV)

    # Clear cart
    cart_df = cart_df[cart_df["customer_id"] != cid]
    save_csv(cart_df, CART_CSV)

    add_notification(cid, "order", "Order Confirmed! 🎉",
                     f"Your order {order_id} has been placed successfully. Total: ₹{round(subtotal, 2)}")

    return {"order_id": order_id, "items": items, "total_amount": round(subtotal, 2), "status": "confirmed", "order_date": now}


@router.get("/orders/{order_id}")
async def get_order(order_id: str, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(ORDERS_CSV, ORDER_COLS)
    rows = df[(df["order_id"] == order_id) & (df["customer_id"] == cid)]
    if rows.empty:
        raise HTTPException(404, "Order not found")
    row = rows.iloc[0].to_dict()
    try:
        items = json.loads(row.get("items_json", "[]"))
    except Exception:
        items = []
    return {
        "order_id": row["order_id"],
        "customer_name": row["customer_name"],
        "customer_email": row["customer_email"],
        "customer_mobile": row["customer_mobile"],
        "items": items,
        "delivery_address": row["delivery_address"],
        "contact_number": row["contact_number"],
        "payment_method": row["payment_method"],
        "subtotal": float(row.get("subtotal", 0) or 0),
        "discount": float(row.get("discount", 0) or 0),
        "total_amount": float(row.get("total_amount", 0) or 0),
        "status": row.get("status", "confirmed"),
        "order_date": row.get("order_date", ""),
    }


@router.post("/orders/{order_id}/reorder")
async def reorder(order_id: str, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(ORDERS_CSV, ORDER_COLS)
    rows = df[(df["order_id"] == order_id) & (df["customer_id"] == cid)]
    if rows.empty:
        raise HTTPException(404, "Order not found")

    try:
        items = json.loads(rows.iloc[0].get("items_json", "[]"))
    except Exception:
        raise HTTPException(400, "Could not parse order items")

    cart_df = load_csv(CART_CSV, CART_COLS)
    added = 0
    for item in items:
        sku = item.get("sku", "")
        qty = item.get("quantity", 1)
        p = get_product_info(sku)
        if p and p.get("current_stock", 0) > 0:
            mask = (cart_df["customer_id"] == cid) & (cart_df["sku"] == sku)
            if cart_df[mask].any().any():
                cart_df.loc[mask, "quantity"] = str(qty)
            else:
                new_row = pd.DataFrame([{"customer_id": cid, "sku": sku, "quantity": str(qty), "added_at": datetime.now(timezone.utc).isoformat()}])
                cart_df = pd.concat([cart_df, new_row], ignore_index=True)
            added += 1

    save_csv(cart_df, CART_CSV)
    return {"message": f"{added} item(s) added to cart"}


# ═══════════════════════════════════════════════════════════════════════════════
# NOTIFICATIONS
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/notifications")
async def get_notifications(payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(NOTIF_CSV, NOTIF_COLS)
    rows = df[df["customer_id"] == cid]
    if not rows.empty:
        rows = rows.sort_values("created_at", ascending=False)
    return rows.to_dict("records")


@router.put("/notifications/read-all")
async def mark_all_read(payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(NOTIF_CSV, NOTIF_COLS)
    df.loc[df["customer_id"] == cid, "is_read"] = "True"
    save_csv(df, NOTIF_CSV)
    return {"message": "All marked as read"}


@router.put("/notifications/{notif_id}/read")
async def mark_read(notif_id: str, payload: dict = Depends(verify_customer)):
    cid = payload["sub"]
    df = load_csv(NOTIF_CSV, NOTIF_COLS)
    mask = (df["id"] == notif_id) & (df["customer_id"] == cid)
    df.loc[mask, "is_read"] = "True"
    save_csv(df, NOTIF_CSV)
    return {"message": "Marked as read"}
