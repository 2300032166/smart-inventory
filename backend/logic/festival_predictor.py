import os
import json
import math
import pandas as pd
from datetime import datetime, timedelta
from logic.pattern_detector import load_sales, analyse_sku

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
FESTIVALS_FILE = os.path.join(DATA_DIR, "festivals.json")
PRODUCTS_FILE = os.path.join(DATA_DIR, "products.csv")


# ── Festival demand multipliers by product type ────────────────────────────────
# These are business-logic driven (not historical), for festival-catalog products
DEMAND_MULTIPLIERS = {
    "Festival Items": 3.0,   # Diyas, Flags, Rakhis — near-zero baseline, huge festival demand
    "Bakery":         2.5,   # Cakes surge massively during Christmas/Diwali
    "Snacks":         2.0,   # Chips, biscuits significantly higher during any festival
    "Grains":         1.8,   # Rice, ghee, sugar — staple festival cooking
    "Dairy":          1.6,   # Milk, curd — used in sweets and rituals
    "Beverages":      1.8,   # Soft drinks, juices — party & feasting
    "Fruits":         1.5,   # Fruits for puja and gifting
    "Vegetables":     1.4,   # Vegetables spike during feast-based festivals
    "Household":      1.3,   # Disposable plates/cups during large gatherings
    "Frozen":         1.2,
    "Personal Care":  1.1,
    "Stationery":     1.0,
    "Health":         1.0,
    "Baby Care":      1.0,
    "Seasonal":       1.2,
}

FESTIVAL_PEAK_DAYS = 7  # Days of peak demand during the festival window


