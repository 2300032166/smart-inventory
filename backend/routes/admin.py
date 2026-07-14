from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Query
from pydantic import BaseModel
from typing import Optional, List
import json, os, uuid, io
from datetime import datetime, timezone
import pandas as pd
import bcrypt as _bcrypt

from middleware.auth_middleware import require_role, require_manager_or_admin
from logic.ai_client import test_connection, load_ai_config
from logic.chatbot_data import data_manager
from routes.inventory import deduct_stock_for_sales, sync_batches_to_stock, save_products
import logging

logger = logging.getLogger(__name__)

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def _hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt(12)).decode()


def load_users():
    with open(os.path.join(DATA_DIR, "users.json")) as f:
        return json.load(f)


def save_users(users):
    with open(os.path.join(DATA_DIR, "users.json"), "w") as f:
        json.dump(users, f, indent=2)


def load_audit():
    try:
        with open(os.path.join(DATA_DIR, "audit_log.json")) as f:
            return json.load(f)
    except Exception:
        return []


def save_audit(data):
    with open(os.path.join(DATA_DIR, "audit_log.json"), "w") as f:
        json.dump(data, f, indent=2)


def log_audit(payload, action_type, description, ip="unknown"):
    audit = load_audit()
    audit.append({
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": payload.get("sub"),
        "user_name": payload.get("name"),
        "role": payload.get("role"),
        "action_type": action_type,
        "description": description,
        "ip_address": ip,
    })
    save_audit(audit)


UPLOAD_HISTORY_FILE = os.path.join(DATA_DIR, "upload_history.json")


