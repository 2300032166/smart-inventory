import os, json


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


def build_prompt(product: dict, pattern: dict, reorder: dict) -> str:
    cfg = load_ai_config()
    template = cfg.get("prompt_template", "")

    if not template:
        template = (
            "You are a store inventory advisor. Analyse the following product and "
            "generate a plain-English replenishment recommendation.\n\n"
            "Product: {product_name} (SKU: {sku})\n"
            "Current stock: {current_stock} {unit}\n"
            "Average daily sales (last 30 days): {avg_daily_sales} {unit}/day\n"
            "Days of stock remaining: {days_remaining} days\n"
            "Supplier lead time: {lead_time_days} days\n"
            "Calculated recommended order quantity: {recommended_qty} {unit}\n"
            "Payday spike detected: {payday_spike}\n"
            "Declining trend: {declining_trend}\n\n"
            "Override history (last 5 decisions for this product):\n"
            "{override_history_summary}\n\n"
            "Write exactly 2-3 sentences explaining WHY this order is recommended, "
            "in plain English that a store manager can understand. Mention specific "
            "patterns detected. Do not repeat the numbers — the UI already shows them. "
            "Do not use bullet points. Just write the reasoning paragraph."
        )

    override_summary = get_override_history_summary(product.get("sku", ""))

    return template.format(
        product_name=product.get("name", "Unknown"),
        sku=product.get("sku", ""),
        current_stock=product.get("current_stock", 0),
        unit=product.get("unit", "units"),
        avg_daily_sales=pattern.get("avg_daily_sales", 0),
        days_remaining=reorder.get("days_remaining", 0),
        lead_time_days=product.get("lead_time_days", 7),
        recommended_qty=reorder.get("recommended_qty", 0),
        payday_spike=pattern.get("payday_spike", False),
        declining_trend=pattern.get("declining_trend", False),
        override_history_summary=override_summary,
    )
