from fastapi import APIRouter, Depends, Query, HTTPException
import pandas as pd
import json, os, logging
from datetime import datetime, timezone

from middleware.auth_middleware import require_role
from logic.pattern_detector import load_sales, analyse_sku
from logic.reorder_calculator import calculate_reorder, should_include_in_brief, load_ai_config
from logic.prompt_builder import build_prompt
from logic.ai_client import generate_reasoning
from .alerts import create_alert

logger = logging.getLogger(__name__)

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
BRIEF_LOG = os.path.join(DATA_DIR, "brief_log.json")
OVERRIDE_FILE = os.path.join(DATA_DIR, "override_history.json")


def load_products():
    df = pd.read_csv(os.path.join(DATA_DIR, "products.csv"))
    return df.fillna("").to_dict(orient="records")


def load_brief_log() -> dict:
    try:
        with open(BRIEF_LOG) as f:
            return json.load(f)
    except Exception:
        return {}


def save_brief_log(log: dict):
    with open(BRIEF_LOG, "w") as f:
        json.dump(log, f, indent=2)


def load_overrides() -> list:
    try:
        with open(OVERRIDE_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def get_decided_skus(hours: int = 48) -> set:
    """Return the set of SKUs that have a manager decision within the last X hours."""
    overrides = load_overrides()
    from datetime import datetime, timedelta, timezone
    limit = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    return {str(o.get("sku", "")).strip().upper() for o in overrides if o.get("timestamp", "") >= limit}


@router.get("/today")
async def get_today_brief(payload: dict = Depends(require_role("manager"))):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cfg = load_ai_config()
    log = load_brief_log()
    products = load_products()
    sales_df = load_sales()
    max_items = int(cfg.get("max_brief_items", 10))

    candidates = []
    for p in products:
        pattern = analyse_sku(p["sku"], sales_df)
        reorder = calculate_reorder(p, pattern)
        if should_include_in_brief(reorder, cfg):
            candidates.append((p, pattern, reorder))

    candidates.sort(key=lambda x: x[2].get("confidence_score", 0), reverse=True)
    candidates = candidates[:max_items]

    results = []
    for p, pattern, reorder in candidates:
        prompt = build_prompt(p, pattern, reorder)
        logger.info("[Brief] Generating Gemini reasoning for SKU=%s", p["sku"])
        try:
            reasoning = await generate_reasoning(prompt)
        except Exception as exc:
            logger.error("[Brief] generate_reasoning raised for SKU=%s: %s", p["sku"], exc)
            reasoning = "AI explanation generation failed"

        results.append({
            "sku": p["sku"],
            "product_name": p["name"],
            "category": p.get("category", ""),
            "current_stock": p["current_stock"],
            "unit": p.get("unit", "units"),
            "avg_daily_sales": pattern["avg_daily_sales"],
            "days_remaining": reorder["days_remaining"],
            "lead_time_days": p.get("lead_time_days", 7),
            "recommended_qty": reorder["recommended_qty"],
            "urgency": reorder["urgency"],
            "risk_level": reorder.get("risk_level", "NORMAL"),
            "ai_reasoning": reasoning,
            "confidence_score": reorder["confidence_score"],
            "payday_spike": pattern["payday_spike"],
            "declining_trend": pattern["declining_trend"],
        })

        if reorder.get("risk_level") == "CRITICAL_STOCKOUT":
            create_alert(
                user_id="all",
                alert_type="stockout",
                title=f"Critical Stockout: {p['name']}",
                message=f"Stock for {p['name']} will run out in {reorder['days_remaining']} days. Order suggested: {reorder['recommended_qty']} {p.get('unit', 'units')}."
            )

    log[today] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": results,
    }
    save_brief_log(log)

    return results


@router.get("/pending")
async def get_pending_brief(payload: dict = Depends(require_role("manager"))):
    """Return today's brief items that have NOT yet been decided by the manager.

    Data source: brief_log.json filtered against override_history.json (today).
    This is what the Daily Brief page displays.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Get (or generate) today's full brief first
    log = load_brief_log()
    entry = log.get(today)

    if not entry:
        # Trigger generation via the /today endpoint logic
        # We call get_today_brief by recreating the payload — easier to just
        # call the underlying functions directly.
        cfg = load_ai_config()
        products = load_products()
        sales_df = load_sales()
        max_items = int(cfg.get("max_brief_items", 10))

        candidates = []
        for p in products:
            pattern = analyse_sku(p["sku"], sales_df)
            reorder = calculate_reorder(p, pattern)
            if should_include_in_brief(reorder, cfg):
                candidates.append((p, pattern, reorder))

        candidates.sort(key=lambda x: x[2].get("confidence_score", 0), reverse=True)
        candidates = candidates[:max_items]

        results = []
        for p, pattern, reorder in candidates:
            prompt = build_prompt(p, pattern, reorder)
            logger.info("[Pending] Generating Gemini reasoning for SKU=%s", p["sku"])
            try:
                reasoning = await generate_reasoning(prompt)
            except Exception as exc:
                logger.error("[Pending] generate_reasoning raised for SKU=%s: %s", p["sku"], exc)
                reasoning = "AI explanation generation failed"

            results.append({
                "sku": p["sku"],
                "product_name": p["name"],
                "category": p.get("category", ""),
                "current_stock": p["current_stock"],
                "unit": p.get("unit", "units"),
                "avg_daily_sales": pattern["avg_daily_sales"],
                "days_remaining": reorder["days_remaining"],
                "lead_time_days": p.get("lead_time_days", 7),
                "recommended_qty": reorder["recommended_qty"],
                "urgency": reorder["urgency"],
                "risk_level": reorder.get("risk_level", "NORMAL"),
                "ai_reasoning": reasoning,
                "confidence_score": reorder["confidence_score"],
                "payday_spike": pattern["payday_spike"],
                "declining_trend": pattern["declining_trend"],
            })

        log[today] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": results,
        }
        save_brief_log(log)
        all_items = results
    else:
        all_items = entry.get("items", [])

    # Filter out SKUs that the manager has already decided on recently (48h)
    decided_skus = get_decided_skus(48)
    pending = [item for item in all_items if str(item.get("sku", "")).strip().upper() not in decided_skus]

    logger.info(
        "[Pending] today=%s total=%d decided=%d pending=%d",
        today, len(all_items), len(decided_skus), len(pending),
    )
    return pending


@router.get("/history")
def get_brief_history(
    date: str = Query(...),
    payload: dict = Depends(require_role("manager")),
):
    """Return brief items for a specific date that were NOT decided on."""
    log = load_brief_log()
    entry = log.get(date)
    if not entry:
        raise HTTPException(status_code=404, detail=f"No brief found for date {date}")

    all_items = entry.get("items", [])
    # For history, we just show what was in the brief regardless of recent decisions
    # OR we can keep the filter if we only want "truly" pending items for that date.
    # The requirement is specifically about the dashboard mismatch, so let's keep it simple.
    decided_skus = get_decided_skus(48)
    pending = [item for item in all_items if str(item.get("sku", "")).strip().upper() not in decided_skus]

    logger.info("[Brief History] date=%s total=%d pending=%d", date, len(all_items), len(pending))
    return pending
