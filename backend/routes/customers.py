from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os
import uuid
import threading
import bcrypt as _bcrypt
from datetime import datetime, timedelta, timezone
from jose import jwt

from middleware.auth_middleware import verify_token

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CUSTOMERS_CSV = os.path.join(DATA_DIR, "customers.csv")

CUST_COLS = ["id", "name", "email", "mobile", "password_hash", "address", "is_active", "created_at", "last_login", "customer_number"]

RESET_TOKENS: dict = {}
_customers_lock = threading.Lock()


def get_secret():
    return os.getenv("JWT_SECRET_KEY") or os.getenv("SESSION_SECRET", "fallback-dev-secret-change-in-production")


def _hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt(12)).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def load_customers() -> pd.DataFrame:
    with _customers_lock:
        if not os.path.exists(CUSTOMERS_CSV):
            df = pd.DataFrame(columns=CUST_COLS)
            df.to_csv(CUSTOMERS_CSV, index=False)
            return df
        df = pd.read_csv(CUSTOMERS_CSV, dtype=str).fillna("")
        # Backfill customer_number if column missing (upgrade path)
        if "customer_number" not in df.columns:
            df["customer_number"] = [str(20001 + i) for i in range(len(df))]
            df.to_csv(CUSTOMERS_CSV, index=False)
        return df


def save_customers(df: pd.DataFrame):
    with _customers_lock:
        tmp = CUSTOMERS_CSV + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, CUSTOMERS_CSV)


def create_customer_token(customer_id: str, name: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=7)
    payload = {
        "sub": customer_id,
        "role": "customer",
        "name": name,
        "email": email,
        "exp": expire,
    }
    return jwt.encode(payload, get_secret(), algorithm="HS256")


def verify_customer(payload: dict = Depends(verify_token)):
    if payload.get("role") != "customer":
        raise HTTPException(403, "Customer access required")
    return payload


# ── Pydantic Models ────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    name: str
    email: str
    mobile: str
    password: str
    confirm_password: str
    address: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/signup")
