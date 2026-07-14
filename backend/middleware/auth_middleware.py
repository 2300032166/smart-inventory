from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
import os

security = HTTPBearer()


def get_secret():
    # Prefer an explicit JWT_SECRET_KEY; fall back to the platform-managed
    # SESSION_SECRET so tokens are still signed with a real secret even if
    # JWT_SECRET_KEY was never set.
    return os.getenv("JWT_SECRET_KEY") or os.getenv("SESSION_SECRET", "fallback-dev-secret-change-in-production")


def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, get_secret(), algorithms=["HS256"])
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def require_role(role: str):
    def role_checker(payload: dict = Depends(verify_token)):
        if payload.get("role") != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Requires role: {role}",
            )
        return payload
    return role_checker


def require_any_role():
    return verify_token


def require_manager_or_admin():
    def checker(payload: dict = Depends(verify_token)):
        if payload.get("role") not in ("manager", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied. Requires manager or admin.",
            )
        return payload
    return checker
