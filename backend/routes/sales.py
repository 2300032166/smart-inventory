from fastapi import APIRouter, Depends, Query
import pandas as pd
import os
from datetime import datetime, timedelta, timezone

from middleware.auth_middleware import verify_token
from logic.pattern_detector import load_sales, analyse_sku, get_effective_today

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


@router.get("/trends")
def get_trends(
    sku: str = Query(...),
    days: int = Query(30),
    payload: dict = Depends(verify_token),
):
    df = load_sales()
    sku_df = df[df["StockCode"] == sku].copy()

    today = get_effective_today(df)
    cutoff = pd.Timestamp(today - timedelta(days=days))
    sku_df = sku_df[sku_df["InvoiceDate"] >= cutoff]

    daily = (
        sku_df.groupby(sku_df["InvoiceDate"].dt.date)["Quantity"]
        .sum()
        .reset_index()
    )
    daily.columns = ["date", "quantity"]
    daily["date"] = daily["date"].astype(str)

    weekly = (
        sku_df.groupby(sku_df["InvoiceDate"].dt.to_period("W"))["Quantity"]
        .sum()
        .reset_index()
    )
    weekly.columns = ["week", "quantity"]
    weekly["week"] = weekly["week"].astype(str)

    pattern = analyse_sku(sku, df)

    total = int(sku_df["Quantity"].sum())
    avg_daily = round(float(daily["quantity"].mean()), 2) if not daily.empty else 0
    peak_day = str(daily.loc[daily["quantity"].idxmax(), "date"]) if not daily.empty else None
    peak_qty = int(daily["quantity"].max()) if not daily.empty else 0

    return {
        "sku": sku,
        "daily_sales": daily.to_dict(orient="records"),
        "weekly_totals": weekly.to_dict(orient="records"),
        "pattern_dates": pattern.get("pattern_dates", []),
        "payday_spike": pattern.get("payday_spike", False),
        "declining_trend": pattern.get("declining_trend", False),
        "summary": {
            "total": total,
            "avg_daily_sales": avg_daily,
            "peak_day": peak_day,
            "peak_qty": peak_qty,
        },
    }


@router.get("/summary")
def get_summary(payload: dict = Depends(verify_token)):
    df = load_sales()
    products_csv = os.path.join(DATA_DIR, "products.csv")
    products = pd.read_csv(products_csv).fillna("").to_dict(orient="records")

    # Data 'today' for inventory analysis
    data_today = get_effective_today(df)
    
    # Real 'today' for tracking manager decisions/orders
    real_today = datetime.now(timezone.utc)
    real_week_start = real_today - timedelta(days=7)

    from logic.pattern_detector import analyse_sku
    from logic.reorder_calculator import calculate_reorder, load_ai_config, should_include_in_brief

    override_path = os.path.join(DATA_DIR, "override_history.json")
    import json

    # Decision metrics use real-time
    try:
        with open(override_path) as f:
            overrides = json.load(f)
    except Exception:
        overrides = []

    # Use a 48-hour window to be safe against server/client time drifts
    recent_limit = (real_today - timedelta(hours=48)).isoformat()
    decided_skus = {str(o.get("sku", "")).strip().upper() for o in overrides if o.get("timestamp", "") >= recent_limit}

    stockout_risk = 0
    cfg = load_ai_config()
    for p in products:
        sku = str(p.get("sku", "")).strip().upper()
        if sku in decided_skus:
            continue
            
        pattern = analyse_sku(p.get("sku"), df)
        reorder = calculate_reorder(p, pattern)
        
        # Match the filtering logic of the Daily Brief exactly
        if reorder["urgency"] == "urgent" and should_include_in_brief(reorder, cfg):
            stockout_risk += 1

    week_orders = [
        o for o in overrides
        if o.get("timestamp", "") >= real_week_start.isoformat()
        and o.get("decision") in ("approved", "overridden")
    ]

    approved = [o for o in overrides if o.get("decision") == "approved"]
    total_decided = len([o for o in overrides if o.get("decision") in ("approved", "overridden", "skipped")])
    accuracy = round(len(approved) / total_decided * 100) if total_decided > 0 else 0

    return {
        "stockout_risk": stockout_risk,
        "orders_this_week": len(week_orders),
        "ai_accuracy_pct": accuracy,
        "total_products": len(products),
        "total_sales_rows": len(df),
    }