def load_festivals() -> list:
    try:
        with open(FESTIVALS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def load_products_dict() -> list:
    try:
        from logic.pattern_detector import load_products_dynamic
        return load_products_dynamic()
    except Exception:
        try:
            df = pd.read_csv(PRODUCTS_FILE)
            return df.fillna("").to_dict(orient="records")
        except Exception:
            return []


def fuzzy_match_product(catalog_name: str, products: list) -> dict | None:
    """
    Find the best matching product from inventory for a catalog name.
    Uses partial string matching for flexibility.
    """
    catalog_lower = catalog_name.lower().strip()

    # Exact name match first
    for p in products:
        if p["name"].lower().strip() == catalog_lower:
            return p

    # Partial match — catalog name is contained in product name or vice versa
    for p in products:
        prod_lower = p["name"].lower()
        # Check if key words from catalog name appear in product name
        key_words = [w for w in catalog_lower.split() if len(w) > 3]
        if all(w in prod_lower for w in key_words):
            return p
        # Or if product name is contained in catalog name
        if prod_lower in catalog_lower or catalog_lower in prod_lower:
            return p

    # Fallback: any shared meaningful word
    for p in products:
        prod_lower = p["name"].lower()
        catalog_words = set(w for w in catalog_lower.split() if len(w) > 3)
        prod_words = set(w for w in prod_lower.split() if len(w) > 3)
        if catalog_words & prod_words:  # any common meaningful word
            return p

    return None


def calculate_status(current_stock: float, required: float, lead_time_avg_demand: float, lead_time: int) -> str:
    """Determine stock readiness status."""
    if current_stock <= 0:
        return "At Risk"
    if required <= 0:
        return "Overstocked"
    coverage = current_stock / required if required > 0 else 999
    lead_demand = lead_time_avg_demand * lead_time

    if current_stock > required * 1.5:
        return "Overstocked"
    elif current_stock >= required:
        return "Ready"
    elif current_stock >= lead_demand:
        return "Low Stock"
    else:
        return "At Risk"


def get_festival_lift_and_predictions(festival_name: str, simulated_today: str = None) -> dict:
    """
    Festival Product Catalog approach:
    - Uses curated catalog per festival defined in festivals.json
    - Matches catalog products to actual inventory
    - Calculates readiness status (Ready / Low Stock / At Risk / Overstocked / Not Available)
    - Generates AI explanations based on inventory data + lead time
    """
    festivals = load_festivals()
    festival = next((f for f in festivals if f["name"] == festival_name), None)
    if not festival:
        return {"error": f"Festival '{festival_name}' not found."}

    # Resolve planning date (with demo mode)
    fest_date = pd.to_datetime(festival["date_2026"])
    real_today = pd.to_datetime(datetime.now().date())
    days_diff = (fest_date - real_today).days
    is_simulated = False

    if simulated_today:
        today = pd.to_datetime(simulated_today)
        is_simulated = True
    else:
        # Increase threshold to 365 days to show real distances for all year festivals
        if days_diff < 0 or days_diff > 365:
            today = fest_date - timedelta(days=14)
            is_simulated = True
        else:
            today = real_today

    days_until_fest = (fest_date - today).days

    # Load data
    products = load_products_dict()
    sales_df = load_sales()
    catalog = festival.get("catalog_products", [])

    predictions = []
    count_ready = 0
    count_at_risk = 0
    count_low_stock = 0
    count_not_available = 0
    count_overstocked = 0
    total_rec_qty = 0
    all_readiness_scores = []

    for cat_prod_name in catalog:
        matched_product = fuzzy_match_product(cat_prod_name, products)

        if matched_product is None:
            # Product not in inventory at all
            predictions.append({
                "catalog_name": cat_prod_name,
                "sku": None,
                "product_name": cat_prod_name,
                "category": "—",
                "unit": "units",
                "current_stock": 0,
                "normal_avg_daily": 0,
                "festival_avg_daily": 0,
                "demand_multiplier": 0,
                "total_required": 0,
                "recommended_order": 0,
                "lead_time": 0,
                "safe_order_date": "—",
                "readiness_score": 0,
                "status": "Not Available",
                "ai_reasoning": f"{cat_prod_name} is not currently in your inventory. Consider adding it from a supplier to capture {festival_name} demand."
            })
            count_not_available += 1
            continue

        sku = matched_product["sku"]
        category = matched_product.get("category", "")
        lead_time = int(matched_product.get("lead_time_days", 5))
        current_stock = float(matched_product.get("current_stock", 0))
        unit = matched_product.get("unit", "units")

        # Get current average daily sales from sales data
        pattern = analyse_sku(sku, sales_df)
        avg_daily = pattern.get("avg_daily_sales", 0)

        # If no sales history, estimate based on reorder threshold
        if avg_daily <= 0:
            reorder_thresh = float(matched_product.get("reorder_threshold", 20))
            avg_daily = max(0.5, reorder_thresh / 30.0)

        # Calculate festival demand
        category_multiplier = DEMAND_MULTIPLIERS.get(category, 1.3)
        fest_avg_daily = avg_daily * category_multiplier

        # What's needed: pre-festival run-rate + festival peak window
        needed_pre_fest = avg_daily * max(0, days_until_fest)
        needed_during_fest = fest_avg_daily * FESTIVAL_PEAK_DAYS
        total_required = needed_pre_fest + needed_during_fest

        # Replenishment
        additional_needed = max(0.0, total_required - current_stock)
        rec_qty = math.ceil(additional_needed * 1.1) if additional_needed > 0 else 0
        total_rec_qty += rec_qty

        # Safe order date
        safe_date = (fest_date - timedelta(days=lead_time + 2))
        safe_order_date = safe_date.strftime("%Y-%m-%d")

        # Readiness score
        if total_required > 0:
            readiness_score = min(100, round((current_stock / total_required) * 100))
        else:
            readiness_score = 100

        all_readiness_scores.append(readiness_score)

        # Status
        status = calculate_status(current_stock, total_required, avg_daily, lead_time)
        if status == "Ready": count_ready += 1
        elif status == "At Risk": count_at_risk += 1
        elif status == "Low Stock": count_low_stock += 1
        elif status == "Overstocked": count_overstocked += 1

        # AI Reasoning
        ai_reasoning = _generate_reasoning(
            matched_product["name"], festival_name, status,
            current_stock, rec_qty, avg_daily, fest_avg_daily,
            lead_time, safe_order_date, days_until_fest, unit,
            category_multiplier
        )

        predictions.append({
            "catalog_name": cat_prod_name,
            "sku": sku,
            "product_name": matched_product["name"],
            "category": category,
            "unit": unit,
            "current_stock": current_stock,
            "normal_avg_daily": round(avg_daily, 2),
            "festival_avg_daily": round(fest_avg_daily, 2),
            "demand_multiplier": category_multiplier,
            "total_required": round(total_required),
            "recommended_order": rec_qty,
            "lead_time": lead_time,
            "safe_order_date": safe_order_date,
            "readiness_score": readiness_score,
            "status": status,
            "ai_reasoning": ai_reasoning
        })

    # Sort: At Risk → Low Stock → Not Available → Overstocked → Ready
    status_order = {"At Risk": 0, "Low Stock": 1, "Not Available": 2, "Overstocked": 3, "Ready": 4}
    predictions.sort(key=lambda x: (status_order.get(x["status"], 9), -x.get("recommended_order", 0)))

    # Overall readiness score
    avg_readiness = round(sum(all_readiness_scores) / len(all_readiness_scores)) if all_readiness_scores else 0

    return {
        "summary": {
            "festival_name": festival["name"],
            "festival_date": festival["date_2026"],
            "days_remaining": days_until_fest,
            "readiness_score": avg_readiness,
            "total_catalog_products": len(catalog),
            "products_ready": count_ready,
            "products_low_stock": count_low_stock,
            "products_at_risk": count_at_risk,
            "products_overstocked": count_overstocked,
            "products_not_available": count_not_available,
            "total_rec_qty": total_rec_qty,
            "simulated": is_simulated,
            "description": festival.get("description", "")
        },
        "predictions": predictions
    }


def _generate_reasoning(name, festival, status, stock, rec_qty, avg_daily,
                        fest_daily, lead_time, order_date, days, unit, multiplier) -> str:
    pct = round((multiplier - 1) * 100)
    if status == "Ready":
        return (f"Current stock of {int(stock)} {unit} is sufficient for {festival}. "
                f"Expected festival demand is ~{pct}% above normal. No immediate action required.")
    elif status == "Overstocked":
        return (f"You have {int(stock)} {unit} in stock — well above the projected festival demand. "
                f"No replenishment needed for {festival}.")
    elif status == "Low Stock":
        return (f"Stock level of {int(stock)} {unit} is below the required festival buffer. "
                f"Festival demand for {name} is expected to be {pct}% higher than normal. "
                f"Order {rec_qty} {unit} before {order_date} to stay stocked.")
    elif status == "At Risk":
        return (f"URGENT: Only {int(stock)} {unit} remaining. With {days} days until {festival} "
                f"and a supplier lead time of {lead_time} days, stock will run out before the festival peaks. "
                f"Order {rec_qty} {unit} before {order_date} immediately.")
    elif status == "Not Available":
        return f"{name} is not in inventory. Add this product for {festival} — demand typically spikes by {pct}%."
    else:
        return f"Review stock for {name} ahead of {festival}."


async def generate_festival_brief(p: dict, festival_name: str) -> str:
    return p.get("ai_reasoning", "")
