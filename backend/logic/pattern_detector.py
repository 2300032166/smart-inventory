import pandas as pd
import os
from datetime import datetime, timedelta

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


_SALES_CACHE = None
_SALES_MTIME = 0
_ANALYSIS_CACHE = {}

# Performance Cache for global velocity
_VELOCITY_CACHE = None 
_VELOCITY_MTIME = 0

def get_avg_sales_map() -> dict:
    global _VELOCITY_CACHE, _VELOCITY_MTIME
    path = os.path.join(DATA_DIR, "sales.csv")
    if not os.path.exists(path): return {}
    
    mtime = os.path.getmtime(path)
    if _VELOCITY_CACHE is not None and mtime == _VELOCITY_MTIME:
        return _VELOCITY_CACHE
        
    df = load_sales()
    recent_sales = df.groupby("StockCode")["Quantity"].sum().to_dict()
    # Assume 1 year of data for avg
    _VELOCITY_CACHE = {str(sku).strip().upper(): qty/365 for sku, qty in recent_sales.items()}
    _VELOCITY_MTIME = mtime
    return _VELOCITY_CACHE


def load_sales() -> pd.DataFrame:
    global _SALES_CACHE, _SALES_MTIME, _ANALYSIS_CACHE
    path = os.path.join(DATA_DIR, "sales.csv")
    
    if not os.path.exists(path):
        return pd.DataFrame(columns=["InvoiceDate", "StockCode", "Quantity"])
        
    try:
        current_mtime = os.path.getmtime(path)
    except OSError:
        return pd.DataFrame()

    if _SALES_CACHE is not None and current_mtime == _SALES_MTIME:
        return _SALES_CACHE

    # Optimize CSV loading
    df = pd.read_csv(path)
    
    if "InvoiceDate" not in df.columns:
        return pd.DataFrame(columns=["InvoiceDate", "StockCode", "Quantity"])
        
    # Fast date parsing
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], format="mixed", dayfirst=False)
    
    # Robust matching: pre-clean StockCode
    df["StockCode"] = df["StockCode"].astype(str).str.strip().str.upper()
    
    _SALES_CACHE = df
    _SALES_MTIME = current_mtime
    # Data changed, clear analysis results
    _ANALYSIS_CACHE.clear()
    return df


def get_effective_today(df: pd.DataFrame = None) -> datetime:
    """Return the actual current date for real-time analysis."""
    if df is not None and not df.empty and "InvoiceDate" in df.columns:
        return df["InvoiceDate"].max()
    return datetime.now()


def get_payday_dates():
    import json
    cfg_path = os.path.join(DATA_DIR, "ai_config.json")
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
        return cfg.get("payday_dates", [25, 26, 27])
    except Exception:
        return [25, 26, 27]


def _process_sku_group(sku: str, sku_df: pd.DataFrame, payday_days: list, today: datetime) -> dict:
    """Core pattern analysis logic for a single SKU's data."""
    if sku_df.empty:
        return {
            "sku": sku,
            "avg_daily_sales": 0,
            "std_dev_daily_sales": 0,
            "payday_avg_sales": 0,
            "payday_spike": False,
            "weekend_spike": False,
            "declining_trend": False,
            "pattern_dates": [],
        }

    cutoff_30 = pd.Timestamp(today - timedelta(days=30))
    recent = sku_df[sku_df["InvoiceDate"] >= cutoff_30]

    if recent.empty:
        recent = sku_df

    daily = recent.groupby(recent["InvoiceDate"].dt.date)["Quantity"].sum()
    avg_daily = float(daily.mean()) if not daily.empty else 0
    std_dev = float(daily.std()) if len(daily) > 1 else 0

    payday_mask = sku_df["InvoiceDate"].dt.day.isin(payday_days)
    payday_df = sku_df[payday_mask]
    if not payday_df.empty:
        payday_daily = payday_df.groupby(payday_df["InvoiceDate"].dt.date)["Quantity"].sum()
        payday_avg = float(payday_daily.mean())
    else:
        payday_avg = 0

    payday_spike = payday_avg > 1.3 * avg_daily if avg_daily > 0 else False

    # Weekend analysis
    weekend_mask = sku_df["InvoiceDate"].dt.weekday.isin([5, 6])
    weekend_df = sku_df[weekend_mask]
    if not weekend_df.empty:
        weekend_daily = weekend_df.groupby(weekend_df["InvoiceDate"].dt.date)["Quantity"].sum()
        weekend_avg = float(weekend_daily.mean())
    else:
        weekend_avg = 0
    weekend_spike = weekend_avg > 1.2 * avg_daily if avg_daily > 0 else False

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
    if weekend_spike:
        pct = round(((weekend_avg / avg_daily) - 1) * 100) if avg_daily > 0 else 0
        pattern_dates.append(f"Weekend spike detected (+{pct}%)")
    if declining_trend:
        pct = round(((prior_avg - last_avg) / prior_avg) * 100) if prior_avg > 0 else 0
        pattern_dates.append(f"Declining trend last 2 weeks (-{pct}%)")

    return {
        "sku": sku,
        "avg_daily_sales": round(avg_daily, 2),
        "std_dev_daily_sales": round(std_dev, 2),
        "payday_avg_sales": round(payday_avg, 2),
        "payday_spike": payday_spike,
        "weekend_spike": weekend_spike,
        "declining_trend": declining_trend,
        "pattern_dates": pattern_dates,
    }


