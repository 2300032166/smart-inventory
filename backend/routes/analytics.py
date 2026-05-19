from fastapi import APIRouter, Depends, Query
from typing import Optional
import json, os
from datetime import datetime, timedelta, timezone
from collections import Counter

from middleware.auth_middleware import require_role

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_overrides():
    try:
        with open(os.path.join(DATA_DIR, "override_history.json")) as f:
            return json.load(f)
    except Exception:
        return []


@router.get("/overrides")
def get_override_analytics(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    manager_id: Optional[str] = Query(None),
    payload: dict = Depends(require_role("admin")),
):
    overrides = load_overrides()

    if date_from:
        overrides = [o for o in overrides if o.get("timestamp", "") >= date_from]
    if date_to:
        overrides = [o for o in overrides if o.get("timestamp", "")[:10] <= date_to]
    if manager_id:
        overrides = [o for o in overrides if o.get("manager_id") == manager_id]

    total = len(overrides)
    if total == 0:
        return {
            "total_suggestions": 0,
            "approved_pct": 0,
            "overridden_pct": 0,
            "skipped_pct": 0,
            "top_overridden_products": [],
            "approval_rate_over_time": [],
            "reason_breakdown": {},
            "quantity_delta_products": [],
        }

    decisions = Counter(o.get("decision") for o in overrides)
    approved_pct = round(decisions.get("approved", 0) / total * 100, 1)
    overridden_pct = round(decisions.get("overridden", 0) / total * 100, 1)
    skipped_pct = round(decisions.get("skipped", 0) / total * 100, 1)

    overridden_records = [o for o in overrides if o.get("decision") == "overridden"]
    sku_override_count = Counter(o.get("sku") for o in overridden_records)
    top_overridden = [
        {"sku": sku, "product_name": next((o["product_name"] for o in overridden_records if o["sku"] == sku), sku), "count": count}
        for sku, count in sku_override_count.most_common(10)
    ]

    reason_counts = Counter(o.get("reason_category", "Other") for o in overridden_records if o.get("reason_category"))
    reason_breakdown = dict(reason_counts)

    today = datetime.now(timezone.utc).date()
    approval_timeline = []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.isoformat()
        day_records = [o for o in overrides if o.get("timestamp", "")[:10] == day_str]
        day_total = len(day_records)
        day_approved = len([o for o in day_records if o.get("decision") == "approved"])
        rate = round(day_approved / day_total * 100, 1) if day_total > 0 else None
        approval_timeline.append({"date": day_str, "approval_rate": rate, "total": day_total})

    qty_delta = []
    for sku, group in {o["sku"]: [] for o in overridden_records}.items():
        sku_records = [o for o in overridden_records if o["sku"] == sku]
        deltas = [abs(float(o.get("actual_qty", 0)) - float(o.get("ai_suggested_qty", 0))) for o in sku_records]
        avg_delta = round(sum(deltas) / len(deltas), 1) if deltas else 0
        qty_delta.append({
            "sku": sku,
            "product_name": sku_records[0].get("product_name", sku) if sku_records else sku,
            "avg_qty_delta": avg_delta,
            "override_count": len(sku_records),
        })
    qty_delta.sort(key=lambda x: x["avg_qty_delta"], reverse=True)

    return {
        "total_suggestions": total,
        "approved_pct": approved_pct,
        "overridden_pct": overridden_pct,
        "skipped_pct": skipped_pct,
        "top_overridden_products": top_overridden,
        "approval_rate_over_time": approval_timeline,
        "reason_breakdown": reason_breakdown,
        "quantity_delta_products": qty_delta[:10],
    }
