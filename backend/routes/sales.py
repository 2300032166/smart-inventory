from fastapi import APIRouter, Depends, Query
import pandas as pd
import os
from datetime import datetime, timedelta

from middleware.auth_middleware import verify_token
from logic.pattern_detector import load_sales, analyse_sku

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

    today = datetime.now().date()
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

    today = datetime.now().date()
    week_start = pd.Timestamp(today - timedelta(days=7))
    week_df = df[df["InvoiceDate"] >= week_start]

    from logic.pattern_detector import analyse_sku
    from logic.reorder_calculator import calculate_reorder

    stockout_risk = 0
    for p in products:
        pattern = analyse_sku(p["sku"], df)
        reorder = calculate_reorder(p, pattern)
        if reorder["urgency"] == "urgent":
            stockout_risk += 1

    override_path = os.path.join(DATA_DIR, "override_history.json")
    import json
    try:
        with open(override_path) as f:
            overrides = json.load(f)
    except Exception:
        overrides = []

    week_orders = [
        o for o in overrides
        if o.get("timestamp", "") >= week_start.isoformat()
        and o.get("decision") in ("approved", "overridden")
    ]

    approved = [o for o in overrides if o.get("decision") == "approved"]
    total_decided = len([o for o in overrides if o.get("decision") in ("approved", "overridden", "skipped")])
    accuracy = round(len(approved) / total_decided * 100) if total_decided > 0 else 0

    pending = len(products) - len([o for o in overrides if o.get("timestamp", "")[:10] == today.isoformat()])

    return {
        "pending_review": max(0, pending),
        "stockout_risk": stockout_risk,
        "orders_this_week": len(week_orders),
        "ai_accuracy_pct": accuracy,
        "total_products": len(products),
        "total_sales_rows": len(df),
    }
