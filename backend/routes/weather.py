from fastapi import APIRouter, Depends
from middleware.auth_middleware import require_manager_or_admin
from logic.weather_client import fetch_weather_forecast
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/forecast")
async def get_weather_forecast(payload: dict = Depends(require_manager_or_admin())):
    """
    Returns the 7-day weather forecast for Vijayawada.
    Used by the frontend dashboard.
    """
    forecast = await fetch_weather_forecast()
    return forecast
