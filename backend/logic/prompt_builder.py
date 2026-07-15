import os, json
from datetime import datetime, timezone

def load_ai_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "data", "ai_config.json")
    try:
        with open(cfg_path) as f:
            return json.load(f)
    except Exception:
        return {}

def get_override_history_summary(sku: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "..", "data", "override_history.json")
    try:
        with open(path) as f:
            history = json.load(f)
    except Exception:
        return "No override history."

    sku_history = [h for h in history if h.get("sku") == sku]
    sku_history = sorted(sku_history, key=lambda x: x.get("timestamp", ""), reverse=True)[:5]

    if not sku_history:
        return "No previous decisions for this product."

    lines = []
    for h in sku_history:
        line = (
            f"{h.get('timestamp', '')[:10]}: {h.get('decision', 'unknown')} "
            f"(AI suggested {h.get('ai_suggested_qty', 0)}, actual {h.get('actual_qty', 0)})"
        )
        if h.get("reason_text"):
            line += f" — {h['reason_text']}"
        lines.append(line)
    return "\n".join(lines)

def build_prompt(product: dict, pattern: dict, reorder: dict, weather_impact: dict = None) -> str:
    from .pattern_detector import get_effective_today
    today = get_effective_today()
    
    arrival_date_raw = reorder.get('delivery_date', '')
    arrival_date = "TBD"
    if arrival_date_raw:
        try:
            arrival_date = datetime.strptime(arrival_date_raw, "%Y-%m-%d").strftime("%B %d")
        except:
            arrival_date = arrival_date_raw

    lead_time = int(product.get('lead_time_days', 7))
    pre_mult = reorder.get("pre_arrival_multiplier", 1.0)
    post_mult = reorder.get("post_arrival_multiplier", 1.0)
    
    drivers = reorder.get("drivers", {})
    all_explanations = drivers.get("all_explanations", []) if drivers else []
    
    prompt = f"""
You are SIRA, the AI assistant for a grocery store. 
Today's date is {today.strftime('%B %d, %Y')}.

Analyze this product's data and provide a concise SINGLE sentence replenishment recommendation.
Product: {product['name']}
Category: {product.get('category', 'General')}
Current Stock: {product['current_stock']} {product.get('unit', 'units')}
Daily Sales Velocity: {pattern['avg_daily_sales']} {product.get('unit', 'units')}/day
Days Remaining: {reorder['days_remaining']}
Earliest Expiry Date: {product.get('expiry_date', 'N/A')}
Lead Time (to get new stock): {lead_time} days
Expected Arrival if ordered now: {arrival_date}
System Recommended Order Quantity: {reorder['recommended_qty']} {product.get('unit', 'units')}

Significant Demand Drivers: {", ".join(all_explanations) if all_explanations else "Normal demand patterns."}
Weather Context: {"Significant weather impact detected." if (pre_mult > 1.1 or post_mult > 1.1) else "Steady weather."}

Rules:
1. CRITICAL: You MUST use exactly {reorder['recommended_qty']} as the order quantity. Never suggest a different number.
2. Speak plainly like a human store assistant. 
3. Use "selling quickly" instead of "velocity".
4. Mention the specific delivery goal/date ({arrival_date}) if relevant to the stock level.
5. ONLY mention demand drivers (weekends, paydays, weather, festivals) if they are explicitly listed in the Significant Demand Drivers above.
6. If no special drivers are present, focus on simple restocking to avoid running out.
7. Forbidden: "There are no special factors", "I recommend", "Velocity", "High/Low demand".
8. Be direct and actionable.
9. Vary the wording and sentence structure from one item to the next. Do not sound templated or repetitive.
"""
    return prompt

