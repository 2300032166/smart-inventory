from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import json, os, uuid, logging
from datetime import datetime, timezone

from middleware.auth_middleware import require_role

logger = logging.getLogger(__name__)

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OVERRIDE_FILE = os.path.join(DATA_DIR, "override_history.json")
AUDIT_FILE = os.path.join(DATA_DIR, "audit_log.json")


def load_overrides() -> list:
    try:
        with open(OVERRIDE_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_overrides(data: list):
    with open(OVERRIDE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_audit() -> list:
    try:
        with open(AUDIT_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_audit(data: list):
    with open(AUDIT_FILE, "w") as f:
        json.dump(data, f, indent=2)


class DecisionRequest(BaseModel):
    sku: str
    product_name: str = ""
    decision: str
    ai_suggested_qty: float = 0
    actual_qty: float = 0
    reason_category: str = ""
    reason_text: str = ""


@router.post("/decide")
def record_decision(
    body: DecisionRequest,
    request: Request,
    payload: dict = Depends(require_role("manager")),
):
    if body.decision not in ("approved", "overridden", "skipped"):
        raise HTTPException(
            status_code=400, detail="decision must be approved, overridden, or skipped"
        )

    overrides = load_overrides()
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sku": body.sku,
        "product_name": body.product_name,
        "ai_suggested_qty": body.ai_suggested_qty,
        "actual_qty": body.actual_qty,
        "decision": body.decision,
        "reason_category": body.reason_category,
        "reason_text": body.reason_text,
        "manager_id": payload.get("sub"),
        "manager_name": payload.get("name"),
    }
    overrides.append(record)
    save_overrides(overrides)

    audit = load_audit()
    ip = request.client.host if request.client else "unknown"
    audit.append({
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": payload.get("sub"),
        "user_name": payload.get("name"),
        "role": payload.get("role"),
        "action_type": f"ORDER_{body.decision.upper()}",
        "description": (
            f"{body.decision.title()} order for {body.product_name} "
            f"(SKU: {body.sku}), qty: {body.actual_qty}"
        ),
        "ip_address": ip,
    })
    save_audit(audit)

    logger.info(
        "[Orders] Decision recorded | sku=%s | decision=%s | manager=%s",
        body.sku, body.decision, payload.get("name"),
    )
    return {"message": "Decision recorded", "id": record["id"]}


@router.get("/reviewed")
def get_reviewed_by_date(
    date: str = Query(None),
    payload: dict = Depends(require_role("manager"))
):
    """Return all manager decisions made on a specific date (or today if None)."""
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    overrides = load_overrides()
    day_items = [o for o in overrides if o.get("timestamp", "")[:10] == target_date]
    day_items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    logger.info("[Orders] Reviewed on %s: %d items", target_date, len(day_items))
    return day_items


@router.get("/history")
def get_order_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sku: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    payload: dict = Depends(require_role("manager")),
):
    overrides = load_overrides()
    overrides.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    if sku:
        overrides = [o for o in overrides if o.get("sku") == sku]
    if decision:
        overrides = [o for o in overrides if o.get("decision") == decision]
    if date_from:
        overrides = [o for o in overrides if o.get("timestamp", "") >= date_from]
    if date_to:
        overrides = [o for o in overrides if o.get("timestamp", "")[:10] <= date_to]

    total = len(overrides)
    start = (page - 1) * limit
    items = overrides[start: start + limit]

    return {"total": total, "page": page, "limit": limit, "items": items}