def load_upload_history():
    try:
        with open(UPLOAD_HISTORY_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_upload_history(data):
    with open(UPLOAD_HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)


REQUIRED_COLUMNS = {"InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID"}


@router.post("/upload-sales-csv")
async def upload_sales_csv(file: UploadFile = File(...), payload: dict = Depends(require_role("admin"))):
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files accepted")

    content = await file.read()
    try:
        df = pd.read_csv(io.StringIO(content.decode("utf-8")))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {e}")

    present = set(df.columns)
    missing = REQUIRED_COLUMNS - present
    column_check = {col: (col in present) for col in REQUIRED_COLUMNS}
    preview = df.head(10).fillna("").to_dict(orient="records")

    if not missing:
        sales_path = os.path.join(DATA_DIR, "sales.csv")
        rollback_backup_path = os.path.join(DATA_DIR, "sales_upload_rollback.csv")

        # Append-mode: merge the uploaded rows into existing sales history
        # instead of overwriting it, so a daily "just today's sales" upload
        # accumulates history rather than wiping out prior data. Duplicate
        # rows (e.g. re-uploading the same day/file) are dropped using a
        # composite key of all line-item fields, since a single InvoiceNo
        # legitimately repeats across multiple product line items on the
        # same order — deduping on InvoiceNo alone would delete real rows.
        added_count = len(df)
        duplicate_count = 0
        total_count = len(df)

        dedup_cols = [c for c in ["InvoiceNo", "StockCode", "Description", "Quantity", "InvoiceDate", "UnitPrice", "CustomerID"] if c in df.columns]

        # Snapshot the pre-upload state so the most recent upload can be
        # undone from the Upload History page. Only one rollback point is
        # kept (the latest upload), matching the "undo last upload" UX.
        if os.path.exists(sales_path):
            with open(sales_path, "rb") as src, open(rollback_backup_path, "wb") as dst:
                dst.write(src.read())

            existing = pd.read_csv(sales_path)
            existing_len = len(existing)
            combined = pd.concat([existing, df], ignore_index=True)
            if dedup_cols:
                before = len(combined)
                combined = combined.drop_duplicates(subset=dedup_cols, keep="first")
                duplicate_count = before - len(combined)
            added_count = len(df) - duplicate_count
            total_count = len(combined)
            combined.to_csv(sales_path, index=False)
            # Rows that were actually appended (non-duplicates from uploaded file)
            newly_added_rows = combined.iloc[existing_len:].to_dict(orient="records")
        else:
            df.to_csv(sales_path, index=False)
            newly_added_rows = df.to_dict(orient="records")

        # Deduct stock for newly added sales rows (FEFO per batch)
        deduct_stock_for_sales(newly_added_rows)

        status = "success"
        history = load_upload_history()
        upload_id = str(uuid.uuid4())
        history.insert(0, {
            "id": upload_id,
            "filename": file.filename,
            "date": datetime.now(timezone.utc).isoformat(),
            "rows": added_count,
            "duplicate_rows": duplicate_count,
            "total_rows": total_count,
            "status": "success",
            "can_rollback": os.path.exists(rollback_backup_path),
        })
        save_upload_history(history)
        log_audit(
            payload,
            "DATA_UPLOAD",
            f"Uploaded sales CSV: {file.filename}, {added_count} new rows added"
            + (f" ({duplicate_count} duplicates skipped)" if duplicate_count else "")
            + f", total sales rows now {total_count}",
        )
        return {
            "status": status,
            "rows": added_count,
            "duplicate_rows": duplicate_count,
            "total_rows": total_count,
            "preview": preview,
            "column_check": column_check,
            "missing_columns": list(missing),
        }

    return {"status": "preview", "preview": preview, "column_check": column_check, "missing_columns": list(missing)}


@router.get("/system-stats")
def get_system_stats(payload: dict = Depends(require_role("admin"))):
    """Compute real-time stats from the filesystem for high accuracy."""
    products_path = os.path.join(DATA_DIR, "products.csv")
    sales_path = os.path.join(DATA_DIR, "sales.csv")
    
    product_count = 0
    last_upload = "Never"
    
    if os.path.exists(products_path):
        try:
            df_p = pd.read_csv(products_path)
            product_count = len(df_p)
        except: pass
        
    if os.path.exists(sales_path):
        mtime = os.path.getmtime(sales_path)
        last_upload = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        
    cfg = load_cfg()
    model_name = "Groq: Llama 3"
    if cfg.get("ai_provider") == "gemini":
        model_name = cfg.get("gemini_model", "Gemini 1.5 Flash")
    elif cfg.get("ai_provider") == "ollama":
        model_name = f"Ollama: {cfg.get('ollama_model', 'Mistral')}"
    elif cfg.get("ai_provider") == "groq":
        model_name = f"Groq: {cfg.get('groq_model', 'Llama 3')}"
        
    return {
        "product_count": product_count,
        "last_upload": last_upload,
        "ai_model": model_name
    }


@router.get("/upload-history")
def get_upload_history(payload: dict = Depends(require_role("admin"))):
    return load_upload_history()


@router.post("/upload-history/{upload_id}/rollback")
def rollback_upload(upload_id: str, request: Request, payload: dict = Depends(require_role("admin"))):
    """Undo the most recent sales CSV upload by restoring the pre-upload snapshot.
    Only the latest upload can be rolled back, since a rollback point is
    only kept for one upload at a time and rolling back an older one would
    also discard any uploads made after it."""
    history = load_upload_history()
    if not history:
        raise HTTPException(status_code=404, detail="No uploads to roll back")

    latest = history[0]
    if latest["id"] != upload_id:
        raise HTTPException(status_code=400, detail="Only the most recent upload can be rolled back")
    if not latest.get("can_rollback"):
        raise HTTPException(status_code=400, detail="This upload cannot be rolled back")

    sales_path = os.path.join(DATA_DIR, "sales.csv")
    rollback_backup_path = os.path.join(DATA_DIR, "sales_upload_rollback.csv")
    if not os.path.exists(rollback_backup_path):
        raise HTTPException(status_code=400, detail="Rollback snapshot not found")

    with open(rollback_backup_path, "rb") as src, open(sales_path, "wb") as dst:
        dst.write(src.read())
    os.remove(rollback_backup_path)

    history.pop(0)
    save_upload_history(history)

    ip = request.client.host if request.client else "unknown"
    log_audit(
        payload,
        "DATA_UPLOAD_ROLLBACK",
        f"Rolled back sales CSV upload: {latest['filename']} ({latest.get('rows', 0)} rows added, "
        f"restored total to {latest.get('total_rows', 'previous')} minus this upload)",
        ip,
    )
    return {"message": "Upload rolled back", "filename": latest["filename"]}


@router.get("/users")
def get_users(payload: dict = Depends(require_role("admin"))):
    users = load_users()
    return [{k: v for k, v in u.items() if k != "password_hash"} for u in users]


class UserCreate(BaseModel):
    name: str
    email: str
    role: str
    password: str


class UserUpdate(BaseModel):
    name: str
    email: str
    role: str


@router.post("/users")
def create_user(body: UserCreate, request: Request, payload: dict = Depends(require_role("admin"))):
    users = load_users()
    if any(u["email"] == body.email for u in users):
        raise HTTPException(status_code=409, detail="Email already in use")
    if body.role not in ("admin", "manager"):
        raise HTTPException(status_code=400, detail="Role must be admin or manager")
    new_user = {
        "id": f"USR{str(uuid.uuid4())[:6].upper()}",
        "name": body.name,
        "email": body.email,
        "password_hash": _hash_password(body.password),
        "role": body.role,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_login": None,
    }
    users.append(new_user)
    save_users(users)
    ip = request.client.host if request.client else "unknown"
    log_audit(payload, "USER_CREATE", f"Created user: {body.email} (role: {body.role})", ip)
    return {k: v for k, v in new_user.items() if k != "password_hash"}


@router.put("/users/{user_id}")
def update_user(user_id: str, body: UserUpdate, request: Request, payload: dict = Depends(require_role("admin"))):
    users = load_users()
    idx = next((i for i, u in enumerate(users) if u["id"] == user_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="User not found")
    if body.role not in ("admin", "manager"):
        raise HTTPException(status_code=400, detail="Role must be admin or manager")
    users[idx]["name"] = body.name
    users[idx]["email"] = body.email
    users[idx]["role"] = body.role
    save_users(users)
    ip = request.client.host if request.client else "unknown"
    log_audit(payload, "USER_UPDATE", f"Updated user: {body.email}", ip)
    return {k: v for k, v in users[idx].items() if k != "password_hash"}


@router.post("/users/{user_id}/deactivate")
def deactivate_user(user_id: str, request: Request, payload: dict = Depends(require_role("admin"))):
    users = load_users()
    idx = next((i for i, u in enumerate(users) if u["id"] == user_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="User not found")

    admins = [u for u in users if u["role"] == "admin" and u["is_active"]]
    if users[idx]["role"] == "admin" and len(admins) <= 1:
        raise HTTPException(status_code=400, detail="Cannot deactivate the last admin user")

    users[idx]["is_active"] = not users[idx]["is_active"]
    save_users(users)
    action = "deactivated" if not users[idx]["is_active"] else "activated"
    ip = request.client.host if request.client else "unknown"
    log_audit(payload, "USER_STATUS_CHANGE", f"User {users[idx]['email']} {action}", ip)
    return {"message": f"User {action}", "is_active": users[idx]["is_active"]}


@router.post("/users/{user_id}/reset-password")
def reset_user_password(user_id: str, request: Request, payload: dict = Depends(require_role("admin"))):
    users = load_users()
    idx = next((i for i, u in enumerate(users) if u["id"] == user_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="User not found")

    temp_password = f"Temp@{str(uuid.uuid4())[:8]}"
    users[idx]["password_hash"] = _hash_password(temp_password)
    save_users(users)
    ip = request.client.host if request.client else "unknown"
    log_audit(payload, "USER_PASSWORD_RESET", f"Password reset for: {users[idx]['email']}", ip)
    return {"message": "Password reset", "temp_password": temp_password}


AI_CONFIG_FILE = os.path.join(DATA_DIR, "ai_config.json")


def load_cfg():
    try:
        with open(AI_CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(data):
    with open(AI_CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=2)


@router.get("/ai-config")
def get_ai_config(payload: dict = Depends(require_role("admin"))):
    cfg = load_cfg()
    safe = dict(cfg)
    # Mask Groq key
    if safe.get("groq_api_key"):
        key = safe["groq_api_key"]
        safe["groq_api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "****"
    return safe


@router.put("/ai-config")
async def update_ai_config(body: dict, request: Request, payload: dict = Depends(require_role("admin"))):
    cfg = load_cfg()
    cfg.update(body)
    save_cfg(cfg)
    ip = request.client.host if request.client else "unknown"
    log_audit(payload, "AI_CONFIG_UPDATE", "Updated AI configuration", ip)
    return {"message": "AI configuration updated"}


@router.post("/ai-config/test")
async def test_ai_connection(body: dict, payload: dict = Depends(require_role("admin"))):
    cfg = load_cfg()
    # If a new Groq key is provided (not masked), update the config for the test
    if body.get("groq_api_key") and not body["groq_api_key"].endswith("..."):
        cfg["groq_api_key"] = body["groq_api_key"]
    
    result = await test_connection("groq", cfg)
    return result


@router.get("/audit-log")
def get_audit_log(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    user_id: Optional[str] = Query(None),
    action_type: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    payload: dict = Depends(require_role("admin")),
):
    audit = load_audit()
    audit.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    if user_id:
        audit = [a for a in audit if a.get("user_id") == user_id]
    if action_type:
        audit = [a for a in audit if a.get("action_type") == action_type]
    if date_from:
        audit = [a for a in audit if a.get("timestamp", "") >= date_from]
    if date_to:
        audit = [a for a in audit if a.get("timestamp", "")[:10] <= date_to]


    total = len(audit)
    start = (page - 1) * limit
    items = audit[start: start + limit]
    return {"total": total, "page": page, "limit": limit, "items": items}


# ── Admin Insights ────────────────────────────────────────────────────────────

@router.get("/insights")
def get_insights(payload: dict = Depends(require_role("admin"))):
    """High-level KPIs and sample lists for the admin Business Insights page."""
    try:
        if not getattr(data_manager, "_initialized", False):
            data_manager.initialize()
        caches = data_manager.caches
        products = data_manager.products

        total_value = sum(
            float(p.get("current_stock", 0) or 0) * float(p.get("unit_price", 0) or 0)
            for p in products
        )
        low_stock = caches.get("low_stock", [])
        stockouts = caches.get("stockout_products", [])
        dead = caches.get("dead_stock", [])
        overstock = caches.get("overstock", [])
        active = caches.get("active_discounts", [])
        pending = caches.get("pending_discount_recommendations", [])
        upcoming = caches.get("upcoming_stock", [])
        supplier_perf = caches.get("supplier_performance", [])
        best = caches.get("best_supplier_overall", {})
        expiry_summary = caches.get("expiry_summary", {})
        expiring_30 = caches.get("expiring_30_days", [])
        expiring_7 = caches.get("expiring_7_days", [])
        expired = caches.get("expiry_expired_batches", [])

        active_value = round(
            sum(
                float(a.get("discounted_price", 0) or 0) * float(a.get("current_stock", 0) or 0)
                for a in active
            ), 2
        )

        return {
            "inventory": {
                "total_products": len(products),
                "total_value": round(total_value, 2),
                "low_stock_count": len(low_stock),
                "stockout_count": len(stockouts),
                "dead_stock_count": len(dead),
                "overstock_count": len(overstock),
                "low_stock_sample": low_stock[:10],
                "stockout_sample": stockouts[:10],
            },
            "discounts": {
                "active_count": len(active),
                "pending_count": len(pending),
                "active_value": active_value,
                "active_sample": active[:10],
                "pending_sample": pending[:10],
            },
            "expiry": {
                "summary": expiry_summary,
                "expiring_7_count": len(expiring_7),
                "expiring_30_count": len(expiring_30),
                "expired_count": len(expired),
                "expiring_30_sample": expiring_30[:10],
                "expired_sample": expired[:10],
            },
            "upcoming_stock": {
                "po_count": len(upcoming),
                "total_units": int(caches.get("upcoming_stock_total", 0)),
                "sample": upcoming[:10],
            },
            "suppliers": {
                "total_suppliers": len(supplier_perf),
                "best_overall": best,
                "top_suppliers": supplier_perf[:10],
            },
        }
    except Exception as e:
        logger.error(f"Failed to gather insights: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to gather insights: {e}")


# ── Bulk Operations ───────────────────────────────────────────────────────────

class BulkStockItem(BaseModel):
    sku: str
    current_stock: float

class BulkStockUpdate(BaseModel):
    items: List[BulkStockItem]
    reason: str = ""

class BulkDiscountItem(BaseModel):
    sku: str
    batch_no: str = ""
    discount_percent: int
    final_price: Optional[float] = None
    scheduled_start: Optional[str] = None
    scheduled_end: Optional[str] = None
    reason: str = ""

class BulkDiscountApply(BaseModel):
    items: List[BulkDiscountItem]
    mode: str = "active"  # "active" or "recommendation"
    reason: str = ""

class BulkDisposeItem(BaseModel):
    batch_no: str
    reason: str = ""

class BulkBatchDispose(BaseModel):
    items: List[BulkDisposeItem]


@router.post("/bulk-update-stock")
def bulk_update_stock(
    body: BulkStockUpdate,
    payload: dict = Depends(require_manager_or_admin()),
):
    products_path = os.path.join(DATA_DIR, "products.csv")
    products = pd.read_csv(products_path).fillna("").to_dict(orient="records")
    sku_map = {str(p.get("sku", "")).strip().upper(): i for i, p in enumerate(products)}

    updated = []
    not_found = []
    for item in body.items:
        sku = str(item.sku).strip().upper()
        if sku not in sku_map:
            not_found.append(item.sku)
            continue
        new_stock = float(item.current_stock)
        sync_batches_to_stock(sku, new_stock)
        idx = sku_map[sku]
        products[idx]["current_stock"] = new_stock
        updated.append({"sku": sku, "current_stock": new_stock})

    save_products(products)
    log_audit(
        payload,
        "bulk_stock_update",
        f"Bulk updated stock for {len(updated)} products. Reason: {body.reason}",
    )
    return {"updated": updated, "not_found": not_found, "count": len(updated)}


@router.post("/bulk-apply-discounts")
def bulk_apply_discounts(
    body: BulkDiscountApply,
    payload: dict = Depends(require_manager_or_admin()),
):
    from routes.discounts import load_store, save_store, append_audit, now_str

    store = load_store()
    products_path = os.path.join(DATA_DIR, "products.csv")
    products = pd.read_csv(products_path).fillna("").to_dict(orient="records")
    product_lookup = {str(p.get("sku", "")).strip().upper(): p for p in products}
    batches_path = os.path.join(DATA_DIR, "inventory_batches.csv")
    batches = pd.read_csv(batches_path).fillna("").to_dict(orient="records")
    batch_lookup = {str(b.get("batch_no", "")).strip().upper(): b for b in batches}

    user = payload.get("sub", "admin")
    created = []
    for item in body.items:
        sku = str(item.sku).strip().upper()
        batch_no = str(item.batch_no or "").strip().upper()
        prod = product_lookup.get(sku)
        if not prod:
            continue

        current_price = float(prod.get("unit_price", 0) or 0)
        product_name = prod.get("name", sku)
        disc_pct = int(item.discount_percent)
        final_price = (
            item.final_price
            if item.final_price is not None
            else round(current_price * (1 - disc_pct / 100), 2)
        )
        batch = batch_lookup.get(batch_no)
        stock = float(batch.get("quantity", 0)) if batch else float(prod.get("current_stock", 0) or 0)

        # Find matching pending recommendation by (sku, batch_no) and mark it approved
        rec_id = None
        if batch_no:
            for r in store.get("recommendations", []):
                if (r.get("status") == "pending"
                    and str(r.get("sku", "")).strip().upper() == sku
                    and str(r.get("batch_no", "")).strip().upper() == batch_no):
                    rec_id = r["id"]
                    break
        else:
            for r in store.get("recommendations", []):
                if (r.get("status") == "pending"
                    and str(r.get("sku", "")).strip().upper() == sku):
                    rec_id = r["id"]
                    break

        # Mark original recommendation as approved if found
        if rec_id:
            for r in store["recommendations"]:
                if r["id"] == rec_id:
                    r["status"] = "approved"
                    r["approved_by"] = user
                    r["updated_at"] = now_str()
                    break

        if body.mode == "active":
            active = {
                "id": str(uuid.uuid4()),
                "recommendation_id": rec_id,
                "sku": sku,
                "batch_no": batch_no or None,
                "product_name": product_name,
                "discount_percent": disc_pct,
                "original_price": current_price,
                "discounted_price": final_price,
                "reason": item.reason or body.reason or "Manual bulk discount",
                "type": "Manual",
                "current_stock": stock,
                "approved_at": now_str(),
                "approved_by": user,
                "scheduled_start": item.scheduled_start or None,
                "scheduled_end": item.scheduled_end or None,
                "notes": item.reason or body.reason or "",
                "status": "active",
            }
            store.setdefault("active_discounts", []).append(active)
            store.setdefault("history", []).append({**active, "_event": "approved"})
        else:
            rec = {
                "id": str(uuid.uuid4()),
                "_key": f"Manual|{sku}|{batch_no or 'N/A'}",
                "type": "Manual",
                "sku": sku,
                "batch_no": batch_no or None,
                "product_name": product_name,
                "current_stock": stock,
                "current_price": current_price,
                "suggested_discount": disc_pct,
                "final_price": final_price,
                "reason": item.reason or body.reason or "Manual bulk discount",
                "shelf_life_remaining": None,
                "status": "pending",
                "notes": item.reason or body.reason or "",
                "scheduled_start": item.scheduled_start or None,
                "scheduled_end": item.scheduled_end or None,
                "created_at": now_str(),
                "updated_at": now_str(),
                "approved_by": None,
            }
            store.setdefault("recommendations", []).append(rec)

        created.append({"sku": sku, "batch_no": batch_no or None, "discount_percent": disc_pct})

    save_store(store)
    log_audit(
        payload,
        "bulk_discount_apply",
        f"Bulk applied {len(created)} discounts (mode={body.mode}). Reason: {body.reason}",
    )
    append_audit(
        "BULK_DISCOUNT_APPLY",
        f"Created {len(created)} discount records in mode '{body.mode}'. Reason: {body.reason}",
        user,
    )
    return {"created": created, "count": len(created)}


@router.post("/bulk-dispose-batches")
def bulk_dispose_batches(
    body: BulkBatchDispose,
    payload: dict = Depends(require_manager_or_admin()),
):
    batches_path = os.path.join(DATA_DIR, "inventory_batches.csv")
    df = pd.read_csv(batches_path).fillna("")
    batch_map = {str(b).strip().upper(): i for i, b in enumerate(df["batch_no"])}

    user = payload.get("sub", "admin")
    now = datetime.now(timezone.utc).isoformat()
    disposed = []
    not_found = []
    for item in body.items:
        bn = str(item.batch_no).strip().upper()
        if bn not in batch_map:
            not_found.append(item.batch_no)
            continue
        idx = batch_map[bn]
        df.at[idx, "status"] = "disposed"
        df.at[idx, "disposed_at"] = now
        df.at[idx, "disposed_by"] = user
        if "disposal_reason" in df.columns:
            df.at[idx, "disposal_reason"] = item.reason
        disposed.append(item.batch_no)

    df.to_csv(batches_path, index=False)
    reasons = [i.reason for i in body.items if i.reason]
    reason_str = ", ".join(reasons) if reasons else "N/A"
    log_audit(
        payload,
        "bulk_dispose_batches",
        f"Bulk disposed {len(disposed)} batches. Reasons: {reason_str}",
    )
    return {"disposed": disposed, "not_found": not_found, "count": len(disposed)}
