"""Customer product reviews — read and submit."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import pandas as pd
import os
import uuid
import json
import threading
from datetime import datetime, timezone

from middleware.auth_middleware import verify_token

router = APIRouter()
DATA_DIR    = os.path.join(os.path.dirname(__file__), "..", "data")
REVIEWS_CSV = os.path.join(DATA_DIR, "reviews.csv")
ORDERS_CSV  = os.path.join(DATA_DIR, "customer_orders.csv")

REVIEW_COLS = ["review_id", "sku", "customer_id", "customer_name",
               "rating", "comment", "date", "verified"]

_lock = threading.Lock()


def load_reviews() -> pd.DataFrame:
    with _lock:
        if not os.path.exists(REVIEWS_CSV):
            return pd.DataFrame(columns=REVIEW_COLS)
        return pd.read_csv(REVIEWS_CSV, dtype=str).fillna("")


def save_reviews(df: pd.DataFrame):
    with _lock:
        tmp = REVIEWS_CSV + ".tmp"
        df.to_csv(tmp, index=False)
        os.replace(tmp, REVIEWS_CSV)


def _verify_customer(payload: dict = Depends(verify_token)):
    if payload.get("role") != "customer":
        raise HTTPException(403, "Customer access required")
    return payload


def _mask_name(full_name: str) -> str:
    """'Priya Sharma' → 'Priya S.'"""
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1][0]}."
    return parts[0] if parts else "Customer"


class ReviewBody(BaseModel):
    rating: int
    comment: str


@router.get("/{sku}")
async def get_reviews(sku: str):
    df = load_reviews()
    rows = df[df["sku"] == sku].copy()
    if rows.empty:
        return {"reviews": [], "avg_rating": 0.0, "total": 0}
    rows["rating"] = pd.to_numeric(rows["rating"], errors="coerce").fillna(0)
    avg = round(float(rows["rating"].mean()), 1)
    rows = rows.sort_values("date", ascending=False)
    return {
        "reviews": rows[["review_id", "customer_name", "rating", "comment",
                          "date", "verified"]].to_dict("records"),
        "avg_rating": avg,
        "total": len(rows),
    }


@router.post("/{sku}")
async def submit_review(sku: str, body: ReviewBody,
                        payload: dict = Depends(_verify_customer)):
    if not (1 <= body.rating <= 5):
        raise HTTPException(400, "Rating must be between 1 and 5")
    comment = body.comment.strip()
    if len(comment) < 10:
        raise HTTPException(400, "Comment must be at least 10 characters")

    customer_id   = payload["sub"]
    customer_name = _mask_name(payload.get("name", "Customer"))

    # Verified purchase check (before acquiring the write lock — read-only)
    verified = False
    if os.path.exists(ORDERS_CSV):
        try:
            odf = pd.read_csv(ORDERS_CSV, dtype=str).fillna("")
            for _, row in odf[odf["customer_id"] == customer_id].iterrows():
                try:
                    items = json.loads(row.get("items_json", "[]"))
                    if any(i.get("sku") == sku for i in items):
                        verified = True
                        break
                except Exception:
                    pass
        except Exception:
            pass

    # Hold the lock across the full read → duplicate-check → append → write
    # to prevent concurrent submits from both passing the duplicate check.
    with _lock:
        if not os.path.exists(REVIEWS_CSV):
            df = pd.DataFrame(columns=REVIEW_COLS)
        else:
            df = pd.read_csv(REVIEWS_CSV, dtype=str).fillna("")

        if not df.empty and not df[
            (df["sku"] == sku) & (df["customer_id"] == customer_id)
        ].empty:
            raise HTTPException(400, "You have already reviewed this product")

        new_row = pd.DataFrame([{
            "review_id":     str(uuid.uuid4()),
            "sku":           sku,
            "customer_id":   customer_id,
            "customer_name": customer_name,
            "rating":        str(body.rating),
            "comment":       comment,
            "date":          datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "verified":      str(verified),
        }])
        updated = pd.concat([df, new_row], ignore_index=True)
        tmp = REVIEWS_CSV + ".tmp"
        updated.to_csv(tmp, index=False)
        os.replace(tmp, REVIEWS_CSV)

    return {"message": "Review submitted successfully!", "verified": verified}
