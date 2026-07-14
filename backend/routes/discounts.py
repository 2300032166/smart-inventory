from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import pandas as pd
import os
import json
import uuid
from datetime import datetime
from typing import Optional

from middleware.auth_middleware import verify_token

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DISCOUNTS_JSON = os.path.join(DATA_DIR, "discounts.json")
AUDIT_JSON     = os.path.join(DATA_DIR, "audit_log.json")

# ── Pydantic bodies ────────────────────────────────────────────────────────────

class ApproveBody(BaseModel):
    discount_percent: Optional[int] = None
    notes: Optional[str] = ""
    scheduled_end: Optional[str] = None   # ISO date string YYYY-MM-DD

class RejectBody(BaseModel):
    notes: Optional[str] = ""

class RevokeBody(BaseModel):
    notes: Optional[str] = ""

# ── Storage helpers ────────────────────────────────────────────────────────────

def load_store() -> dict:
    if not os.path.exists(DISCOUNTS_JSON):
        return {"recommendations": [], "active_discounts": [], "history": []}
    try:
        with open(DISCOUNTS_JSON, "r") as f:
            return json.load(f)
    except Exception:
        return {"recommendations": [], "active_discounts": [], "history": []}

def save_store(store: dict):
    with open(DISCOUNTS_JSON, "w") as f:
        json.dump(store, f, indent=2, default=str)

def now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")

def append_audit(action: str, detail: str, user: str):
    try:
        log = []
        if os.path.exists(AUDIT_JSON):
            with open(AUDIT_JSON, "r") as f:
                log = json.load(f)
        log.append({
            "timestamp": now_str(),
            "action": action,
            "detail": detail,
            "user": user,
            "module": "Discounts"
        })
        with open(AUDIT_JSON, "w") as f:
            json.dump(log[-2000:], f, indent=2, default=str)
    except Exception:
        pass

# ── Recommendation generation ──────────────────────────────────────────────────

def expiry_discount_pct(days_left: int) -> int:
    if days_left <= 2:   return 60
    if days_left <= 6:   return 40
    if days_left <= 14:  return 20
    if days_left <= 30:  return 10
    return 0

def generate_fresh_recommendations() -> list:
    """Pull from expiry batches + dead stock analysis and produce raw recommendation dicts."""
    recs = []
    today = datetime.now()

    batches_csv  = os.path.join(DATA_DIR, "inventory_batches.csv")
    products_csv = os.path.join(DATA_DIR, "products.csv")

    price_map: dict = {}
    name_map:  dict = {}
    if os.path.exists(products_csv):
        pdf = pd.read_csv(products_csv).fillna("")
        price_map = dict(zip(pdf["sku"].str.strip().str.upper(),
                             pd.to_numeric(pdf["unit_price"], errors="coerce").fillna(0)))
        name_map  = dict(zip(pdf["sku"].str.strip().str.upper(), pdf["name"]))

    # ── 1. Expiry-based ──────────────────────────────────────────────────────
    if os.path.exists(batches_csv):
        bdf = pd.read_csv(batches_csv).fillna("")
        bdf = bdf[bdf["status"] == "active"]
        bdf["quantity"] = pd.to_numeric(bdf["quantity"], errors="coerce").fillna(0)
        bdf = bdf[bdf["quantity"] > 0]

        for _, row in bdf.iterrows():
            sku = str(row["sku"]).strip().upper()
            try:
                expiry_dt = datetime.strptime(str(row["expiry_date"]), "%Y-%m-%d")
                days_left = (expiry_dt.date() - today.date()).days
            except Exception:
                continue

            if days_left < 1:
                continue  # already expired/today — skip, let auto-deactivation handle it
            disc_pct = expiry_discount_pct(days_left)
            if disc_pct == 0:
                continue

            unit_price   = float(price_map.get(sku, 0))
            product_name = str(name_map.get(sku, row.get("product_name", sku)))

            recs.append({
                "_key": f"Expiry|{sku}|{row.get('batch_no','')}",
                "type": "Expiry",
                "sku": sku,
                "batch_no": str(row.get("batch_no", "")),
                "product_name": product_name,
                "current_stock": float(row["quantity"]),
                "current_price": unit_price,
                "suggested_discount": disc_pct,
                "final_price": round(unit_price * (1 - disc_pct / 100), 2),
                "reason": "Approaching Expiry",
                "shelf_life_remaining": days_left,
            })

    # ── 2. Dead Stock & Slow Moving ──────────────────────────────────────────
    try:
        from routes.dead_stock import get_analysis_data
        analysis = get_analysis_data()

        for item in analysis.get("sku_stats", []):
            sku         = str(item["sku"]).strip().upper()
            status_code = item.get("status_code", "healthy")

            if status_code == "dead":
                disc_pct, reason, rec_type = 25, "Dead Stock", "Dead Stock"
            elif status_code == "slow":
                disc_pct, reason, rec_type = 15, "Slow Moving Product", "Slow Moving"
            else:
                continue

            unit_price = float(price_map.get(sku, 0))
            recs.append({
                "_key": f"{rec_type}|{sku}",
                "type": rec_type,
                "sku": sku,
                "batch_no": "",
                "product_name": str(item.get("name", sku)),
                "current_stock": float(item.get("current_stock", 0)),
                "current_price": unit_price,
                "suggested_discount": disc_pct,
                "final_price": round(unit_price * (1 - disc_pct / 100), 2),
                "reason": reason,
                "shelf_life_remaining": None,
            })
    except Exception:
        pass

    return recs