def analyse_sku(sku: str, df: pd.DataFrame = None) -> dict:
    global _ANALYSIS_CACHE
    
    sku_target = str(sku).strip().upper()
    if sku_target in _ANALYSIS_CACHE:
        return _ANALYSIS_CACHE[sku_target]

    if df is None:
        df = load_sales()
    
    sku_df = df[df["StockCode"] == sku_target].copy()
    
    today = get_effective_today(df)
    payday_days = get_payday_dates()
    
    result = _process_sku_group(sku_target, sku_df, payday_days, today)
    _ANALYSIS_CACHE[sku_target] = result
    return result


def analyse_all_skus() -> dict:
    """Optimized analysis using fully vectorized operations."""
    global _ANALYSIS_CACHE
    df = load_sales()
    
    # If cache is already hot and matches full SKU list, return it
    if _ANALYSIS_CACHE:
        return _ANALYSIS_CACHE

    if df.empty:
        return {}

    today = get_effective_today(df)
    payday_days = get_payday_dates()
    
    print(f"Running optimized batch analysis for {df['StockCode'].nunique()} SKUs..")

    cutoff_30 = pd.Timestamp(today - timedelta(days=30))
    cutoff_14 = pd.Timestamp(today - timedelta(days=14))
    cutoff_7 = pd.Timestamp(today - timedelta(days=7))

    # Add useful date components
    df['date'] = df['InvoiceDate'].dt.date
    df['day'] = df['InvoiceDate'].dt.day
    df['weekday'] = df['InvoiceDate'].dt.weekday

    # 1. Base recent (30 days) daily sales
    recent_mask = df["InvoiceDate"] >= cutoff_30
    recent = df[recent_mask]
    
    # Fallback to overall for items not sold recently
    not_recent_skus = set(df['StockCode']) - set(recent['StockCode'])
    if not_recent_skus:
        fallback = df[df['StockCode'].isin(not_recent_skus)]
        recent = pd.concat([recent, fallback])

    if recent.empty:
        return {}

    daily_sum = recent.groupby(['StockCode', 'date'])['Quantity'].sum()
    avg_daily = daily_sum.groupby('StockCode').mean()
    std_dev = daily_sum.groupby('StockCode').std().fillna(0)

    # 2. Payday sales
    payday_mask = df["day"].isin(payday_days)
    payday_daily_sum = df[payday_mask].groupby(['StockCode', 'date'])['Quantity'].sum()
    payday_avg = payday_daily_sum.groupby('StockCode').mean()

    # 3. Weekend sales
    weekend_mask = df["weekday"].isin([5, 6])
    weekend_daily_sum = df[weekend_mask].groupby(['StockCode', 'date'])['Quantity'].sum()
    weekend_avg = weekend_daily_sum.groupby('StockCode').mean()

    # 4. Trend analysis (14-day vs 7-day)
    prior_mask = (df["InvoiceDate"] >= cutoff_14) & (df["InvoiceDate"] < cutoff_7)
    prior_daily_sum = df[prior_mask].groupby(['StockCode', 'date'])['Quantity'].sum()
    prior_avg = prior_daily_sum.groupby('StockCode').mean()

    last_mask = df["InvoiceDate"] >= cutoff_7
    last_daily_sum = df[last_mask].groupby(['StockCode', 'date'])['Quantity'].sum()
    last_avg = last_daily_sum.groupby('StockCode').mean()

    # Align all series to the complete set of SKUs
    skus = df['StockCode'].unique()
    
    avg_daily = avg_daily.reindex(skus, fill_value=0)
    std_dev = std_dev.reindex(skus, fill_value=0)
    payday_avg = payday_avg.reindex(skus, fill_value=0)
    weekend_avg = weekend_avg.reindex(skus, fill_value=0)
    prior_avg = prior_avg.reindex(skus, fill_value=0)
    last_avg = last_avg.reindex(skus, fill_value=0)

    # Boolean flags
    payday_spike = (payday_avg > 1.3 * avg_daily) & (avg_daily > 0)
    weekend_spike = (weekend_avg > 1.2 * avg_daily) & (avg_daily > 0)
    declining_trend = (prior_avg > 0) & (last_avg < prior_avg * 0.85)

    results = {}
    payday_days_str = ','.join(map(str, payday_days))

    for sku in skus:
        ad = float(avg_daily[sku])
        pd_avg = float(payday_avg[sku])
        wk_avg = float(weekend_avg[sku])
        pr_avg = float(prior_avg[sku])
        lst_avg = float(last_avg[sku])
        
        pd_spike = bool(payday_spike[sku])
        wk_spike = bool(weekend_spike[sku])
        dec_trend = bool(declining_trend[sku])
        
        pattern_dates = []
        if pd_spike:
            pct = round(((pd_avg / ad) - 1) * 100) if ad > 0 else 0
            pattern_dates.append(f"Payday spike detected: days {payday_days_str} (+{pct}%)")
        if wk_spike:
            pct = round(((wk_avg / ad) - 1) * 100) if ad > 0 else 0
            pattern_dates.append(f"Weekend spike detected (+{pct}%)")
        if dec_trend:
            pct = round(((pr_avg - lst_avg) / pr_avg) * 100) if pr_avg > 0 else 0
            pattern_dates.append(f"Declining trend last 2 weeks (-{pct}%)")

        results[sku] = {
            "sku": sku,
            "avg_daily_sales": round(ad, 2),
            "std_dev_daily_sales": round(float(std_dev[sku]), 2),
            "payday_avg_sales": round(pd_avg, 2),
            "payday_spike": pd_spike,
            "weekend_spike": wk_spike,
            "declining_trend": dec_trend,
            "pattern_dates": pattern_dates,
        }
    
    _ANALYSIS_CACHE = results
    return results


