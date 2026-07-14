from datetime import datetime, timedelta
import os, json


def load_ai_config():
    cfg_path = os.path.join(os.path.dirname(__file__), "..", "data", "ai_config.json")
    try:
        with open(cfg_path) as f:
            return json.load(f)
    except Exception:
        return {"confidence_threshold": 60, "max_brief_items": 100, "payday_dates": [25, 26, 27]}


def calculate_reorder(product: dict, pattern: dict, weather_impact: dict = None) -> dict:
    from .pattern_detector import get_effective_today, get_payday_dates
    today = get_effective_today()
    payday_dates = get_payday_dates()
    
    current_stock = float(product.get("current_stock", 0))
    avg_daily = pattern.get("avg_daily_sales", 0)
    lead_time = int(product.get("lead_time_days", 7))
    pre_mult = weather_impact.get("pre_arrival_multiplier", 1.0) if weather_impact else 1.0
    post_mult = weather_impact.get("post_arrival_multiplier", 1.0) if weather_impact else 1.0
    
    # --- 1. Calculate DAYS REMAINING via Simulation ---
    # We iterate day-by-day to see exactly when stock runs out
    days_remaining = 999.0
    if avg_daily > 0:
        temp_stock = current_stock
        for d in range(1, 101): # Check up to 100 days
            sim_date = today + timedelta(days=d-1)
            daily_mult = 1.0
            if pattern.get("payday_spike") and sim_date.day in payday_dates:
                daily_mult *= 1.3
            if pattern.get("weekend_spike") and sim_date.weekday() in [4, 5, 6]:
                daily_mult *= 1.2
            
            # Use pre-arrival weather for the depletion forecast
            daily_mult *= pre_mult
            
            daily_demand = avg_daily * daily_mult
            if temp_stock <= daily_demand:
                # Fractional day for precision
                days_remaining = round((d - 1) + (temp_stock / daily_demand), 1) if daily_demand > 0 else d
                break
            temp_stock -= daily_demand
            if d == 100: days_remaining = 100.0

    if days_remaining <= lead_time:
        urgency = "urgent"
    elif days_remaining <= lead_time + 3.0:
        urgency = "normal"
    else:
        urgency = "low"

    # --- 2. Calculate RECOMMENDED QTY via Step-by-Step Forecast ---
    # We buffer for LeadTime + Dynamic Buffer
    forward_buffer = max(3, min(lead_time, 10))
    total_window = lead_time + forward_buffer
    forecast_demand = 0.0
    
    for d in range(total_window):
        sim_date = today + timedelta(days=d)
        daily_mult = 1.0
        
        # Temporal Spikes
        if pattern.get("payday_spike") and sim_date.day in payday_dates:
            daily_mult *= 1.3
        if pattern.get("weekend_spike") and sim_date.weekday() in [4, 5, 6]:
            daily_mult *= 1.2
            
        # Weather Stages
        # Pre-arrival for days before expected delivery, post-arrival after
        if d < lead_time:
            daily_mult *= pre_mult
        else:
            daily_mult *= post_mult
            
        forecast_demand += avg_daily * daily_mult

    safety_stock = max(avg_daily * 2, (avg_daily * 7) * 0.2)
    target_inventory = forecast_demand + safety_stock
    recommended_qty = int(round(max(0, target_inventory - current_stock)))

    # Risk level decision logic
    if days_remaining <= lead_time:
        risk_level = "CRITICAL_STOCKOUT"
    elif pre_mult > 1.2 and days_remaining < lead_time + 4:
         risk_level = "WEATHER_RISK"
    elif recommended_qty == 0 and days_remaining > lead_time + 20:
        risk_level = "OVERSTOCK"
    else:
        risk_level = "NORMAL"

    # Confidence calculation
    base_confidence = 60 if urgency == "normal" else (100 if urgency == "urgent" else 20)
    if weather_impact and weather_impact.get("confidence") == "LOW":
        confidence_score = 40 # Reduced confidence if forecast is unavailable
    else:
        confidence_score = base_confidence

    drivers = identify_drivers(product, pattern, {
        "days_remaining": days_remaining,
        "pre_arrival_multiplier": pre_mult,
        "post_arrival_multiplier": post_mult,
        "safety_stock": safety_stock
    }, weather_impact)

    return {
        "days_remaining": days_remaining,
        "urgency": urgency,
        "risk_level": risk_level,
        "recommended_qty": recommended_qty,
        "confidence_score": confidence_score,
        "pre_arrival_multiplier": pre_mult,
        "post_arrival_multiplier": post_mult,
        "delivery_date": weather_impact.get("delivery_date") if weather_impact else None,
        "weather_confidence": weather_impact.get("confidence", "HIGH") if weather_impact else "HIGH",
        "safety_stock": round(safety_stock, 1),
        "drivers": drivers
    }