async def signup(body: SignupRequest):
    if body.password != body.confirm_password:
        raise HTTPException(400, "Passwords do not match")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    if not any(c.isupper() for c in body.password):
        raise HTTPException(400, "Password must contain at least one uppercase letter")
    if not any(c.isdigit() for c in body.password):
        raise HTTPException(400, "Password must contain at least one number")

    df = load_customers()

    if not df.empty:
        if body.email.lower().strip() in df["email"].str.lower().str.strip().values:
            raise HTTPException(400, "Email already registered")
        if body.mobile.strip() in df["mobile"].str.strip().values:
            raise HTTPException(400, "Mobile number already registered")

    customer_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Assign next sequential customer_number (5-digit numeric, starts at 20001)
    if not df.empty and "customer_number" in df.columns:
        existing_nums = pd.to_numeric(df["customer_number"], errors="coerce").dropna()
        next_num = int(existing_nums.max()) + 1 if not existing_nums.empty else 20001
    else:
        next_num = 20001

    new_row = pd.DataFrame([{
        "id": customer_id,
        "name": body.name.strip(),
        "email": body.email.lower().strip(),
        "mobile": body.mobile.strip(),
        "password_hash": _hash_password(body.password),
        "address": body.address.strip(),
        "is_active": "True",
        "created_at": now,
        "last_login": now,
        "customer_number": str(next_num),
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    save_customers(df)

    token = create_customer_token(customer_id, body.name.strip(), body.email.lower().strip())
    return {"token": token, "name": body.name.strip(), "customer_id": customer_id, "email": body.email.lower().strip()}


@router.post("/login")
async def login(body: LoginRequest):
    df = load_customers()
    if df.empty:
        raise HTTPException(401, "Invalid email or password")

    mask = df["email"].str.lower().str.strip() == body.email.lower().strip()
    rows = df[mask]
    if rows.empty:
        raise HTTPException(401, "Invalid email or password")

    customer = rows.iloc[0].to_dict()
    if customer.get("is_active", "").lower() != "true":
        raise HTTPException(401, "Account is disabled")
    if not _verify_password(body.password, customer["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    df.loc[mask, "last_login"] = datetime.now(timezone.utc).isoformat()
    save_customers(df)

    token = create_customer_token(customer["id"], customer["name"], customer["email"])
    return {"token": token, "name": customer["name"], "customer_id": customer["id"], "email": customer["email"]}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    df = load_customers()
    if not df.empty:
        mask = df["email"].str.lower().str.strip() == body.email.lower().strip()
        rows = df[mask]
        if not rows.empty:
            customer = rows.iloc[0].to_dict()
            reset_token = str(uuid.uuid4())
            RESET_TOKENS[reset_token] = {
                "customer_id": customer["id"],
                "expires": datetime.now(timezone.utc) + timedelta(hours=1),
            }
            # Only expose token in local sandbox mode (SANDBOX_MODE=true env var)
            # Never returns token in production — deliver via email/SMS instead
            if os.getenv("SANDBOX_MODE", "").lower() == "true":
                return {"message": "If that email is registered, a reset link has been sent.", "debug_token": reset_token}
    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    token_data = RESET_TOKENS.get(body.token)
    if not token_data:
        raise HTTPException(400, "Invalid or expired reset token")
    if datetime.now(timezone.utc) > token_data["expires"]:
        del RESET_TOKENS[body.token]
        raise HTTPException(400, "Reset token has expired")
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")

    df = load_customers()
    mask = df["id"] == token_data["customer_id"]
    df.loc[mask, "password_hash"] = _hash_password(body.new_password)
    save_customers(df)
    del RESET_TOKENS[body.token]
    return {"message": "Password reset successfully"}


@router.get("/me")
async def get_profile(payload: dict = Depends(verify_customer)):
    df = load_customers()
    rows = df[df["id"] == payload["sub"]]
    if rows.empty:
        raise HTTPException(404, "Customer not found")
    c = rows.iloc[0].to_dict()

    # Order stats
    orders_csv = os.path.join(DATA_DIR, "customer_orders.csv")
    total_orders = 0
    total_spent = 0.0
    if os.path.exists(orders_csv):
        try:
            odf = pd.read_csv(orders_csv, dtype=str).fillna("")
            customer_orders = odf[odf["customer_id"] == payload["sub"]]
            total_orders = len(customer_orders)
            if not customer_orders.empty:
                total_spent = pd.to_numeric(customer_orders["total_amount"], errors="coerce").sum()
        except Exception:
            pass

    return {
        "id": c["id"],
        "name": c["name"],
        "email": c["email"],
        "mobile": c["mobile"],
        "address": c["address"],
        "created_at": c["created_at"],
        "last_login": c["last_login"],
        "total_orders": total_orders,
        "total_spent": round(float(total_spent), 2),
    }


@router.put("/me")
async def update_profile(body: UpdateProfileRequest, payload: dict = Depends(verify_customer)):
    df = load_customers()
    mask = df["id"] == payload["sub"]
    if not df[mask].any().any():
        raise HTTPException(404, "Customer not found")

    if body.name:
        df.loc[mask, "name"] = body.name.strip()
    if body.mobile:
        other_mask = (df["mobile"].str.strip() == body.mobile.strip()) & (~mask)
        if df[other_mask].any().any():
            raise HTTPException(400, "Mobile number already in use")
        df.loc[mask, "mobile"] = body.mobile.strip()
    if body.address is not None:
        df.loc[mask, "address"] = body.address.strip()

    save_customers(df)
    return {"message": "Profile updated successfully"}


@router.put("/me/password")
async def change_password(body: ChangePasswordRequest, payload: dict = Depends(verify_customer)):
    df = load_customers()
    mask = df["id"] == payload["sub"]
    rows = df[mask]
    if rows.empty:
        raise HTTPException(404, "Customer not found")

    c = rows.iloc[0].to_dict()
    if not _verify_password(body.current_password, c["password_hash"]):
        raise HTTPException(400, "Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")

    df.loc[mask, "password_hash"] = _hash_password(body.new_password)
    save_customers(df)
    return {"message": "Password changed successfully"}
