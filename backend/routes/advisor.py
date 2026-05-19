from fastapi import APIRouter, Depends, Query, HTTPException
import pandas as pd
import json, os
from datetime import datetime, timezone

from middleware.auth_middleware import require_role
from logic.pattern_detector import load_sales, analyse_sku
from logic.reorder_calculator import calculate_reorder, should_include_in_brief, load_ai_config
from logic.prompt_builder import build_prompt
from logic.ai_client import generate_reasoning

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
BRIEF_LOG = os.path.join(DATA_DIR, "brief_log.json")


def load_products():
    import pandas as pd
    df = pd.read_csv(os.path.join(DATA_DIR, "products.csv"))
    return df.fillna("").to_dict(orient="records")


def load_brief_log():
    try:
        with open(BRIEF_LOG) as f:
            return json.load(f)
    except Exception:
        return {}


def save_brief_log(log: dict):
    with open(BRIEF_LOG, "w") as f:
        json.dump(log, f, indent=2)


@router.get("/today")
async def get_today_brief(payload: dict = Depends(require_role("manager"))):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cfg = load_ai_config()
    cache_hours = int(cfg.get("brief_cache_hours", 6))

    log = load_brief_log()
    cached = log.get(today)
    if cached:
        cached_at = cached.get("generated_at", "")
        if cached_at:
            try:
                gen_time = datetime.fromisoformat(cached_at)
                now = datetime.now(timezone.utc)
                if (now - gen_time).total_seconds() < cache_hours * 3600:
                    return cached.get("items", [])
            except Exception:
                pass

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
        try:
            reasoning = await generate_reasoning(prompt)
        except Exception as e:
            reasoning = (
                "Based on current stock levels, this product needs replenishment "
                "to avoid a stockout before the next delivery can arrive."
            )

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

    return results


@router.get("/history")
def get_brief_history(
    date: str = Query(...),
    payload: dict = Depends(require_role("manager")),
):
    log = load_brief_log()
    entry = log.get(date)
    if not entry:
        raise HTTPException(status_code=404, detail=f"No brief found for date {date}")
    return entry.get("items", [])
