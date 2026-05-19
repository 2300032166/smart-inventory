from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel
from jose import jwt
import bcrypt as _bcrypt
from datetime import datetime, timedelta, timezone
import json, os, uuid

from middleware.auth_middleware import verify_token

router = APIRouter()


def _hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt(12)).decode()


def _verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_users():
    with open(os.path.join(DATA_DIR, "users.json")) as f:
        return json.load(f)


def save_users(users):
    with open(os.path.join(DATA_DIR, "users.json"), "w") as f:
        json.dump(users, f, indent=2)


def get_secret():
    return os.getenv("JWT_SECRET_KEY", "fallback-dev-secret-change-in-production")


def create_token(user: dict) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=8)
    payload = {
        "sub": user["id"],
        "role": user["role"],
        "name": user["name"],
        "email": user["email"],
        "exp": expire,
    }
    return jwt.encode(payload, get_secret(), algorithm="HS256")


def log_audit(user_id, user_name, role, action_type, description, ip="unknown"):
    path = os.path.join(DATA_DIR, "audit_log.json")
    try:
        with open(path) as f:
            logs = json.load(f)
    except Exception:
        logs = []
    logs.append({
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "user_name": user_name,
        "role": role,
        "action_type": action_type,
        "description": description,
        "ip_address": ip,
    })
    with open(path, "w") as f:
        json.dump(logs, f, indent=2)


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


RESET_TOKENS: dict = {}


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    users = load_users()
    user = next((u for u in users if u["email"] == body.email and u["is_active"]), None)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not _verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user["last_login"] = datetime.now(timezone.utc).isoformat()
    save_users(users)

    ip = request.client.host if request.client else "unknown"
    log_audit(user["id"], user["name"], user["role"], "LOGIN", f"User logged in: {user['email']}", ip)

    token = create_token(user)
    return {"token": token, "role": user["role"], "name": user["name"], "user_id": user["id"]}


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    users = load_users()
    user = next((u for u in users if u["email"] == body.email and u["is_active"]), None)
    if not user:
        return {"message": "If that email is registered, a reset link has been sent."}

    reset_token = str(uuid.uuid4())
    RESET_TOKENS[reset_token] = {"user_id": user["id"], "expires": datetime.now(timezone.utc) + timedelta(hours=1)}
    print(f"[SANDBOX] Password reset token for {body.email}: {reset_token}")
    return {"message": "If that email is registered, a reset link has been sent.", "debug_token": reset_token}


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    token_data = RESET_TOKENS.get(body.token)
    if not token_data:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    if datetime.now(timezone.utc) > token_data["expires"]:
        del RESET_TOKENS[body.token]
        raise HTTPException(status_code=400, detail="Reset token has expired")

    users = load_users()
    user = next((u for u in users if u["id"] == token_data["user_id"]), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user["password_hash"] = _hash_password(body.new_password)
    save_users(users)
    del RESET_TOKENS[body.token]
    return {"message": "Password reset successfully"}


@router.get("/me")
async def get_me(payload: dict = Depends(verify_token)):
    users = load_users()
    user = next((u for u in users if u["id"] == payload["sub"]), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": user["id"], "name": user["name"], "email": user["email"], "role": user["role"]}