# ── Auto-deactivation helpers ─────────────────────────────────────────────────

def check_auto_deactivate(store: dict) -> bool:
    """Deactivate discounts whose end date passed, batch expired, or stock = 0.
    Returns True if any change was made."""
    changed = False
    today_str = datetime.now().date().isoformat()

    batches_csv  = os.path.join(DATA_DIR, "inventory_batches.csv")
    products_csv = os.path.join(DATA_DIR, "products.csv")

    # Build quick lookup: batch_no -> {status, quantity, expiry_date}
    batch_lookup: dict = {}
    if os.path.exists(batches_csv):
        try:
            bdf = pd.read_csv(batches_csv).fillna("")
            for _, r in bdf.iterrows():
                batch_lookup[str(r.get("batch_no", ""))] = {
                    "status":  str(r.get("status", "active")),
                    "qty":     float(r.get("quantity", 0) or 0),
                    "expiry":  str(r.get("expiry_date", "")),
                }
        except Exception:
            pass

    # Build stock lookup: sku -> current_stock
    stock_lookup: dict = {}
    if os.path.exists(products_csv):
        try:
            pdf = pd.read_csv(products_csv).fillna("")
            for _, r in pdf.iterrows():
                sku = str(r.get("sku", "")).strip().upper()
                stock_lookup[sku] = float(r.get("current_stock", 0) or 0)
        except Exception:
            pass

    active_out = []
    for ad in store.get("active_discounts", []):
        if ad.get("status") != "active":
            active_out.append(ad)
            continue

        reason = None

        # End-date check
        end = ad.get("scheduled_end") or ""
        if end and end < today_str:
            reason = "End date reached"

        # Batch-level checks (for Expiry type)
        if not reason and ad.get("batch_no"):
            b = batch_lookup.get(ad["batch_no"], {})
            if b.get("status") in ("disposed", "expired"):
                reason = f"Batch {b.get('status', 'inactive')}"
            elif b.get("expiry", "") and b.get("expiry", "") < today_str:
                reason = "Batch expired"
            elif b.get("qty", 1) <= 0:
                reason = "Batch sold out"

        # SKU stock check
        if not reason:
            sku = str(ad.get("sku", "")).upper()
            if stock_lookup.get(sku, 1) <= 0:
                reason = "Product sold out"

        if reason:
            ad["status"] = "expired"
            ad["auto_deactivated_reason"] = reason
            ad["deactivated_at"] = now_str()
            store.setdefault("history", []).append({**ad, "_event": "auto_deactivated"})
            changed = True
        else:
            active_out.append(ad)

    store["active_discounts"] = active_out
    return changed

# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/recommendations")
def get_recommendations(payload: dict = Depends(verify_token)):
    store = load_store()

    # Run auto-deactivation first
    if check_auto_deactivate(store):
        save_store(store)

    # Generate fresh recs and merge (avoid duplicates by _key)
    # Rejected recs stay in the store so their keys are suppressed for 7 days
    fresh = generate_fresh_recommendations()
    today = datetime.now().date().isoformat()

    pending_by_key = {}
    existing_keys = set()
    for r in store["recommendations"]:
        if r.get("status") == "pending":
            pending_by_key[r.get("_key", "")] = r
            existing_keys.add(r.get("_key", ""))
        elif r.get("status") in ("approved", "scheduled"):
            existing_keys.add(r.get("_key", ""))
        elif r.get("status") == "rejected":
            # Suppress rejected keys for 7 days so same-tier re-generation is blocked
            rejected_at = r.get("updated_at", "")[:10]
            if rejected_at >= today[:10]:
                # Compare dates — keep blocked for 7 days
                from datetime import date as _date, timedelta as _td
                try:
                    r_date = _date.fromisoformat(rejected_at)
                    if (_date.today() - r_date).days < 7:
                        existing_keys.add(r.get("_key", ""))
                except Exception:
                    pass

    fresh_keys = {rec["_key"] for rec in fresh}
    added = 0
    changed = False

    # Auto-cancel any pending recommendation that is no longer freshly recommended (e.g. batch expired or sold out)
    for r in store["recommendations"]:
        if r.get("status") == "pending" and r.get("_key", "") not in fresh_keys:
            r["status"] = "auto_cancelled"
            r["updated_at"] = now_str()
            changed = True

    for rec in fresh:
        key = rec["_key"]
        existing = pending_by_key.get(key)
        # If it was just auto-cancelled, treat as not pending
        if existing is not None and existing.get("status") != "pending":
            existing = None

        if existing is not None:
            # Refresh live fields (shelf life, price, discount tier) on an already-pending rec
            fields = ("current_stock", "current_price", "suggested_discount",
                      "final_price", "shelf_life_remaining", "product_name")
            for f in fields:
                if existing.get(f) != rec.get(f):
                    existing[f] = rec.get(f)
                    changed = True
        elif key not in existing_keys:
            store["recommendations"].append({
                "id":          str(uuid.uuid4()),
                "_key":        key,
                "type":        rec["type"],
                "sku":         rec["sku"],
                "batch_no":    rec["batch_no"],
                "product_name": rec["product_name"],
                "current_stock": rec["current_stock"],
                "current_price": rec["current_price"],
                "suggested_discount": rec["suggested_discount"],
                "final_price": rec["final_price"],
                "reason":      rec["reason"],
                "shelf_life_remaining": rec.get("shelf_life_remaining"),
                "status":      "pending",
                "notes":       "",
                "scheduled_end": None,
                "created_at":  now_str(),
                "updated_at":  now_str(),
                "approved_by": None,
            })
            existing_keys.add(key)
            added += 1

    if added or changed:
        save_store(store)

    # Return only pending items (approved/rejected go to history/active)
    pending = [r for r in store["recommendations"] if r.get("status") == "pending"]
    pending.sort(key=lambda x: (
        {"Expiry": 0, "Dead Stock": 1, "Slow Moving": 2}.get(x.get("type", ""), 3),
        x.get("shelf_life_remaining") or 9999
    ))
    return pending


@router.post("/recommendations/{rec_id}/approve")
def approve_recommendation(rec_id: str, body: ApproveBody, payload: dict = Depends(verify_token)):
    store = load_store()
    rec = next((r for r in store["recommendations"] if r["id"] == rec_id), None)
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    if rec["status"] != "pending":
        raise HTTPException(400, f"Recommendation is already {rec['status']}")

    disc_pct = body.discount_percent if body.discount_percent is not None else rec["suggested_discount"]
    if not (1 <= disc_pct <= 90):
        raise HTTPException(400, "Discount percent must be between 1 and 90")

    user = payload.get("sub", "manager")
    final_price = round(rec["current_price"] * (1 - disc_pct / 100), 2)

    # Update recommendation
    rec["status"]        = "approved"
    rec["notes"]         = body.notes or ""
    rec["scheduled_end"] = body.scheduled_end or None
    rec["approved_by"]   = user
    rec["updated_at"]    = now_str()

    # Create active discount
    active = {
        "id":                str(uuid.uuid4()),
        "recommendation_id": rec_id,
        "sku":               rec["sku"],
        "batch_no":          rec["batch_no"],
        "product_name":      rec["product_name"],
        "discount_percent":  disc_pct,
        "original_price":    rec["current_price"],
        "discounted_price":  final_price,
        "reason":            rec["reason"],
        "type":              rec["type"],
        "current_stock":     rec["current_stock"],
        "approved_at":       now_str(),
        "approved_by":       user,
        "scheduled_end":     body.scheduled_end or None,
        "notes":             body.notes or "",
        "status":            "active",
    }
    store.setdefault("active_discounts", []).append(active)
    store.setdefault("history", []).append({**active, "_event": "approved"})
    save_store(store)
    append_audit("DISCOUNT_APPROVED",
                 f"{rec['product_name']} (SKU: {rec['sku']}) — {disc_pct}% off. Reason: {rec['reason']}",
                 user)
    return {"success": True, "active_discount": active}


