from datetime import datetime
import os, json


def load_ai_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "data", "ai_config.json")
    try:
        with open(cfg_path) as f:
            return json.load(f)
    except Exception:
        return {"confidence_threshold": 60, "max_brief_items": 10, "payday_dates": [25, 26, 27]}


def calculate_reorder(product: dict, pattern: dict) -> dict:
    current_stock = float(product.get("current_stock", 0))
    avg_daily = pattern.get("avg_daily_sales", 0)
    lead_time = int(product.get("lead_time_days", 7))
    payday_spike = pattern.get("payday_spike", False)

    if avg_daily <= 0:
        days_remaining = 999
    else:
        days_remaining = round(current_stock / avg_daily, 1)

    if days_remaining < lead_time:
        urgency = "urgent"
    elif days_remaining < lead_time * 1.5:
        urgency = "normal"
    else:
        urgency = "low"

    if avg_daily > 0:
        base_qty = (avg_daily * (lead_time + 7)) - current_stock
        if base_qty < 0:
            base_qty = 0

        today_day = datetime.now().day
        cfg = load_ai_config()
        payday_days = cfg.get("payday_dates", [25, 26, 27])
        days_until_payday = min([(d - today_day) % 30 for d in payday_days])

        if payday_spike and days_until_payday <= lead_time:
            base_qty *= 1.5

        recommended_qty = round(base_qty)
    else:
        recommended_qty = 0

    # Risk level decision logic
    if days_remaining <= lead_time:
        risk_level = "CRITICAL_STOCKOUT"
    elif recommended_qty == 0 and days_remaining > lead_time + 14:
        risk_level = "OVERSTOCK"
    else:
        risk_level = "NORMAL"

    urgency_score_map = {"urgent": 100, "normal": 60, "low": 20}
    confidence_score = urgency_score_map.get(urgency, 20)

    return {
        "days_remaining": days_remaining,
        "urgency": urgency,
        "risk_level": risk_level,
        "recommended_qty": max(0, recommended_qty),
        "confidence_score": confidence_score,
    }


def should_include_in_brief(reorder: dict, cfg: dict = None) -> bool:
    if cfg is None:
        cfg = load_ai_config()
    threshold = cfg.get("confidence_threshold", 60)
    urgency = reorder.get("urgency", "low")
    confidence = reorder.get("confidence_score", 0)
    if urgency == "low" and confidence < threshold:
        return False
    return True