def identify_drivers(product: dict, pattern: dict, reorder: dict, weather: dict = None) -> dict:
    factors = []
    # stay consistent with the dataset timeline
    from .pattern_detector import get_effective_today
    today = get_effective_today()
    
    # 1. Stockout Risk (Critical)
    days_rem = reorder.get('days_remaining', 999)
    if days_rem <= 3:
        factors.append({
            "id": "stockout_risk",
            "name": "Stockout Risk",
            "explanation": f"{product.get('name', 'Product')} is projected to run out within {days_rem} days."
        })
        
    # 2. Lead Time Risk
    lead_time = int(product.get('lead_time_days', 7))
    if days_rem <= lead_time and not any(f['id'] == 'stockout_risk' for f in factors):
        factors.append({
            "id": "lead_time_risk",
            "name": "Lead Time Risk",
            "explanation": f"Inventory won't last until next delivery (lead time: {lead_time} days)."
        })

    # 2.1 Order Soon (Normal items)
    elif days_rem <= lead_time + 3.0 and not any(f['id'] == 'stockout_risk' or f['id'] == 'lead_time_risk' for f in factors):
        factors.append({
            "id": "order_soon",
            "name": "Order Soon",
            "explanation": f"Order should be placed within 3 days to maintain optimal safety levels."
        })

    # 3. Weather Impact
    if reorder.get('pre_arrival_multiplier', 1.0) > 1.15 or reorder.get('post_arrival_multiplier', 1.0) > 1.15:
        reason = weather.get('reason', 'forecasted conditions') if weather else 'forecasted conditions'
        factors.append({
            "id": "weather_impact",
            "name": "Weather Impact",
            "explanation": f"Forecasted {reason} may increase demand. Additional stock is recommended to maintain availability."
        })

    # 4. Payday Effect
    if pattern.get('payday_spike') and today.day in [24, 25, 26, 27, 28]:
        factors.append({
            "id": "payday_effect",
            "name": "Payday Effect",
            "explanation": "Increased spending is expected during the monthly payday period based on historical sales patterns."
        })

    # 5. Weekend Effect
    if pattern.get('weekend_spike') and today.weekday() in [3, 4, 5, 6]:
        factors.append({
            "id": "weekend_effect",
            "name": "Weekend Effect",
            "explanation": "Weekend purchasing activity typically increases demand for this item. Current stock covers only a few days."
        })

    # 6. Summer Seasonal
    if today.month in [3, 4, 5] and product.get('category') in ['Beverages', 'Ice Cream', 'Dairy']:
        factors.append({
            "id": "summer_seasonal",
            "name": "Summer Demand",
            "explanation": "Summer demand patterns suggest increased consumption of beverages and cooling products."
        })

    # 7. Monsoon Seasonal
    if today.month in [6, 7, 8] and (product.get('category') == 'Rainwear' or 'Umbrella' in product['name'] or 'Raincoat' in product['name']):
        factors.append({
            "id": "monsoon_seasonal",
            "name": "Monsoon Demand",
            "explanation": "Monsoon season is expected to increase demand for rain-related products. Stock expansion advised."
        })

    # 8. Fast Moving
    if pattern.get('avg_daily_sales', 0) > 10:
        factors.append({
            "id": "fast_moving",
            "name": "Fast Moving",
            "explanation": "This product consistently ranks among the fastest-selling items and requires proactive replenishment."
        })

    # 9. Festival Demand
    festivals_path = os.path.join(os.path.dirname(__file__), "..", "data", "festivals.json")
    try:
        with open(festivals_path) as f:
            festivals = json.load(f)
        
        current_year = today.year
        for fest in festivals:
            fest_date_str = fest.get(f"date_{current_year}")
            if not fest_date_str: continue
            
            fest_date = datetime.strptime(fest_date_str, "%Y-%m-%d").date()
            # 5 days before festival up to the festival day
            if 0 <= (fest_date - today).days <= 5:
                if product.get('name') in fest.get('catalog_products', []):
                    factors.append({
                        "id": "festival_demand",
                        "name": f"{fest['name']} Readiness",
                        "explanation": f"High demand expected for {fest['name']} in the coming days."
                    })
                    break
    except Exception:
        pass

    # 9. Safety Stock Breach
    if float(product.get('current_stock', 0)) < reorder.get('safety_stock', 0):
        factors.append({
            "id": "safety_stock",
            "name": "Low Safety Stock",
            "explanation": "Stock has fallen below the safe limit."
        })

    if not factors:
        return {"primary": None, "supporting": [], "natural_explanation": ""}
    
    # 1. Calculate Order By Date
    days_left = reorder['days_remaining']
    l_time = int(product.get('lead_time_days', 7))
    buffer = days_left - l_time
    order_by_dt = today + timedelta(days=max(0, round(buffer)))
    order_by_str = f"Order by {order_by_dt.strftime('%B %d')}."
    if buffer <= 0:
        order_by_str = "Order today (ASAP)."

    # 2. Map IDs to very simple English
    simple_map = {
        "stockout_risk": "Stock is running very low.",
        "lead_time_risk": "Stock is low and won't last until next delivery.",
        "order_soon": "Order needs to be placed soon to avoid depletion.",
        "weather_impact": "Sales might go up due to weather changes.",
        "payday_effect": "Sales usually go up during payday.",
        "weekend_effect": "Sales usually go up on weekends.",
        "summer_seasonal": "Demand is higher during summer.",
        "monsoon_seasonal": "Demand is higher during monsoon.",
        "fast_moving": "This item sells very quickly.",
        "safety_stock": "Stock has fallen below the safe limit."
    }

    # Supporting factors (shorter)
    short_map = {
        "order_soon": "upcoming demand",
        "weather_impact": "weather changes",
        "payday_effect": "payday",
        "weekend_effect": "weekends",
        "summer_seasonal": "summer demand",
        "monsoon_seasonal": "monsoon season",
        "fast_moving": "high daily sales",
        "festival_demand": "upcoming festival"
    }

    p_name = product.get('name', 'This item')
    primary_id = factors[0]['id']
    supporting_ids = [f['id'] for f in factors[1:]]
    
    main_reason = simple_map.get(primary_id, "Replenishment is needed.")
    
    extras = [short_map[sid] for sid in supporting_ids if sid in short_map]
    
    if extras:
        if len(extras) == 1:
            natural_explanation = f"{main_reason} Extra sales expected from {extras[0]}. {order_by_str}"
        else:
            natural_explanation = f"{main_reason} Extra sales expected from {', '.join(extras[:-1])} and {extras[-1]}. {order_by_str}"
    else:
        natural_explanation = f"{main_reason} {order_by_str}"

    return {
        "primary": factors[0],
        "supporting": supporting_ids,
        "all_explanations": [f['explanation'] for f in factors],
        "natural_explanation": natural_explanation
    }


def should_include_in_brief(reorder: dict, cfg: dict = None) -> bool:
    if cfg is None:
        cfg = load_ai_config()
    
    urgency = reorder.get("urgency", "low")
    qty = reorder.get("recommended_qty", 0)
    
    # 1. Never show products that don't need ordering (qty 0)
    if qty <= 0:
        return False
        
    # 2. Only show Urgent or Normal items (matching the user's focus)
    if urgency == "low":
        return False
        
    # 3. Final check for confidence threshold
    threshold = cfg.get("confidence_threshold", 60)
    confidence = reorder.get("confidence_score", 0)
    if confidence < threshold:
        return False
        
    return True
