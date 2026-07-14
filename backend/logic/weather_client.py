import httpx
import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "weather_cache.json")
# Vijayawada, Andhra Pradesh, India
LAT = 16.5062
LON = 80.6480

async def fetch_weather_forecast():
    """Fetch 7-day forecast from Open-Meteo for Vijayawada."""
    
    # Check cache first
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE) as f:
                cache = json.load(f)
                cached_time = datetime.fromisoformat(cache.get("timestamp"))
                if datetime.now() - cached_time < timedelta(hours=3):
                    logger.info("[Weather] Returning cached forecast")
                    return cache.get("forecast")
    except Exception as e:
        logger.warning("[Weather] Cache read error: %s", e)

    url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode&timezone=auto"
    
    try:
        logger.info("[Weather] Fetching fresh forecast for Vijayawada...")
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            
            # Simple structure for easier consumption
            daily = data.get("daily", {})
            forecast = []
            for i in range(len(daily.get("time", []))):
                forecast.append({
                    "date": daily["time"][i],
                    "max_temp": daily["temperature_2m_max"][i],
                    "min_temp": daily["temperature_2m_min"][i],
                    "precip": daily["precipitation_sum"][i],
                    "code": daily["weathercode"][i]
                })
            
            # Save to cache
            with open(CACHE_FILE, "w") as f:
                json.dump({
                    "timestamp": datetime.now().isoformat(),
                    "forecast": forecast
                }, f, indent=2)
            
            return forecast
    except Exception as e:
        logger.error("[Weather] API Error: %s", e)
        # Fallback to local data if available or empty list
        return []
