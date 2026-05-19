import pandas as pd
import os
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


def load_sales() -> pd.DataFrame:
    path = os.path.join(DATA_DIR, "sales.csv")
    df = pd.read_csv(path)
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    return df


def get_payday_dates():
    import json
    cfg_path = os.path.join(DATA_DIR, "ai_config.json")
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
        return cfg.get("payday_dates", [25, 26, 27])
    except Exception:
        return [25, 26, 27]


def analyse_sku(sku: str, df: pd.DataFrame = None) -> dict:
    if df is None:
        df = load_sales()

    sku_df = df[df["StockCode"] == sku].copy()
    if sku_df.empty:
        return {
            "sku": sku,
            "avg_daily_sales": 0,
            "std_dev_daily_sales": 0,
            "payday_avg_sales": 0,
            "payday_spike": False,
            "declining_trend": False,
            "pattern_dates": [],
        }

    today = datetime.now().date()
    cutoff_30 = pd.Timestamp(today - timedelta(days=30))
    recent = sku_df[sku_df["InvoiceDate"] >= cutoff_30]

    if recent.empty:
        recent = sku_df

    daily = recent.groupby(recent["InvoiceDate"].dt.date)["Quantity"].sum()
    avg_daily = float(daily.mean()) if not daily.empty else 0
    std_dev = float(daily.std()) if len(daily) > 1 else 0

    payday_days = get_payday_dates()
    payday_mask = sku_df["InvoiceDate"].dt.day.isin(payday_days)
    payday_df = sku_df[payday_mask]
    if not payday_df.empty:
        payday_daily = payday_df.groupby(payday_df["InvoiceDate"].dt.date)["Quantity"].sum()
        payday_avg = float(payday_daily.mean())
    else:
        payday_avg = 0

    payday_spike = payday_avg > 1.5 * avg_daily if avg_daily > 0 else False

    cutoff_14 = pd.Timestamp(today - timedelta(days=14))
    cutoff_7 = pd.Timestamp(today - timedelta(days=7))
    prior_period = sku_df[(sku_df["InvoiceDate"] >= cutoff_14) & (sku_df["InvoiceDate"] < cutoff_7)]
    last_period = sku_df[sku_df["InvoiceDate"] >= cutoff_7]

    prior_avg = float(prior_period.groupby(prior_period["InvoiceDate"].dt.date)["Quantity"].sum().mean()) if not prior_period.empty else 0
    last_avg = float(last_period.groupby(last_period["InvoiceDate"].dt.date)["Quantity"].sum().mean()) if not last_period.empty else 0

    declining_trend = (prior_avg > 0) and (last_avg < prior_avg * 0.85)

    pattern_dates = []
    if payday_spike:
        pct = round(((payday_avg / avg_daily) - 1) * 100) if avg_daily > 0 else 0
        pattern_dates.append(f"Payday spike detected: days {','.join(map(str, payday_days))} (+{pct}%)")
    if declining_trend:
        pct = round(((prior_avg - last_avg) / prior_avg) * 100) if prior_avg > 0 else 0
        pattern_dates.append(f"Declining trend last 2 weeks (-{pct}%)")

    return {
        "sku": sku,
        "avg_daily_sales": round(avg_daily, 2),
        "std_dev_daily_sales": round(std_dev, 2),
        "payday_avg_sales": round(payday_avg, 2),
        "payday_spike": payday_spike,
        "declining_trend": declining_trend,
        "pattern_dates": pattern_dates,
    }


def analyse_all_skus() -> dict:
    df = load_sales()
    skus = df["StockCode"].unique()
    results = {}
    for sku in skus:
        results[sku] = analyse_sku(sku, df)
    return results