def load_products_dynamic() -> list:
    """Load products and dynamically adjust current_stock based on non-expired batches."""
    products_csv = os.path.join(DATA_DIR, "products.csv")
    batches_csv = os.path.join(DATA_DIR, "inventory_batches.csv")
    
    if not os.path.exists(products_csv):
        return []
        
    df = pd.read_csv(products_csv)
    
    if os.path.exists(batches_csv):
        try:
            bdf = pd.read_csv(batches_csv)
            if not bdf.empty:
                bdf['expiry_date_dt'] = pd.to_datetime(bdf['expiry_date'], errors='coerce')
                today_dt = pd.to_datetime(datetime.now().date())
                
                # Active (non-expired) batches condition:
                # status is 'active' AND (expiry_date_dt > today_dt or missing expiry date) AND quantity > 0
                active_batches = bdf[
                    (bdf['status'] == 'active') & 
                    (bdf['quantity'] > 0) & 
                    ((bdf['expiry_date_dt'] > today_dt) | bdf['expiry_date_dt'].isna())
                ]
                
                # List of SKUs that have ANY batch (active or expired) in inventory_batches.csv
                skus_with_batches = set(bdf['sku'].astype(str).str.strip().str.upper())
                
                # Sum active stock per SKU (normalise SKU case for lookup)
                sku_stock_map = active_batches.groupby(
                    active_batches['sku'].astype(str).str.strip().str.upper()
                )['quantity'].sum().to_dict()

                # Apply map dynamically
                products_list = df.fillna("").to_dict(orient="records")
                for p in products_list:
                    sku_upper = str(p['sku']).strip().upper()
                    if sku_upper in skus_with_batches:
                        p['current_stock'] = float(sku_stock_map.get(sku_upper, 0.0))
                return products_list
        except Exception as e:
            # Fall back to default products list
            pass
            
    return df.fillna("").to_dict(orient="records")

