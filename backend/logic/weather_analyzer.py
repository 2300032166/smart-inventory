import logging

logger = logging.getLogger(__name__)

# Weather Sensitivity Mappings for Vijayawada
# Multipliers for demand based on weather conditions
SENSITIVITY = {
    "Dairy": {"high_temp": 1.0, "rain": 1.0},        # User feedback: Daily stable product
    "Frozen": {"high_temp": 1.5, "rain": 0.8, "weather_sensitive": True},        # Ice cream spikes in heat
    "Beverages": {"high_temp": 1.4, "rain": 1.1, "weather_sensitive": True},     # Cold drinks in heat
    "Household": {"high_temp": 1.0, "rain": 1.8, "weather_sensitive": True},     # Umbrellas/Raincoats
    "Vegetables": {"high_temp": 1.0, "rain": 1.0, "weather_sensitive": False},
    "Fruits": {"high_temp": 1.0, "rain": 1.0, "weather_sensitive": False},
    "Bakery": {"high_temp": 0.9, "rain": 1.1, "weather_sensitive": False},
    "Grains": {"high_temp": 1.0, "rain": 1.0, "weather_sensitive": False},
    "Grocery": {"high_temp": 1.0, "rain": 1.05, "weather_sensitive": False},
    "Cooking Oil": {"high_temp": 1.0, "rain": 1.0, "weather_sensitive": False},
}

def analyze_weather_for_windows(forecast: list, category: str, lead_time: int) -> dict:
    """
    Analyzes weather for two separate windows:
    1. Pre-arrival (Today to Today + Lead Time - 1): Affects urgency/risk.
    2. Post-arrival (Today + Lead Time to Today + Lead Time + 7): Affects reorder quantity.
    """
    import datetime
    today = datetime.date.today()
    arrival_date = today + datetime.timedelta(days=lead_time)
    
    cat_rules = SENSITIVITY.get(category, {"high_temp": 1.0, "rain": 1.0})
    
    pre_multipliers = []
    post_multipliers = []
    
    forecast_days_available = len(forecast)
    confidence = "HIGH"
    fallback_used = False

    for i, day in enumerate(forecast):
        date_str = day.get("date", "")
        try:
            forecast_date = datetime.date.fromisoformat(date_str)
        except:
            continue
            
        temp = day.get("max_temp", 30)
        precip = day.get("precip", 0)
        
        # Calculate multiplier for this specific day
        day_mult = 1.0
        base_high_temp = cat_rules.get("high_temp", 1.0)
        
        if temp > 38 and base_high_temp > 1.0:
            day_mult = max(day_mult, base_high_temp * 1.1)
        elif temp > 34 and base_high_temp > 1.0:
            day_mult = max(day_mult, base_high_temp)
            
        if precip > 10:
            m = cat_rules.get("rain", 1.0)
            if m > 1.0: day_mult = max(day_mult, m)
            elif m < 1.0: day_mult = min(day_mult, m)

        # Assign to window
        days_from_today = (forecast_date - today).days
        if days_from_today < lead_time:
            pre_multipliers.append(day_mult)
        elif days_from_today < lead_time + 7:
            post_multipliers.append(day_mult)

    # Handle Forecast Limit Fallback
    # If the arrival period is beyond our forecast (7 days), we fallback to 1.0 (seasonal avg)
    if lead_time >= forecast_days_available:
        confidence = "LOW"
        fallback_used = True
        post_window_mult = 1.0 # Fallback to 1.0 (representing historical/seasonal average)
    else:
        # Use average for post-arrival window as requested
        post_window_mult = sum(post_multipliers) / len(post_multipliers) if post_multipliers else 1.0

    # Max for pre-arrival impact (used for urgency/risk)
    pre_window_mult = max(pre_multipliers) if pre_multipliers else 1.0

    return {
        "pre_arrival_multiplier": round(pre_window_mult, 2),
        "post_arrival_multiplier": round(post_window_mult, 2),
        "delivery_date": arrival_date.isoformat(),
        "lead_time": lead_time,
        "confidence": confidence,
        "fallback_used": fallback_used,
        "forecast_days_available": forecast_days_available,
        # For backward compatibility/logging
        "multiplier": round(post_window_mult, 2), 
        "reason": f"Analyzed post-arrival window ({arrival_date} + 7 days)"
    }
