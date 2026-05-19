from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Query
from pydantic import BaseModel
from typing import Optional
import json, os, uuid, io
from datetime import datetime, timezone
import pandas as pd
import bcrypt as _bcrypt

from middleware.auth_middleware import require_role
from logic.ai_client import test_connection, load_ai_config

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
        df.to_csv(os.path.join(DATA_DIR, "sales.csv"), index=False)
        status = "success"
        row_count = len(df)
        history = load_upload_history()
        history.insert(0, {
            "id": str(uuid.uuid4()),
            "filename": file.filename,
            "date": datetime.now(timezone.utc).isoformat(),
            "rows": row_count,
            "status": "success",
        })
        save_upload_history(history)
        log_audit(payload, "DATA_UPLOAD", f"Uploaded sales CSV: {file.filename}, {row_count} rows")
        return {"status": status, "rows": row_count, "preview": preview, "column_check": column_check, "missing_columns": list(missing)}

    return {"status": "preview", "preview": preview, "column_check": column_check, "missing_columns": list(missing)}


@router.get("/upload-history")
def get_upload_history(payload: dict = Depends(require_role("admin"))):
    return load_upload_history()


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
    if safe.get("gemini_api_key"):
        key = safe["gemini_api_key"]
        safe["gemini_api_key"] = key[:8] + "..." + key[-4:] if len(key) > 12 else "****"
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
    if body.get("gemini_api_key") and not body["gemini_api_key"].endswith("..."):
        cfg["gemini_api_key"] = body["gemini_api_key"]
    provider = body.get("ai_provider", cfg.get("ai_provider", "gemini"))
    result = await test_connection(provider, cfg)
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