@router.post("/recommendations/{rec_id}/reject")
def reject_recommendation(rec_id: str, body: RejectBody, payload: dict = Depends(verify_token)):
    store = load_store()
    rec = next((r for r in store["recommendations"] if r["id"] == rec_id), None)
    if not rec:
        raise HTTPException(404, "Recommendation not found")
    if rec["status"] != "pending":
        raise HTTPException(400, f"Recommendation is already {rec['status']}")

    user = payload.get("sub", "manager")
    rec["status"]     = "rejected"
    rec["notes"]      = body.notes or ""
    rec["updated_at"] = now_str()

    # Keep rejected rec in store with status "rejected" so its _key suppresses
    # re-generation for 7 days. Also add to history for audit trail.
    store.setdefault("history", []).append({**rec, "_event": "rejected"})
    save_store(store)
    append_audit("DISCOUNT_REJECTED",
                 f"{rec['product_name']} (SKU: {rec['sku']}) discount rejected. Notes: {body.notes}",
                 user)
    return {"success": True}


@router.post("/recommendations/{rec_id}/schedule")
def schedule_recommendation(rec_id: str, body: ApproveBody, payload: dict = Depends(verify_token)):
    """Approve with a mandatory end date (scheduled discount)."""
    if not body.scheduled_end:
        raise HTTPException(400, "scheduled_end date is required for scheduling")
    return approve_recommendation(rec_id, body, payload)


@router.get("/active")
def get_active_discounts(payload: dict = Depends(verify_token)):
    store = load_store()
    if check_auto_deactivate(store):
        save_store(store)
    active = [a for a in store.get("active_discounts", []) if a.get("status") == "active"]
    active.sort(key=lambda x: x.get("approved_at", ""), reverse=True)
    return active


@router.post("/active/{discount_id}/revoke")
def revoke_discount(discount_id: str, body: RevokeBody, payload: dict = Depends(verify_token)):
    store = load_store()
    ad = next((a for a in store.get("active_discounts", []) if a["id"] == discount_id), None)
    if not ad:
        raise HTTPException(404, "Active discount not found")
    if ad.get("status") != "active":
        raise HTTPException(400, "Discount is not active")

    user = payload.get("sub", "manager")
    ad["status"]         = "revoked"
    ad["revoked_at"]     = now_str()
    ad["revoked_by"]     = user
    ad["revoke_notes"]   = body.notes or ""

    # Remove from active, add to history
    store["active_discounts"] = [a for a in store["active_discounts"] if a["id"] != discount_id]
    store.setdefault("history", []).append({**ad, "_event": "revoked"})

    # Also mark matching recommendation as pending again so it can be re-evaluated
    rec_id = ad.get("recommendation_id", "")
    for r in store.get("recommendations", []):
        if r.get("id") == rec_id and r.get("status") == "approved":
            r["status"]     = "pending"
            r["updated_at"] = now_str()

    save_store(store)
    append_audit("DISCOUNT_REVOKED",
                 f"{ad['product_name']} (SKU: {ad['sku']}) discount revoked. Notes: {body.notes}",
                 user)
    return {"success": True, "message": f"Discount for {ad['product_name']} has been revoked. Original price restored."}


@router.get("/history")
def get_history(payload: dict = Depends(verify_token)):
    store = load_store()
    hist = store.get("history", [])
    hist.sort(key=lambda x: x.get("updated_at", x.get("revoked_at", x.get("approved_at", ""))), reverse=True)
    return hist


@router.get("/active-map")
def get_active_map():
    """Public endpoint — returns {sku: {discount_percent, discounted_price, original_price, reason, type}}
    Used by customer_products.py to apply real discounts."""
    store = load_store()
    result = {}
    today_str = datetime.now().date().isoformat()
    for ad in store.get("active_discounts", []):
        if ad.get("status") != "active":
            continue
        end = ad.get("scheduled_end") or ""
        if end and end < today_str:
            continue
        sku = str(ad.get("sku", "")).upper()
        # If multiple active discounts for same SKU, take highest %
        if sku not in result or ad["discount_percent"] > result[sku]["discount_percent"]:
            result[sku] = {
                "discount_percent":  ad["discount_percent"],
                "original_price":    ad["original_price"],
                "discounted_price":  ad["discounted_price"],
                "reason":            ad.get("reason", ""),
                "type":              ad.get("type", ""),
            }
    return result
