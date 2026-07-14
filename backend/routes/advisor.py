from fastapi import APIRouter, Depends, Query, HTTPException, BackgroundTasks
import pandas as pd
import json, os, logging, asyncio
from datetime import datetime, timezone

from middleware.auth_middleware import require_manager_or_admin
from logic.pattern_detector import load_sales, analyse_sku
from .inventory import load_products, enrich_product, get_incoming_stock
from .suppliers import recommend_for_sku, supplier_data_snapshot
from logic.reorder_calculator import calculate_reorder, should_include_in_brief, load_ai_config
from logic.prompt_builder import build_prompt
from logic.ai_client import generate_reasoning, AI_FAIL_MSG
from logic.weather_client import fetch_weather_forecast
from logic.weather_analyzer import analyze_weather_for_windows
from .alerts import create_alert

logger = logging.getLogger(__name__)

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
BRIEF_LOG = os.path.join(DATA_DIR, "brief_log.json")
OVERRIDE_FILE = os.path.join(DATA_DIR, "override_history.json")


def _select_ai_candidates(candidates: list, cfg: dict) -> list:
    """Pick the AI batch for the brief. For this flow we prefer the full brief set so most items get an AI attempt unless the provider limit is reached."""
    requested = int(cfg.get("max_ai_items", len(candidates)))
    max_ai_items = max(1, min(len(candidates), requested))
    if len(candidates) <= max_ai_items:
        return candidates

    return sorted(
        candidates,
        key=lambda item: (
            0 if item[2].get("urgency") == "urgent" else 1,
            item[2].get("days_remaining", 9999),
            -float(item[2].get("confidence_score", 0)),
        ),
    )[:max_ai_items]


def load_products():
    from .inventory import load_products as load_inventory_products
    products_list = load_inventory_products()
    df = pd.DataFrame(products_list).fillna("")
    # Aggregate batches to SKU level for brief logic
    # We take the earliest expiry date across all batches for risk assessment
    agg_dict = {
        "name": "first",
        "category": "first",
        "current_stock": "sum",
        "unit": "first",
        "unit_price": "first",
        "lead_time_days": "first",
        "supplier_name": "first",
    }
    # expiry_date lives in inventory_batches.csv now; only aggregate if present
    if "expiry_date" in df.columns:
        agg_dict["expiry_date"] = "min"
    sku_agg = df.groupby("sku").agg(agg_dict).reset_index()
    return sku_agg.to_dict(orient="records")


def load_brief_log() -> dict:
    try:
        with open(BRIEF_LOG) as f:
            return json.load(f)
    except Exception:
        return {}


def save_brief_log(log: dict):
    with open(BRIEF_LOG, "w") as f:
        json.dump(log, f, indent=2)


def load_overrides() -> list:
    try:
        with open(OVERRIDE_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def get_decided_skus(hours: int = 48) -> set:
    """Return the set of SKUs that have a manager decision within the last X hours,
    excluding those where the latest decision is 'cancelled'."""
    overrides = load_overrides()
    from datetime import datetime, timedelta, timezone
    limit = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    
    # Track the latest decision for each SKU within the time window
    latest_decisions = {}
    for o in overrides:
        # Check both original timestamp and last_updated for the time window
        ts = o.get("timestamp", "")
        upd = o.get("last_updated", "")
        relevant_ts = max(ts, upd)
        
        if relevant_ts >= limit:
            sku = str(o.get("sku", "")).strip().upper()
            # Keep the one with the most recent activity
            if sku not in latest_decisions or relevant_ts > max(latest_decisions[sku].get("timestamp", ""), latest_decisions[sku].get("last_updated", "")):
                latest_decisions[sku] = o
                
    # A SKU is "decided" only if its most recent state is NOT cancelled
    return {sku for sku, record in latest_decisions.items() if record.get("status") != "cancelled"}


@router.get("/today")
async def get_today_brief(
    background_tasks: BackgroundTasks,
    force: bool = Query(False),
    payload: dict = Depends(require_manager_or_admin())
):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cfg = load_ai_config()
    log = load_brief_log()
    
    # Check if CSV files have been modified since the brief was saved
    products_csv = os.path.join(DATA_DIR, "products.csv")
    sales_csv = os.path.join(DATA_DIR, "sales.csv")
    try:
        csv_mtime = max(os.path.getmtime(products_csv), os.path.getmtime(sales_csv))
    except OSError as e:
        logger.error("[Brief] Could not read CSV file timestamps: %s", e)
        # If data files are missing, return cached brief if available, else 500
        if today in log and log[today].get("items"):
            logger.warning("[Brief] Data files missing — returning cached brief for today.")
            return log[today]["items"]
        raise HTTPException(status_code=500, detail="Inventory data files are not available. Please check the deployment data volume.")

    if not force and today in log:
        # Only return cached brief if it was created AFTER the last CSV change
        if log[today].get("mtime", 0) >= csv_mtime:
            return log[today]["items"]

    try:
        products = load_products()
        sales_df = load_sales()
    except Exception as e:
        logger.error("[Brief] Failed to load product/sales data: %s", e)
        if today in log and log[today].get("items"):
            logger.warning("[Brief] Data load failed — returning cached brief for today.")
            return log[today]["items"]
        raise HTTPException(status_code=500, detail=f"Failed to load inventory data: {e}")
    
    # OPTIMIZATION: Pre-calculate sales stats for all SKUs to avoid O(N^2) filtering
    print(f"Optimizing brief for {len(products)} products...")
    # Robust SKU keys: string, stripped, upper
    sales_df["StockCode"] = sales_df["StockCode"].astype(str).str.strip().str.upper()
    recent_sales = sales_df.groupby("StockCode")["Quantity"].sum().to_dict()
    # Estimate avg daily sales over 365 days
    avg_sales_map = {str(sku): qty/365 for sku, qty in recent_sales.items()}
    # Fetch patterns for all products to avoid O(N^2) loops
    from logic.pattern_detector import analyse_all_skus
    all_patterns = analyse_all_skus()

    # NEW: Fetch weather forecast for Vijayawada
    forecast = await fetch_weather_forecast()

    # Supplier data is loaded once per brief generation and reused for recommendations.
    supplier_data = supplier_data_snapshot()

    # OPTIMIZATION: Build incoming stock map once to avoid 2510x file reads inside the loop.
    # Mirrors the exact logic from get_incoming_stock() but vectorised.
    from .orders import load_overrides as _load_overrides
    incoming_stock_map: dict = {}
    try:
        for o in _load_overrides():
            if o.get("status") in ("approved", "ordered") and not o.get("po_id"):
                _sku = str(o.get("sku", "")).strip().upper()
                if _sku:
                    incoming_stock_map[_sku] = incoming_stock_map.get(_sku, 0.0) + float(o.get("actual_qty", 0))
        _po_csv = os.path.join(DATA_DIR, "purchase_orders.csv")
        if os.path.exists(_po_csv):
            import pandas as _pd
            _po_df = _pd.read_csv(_po_csv).fillna("")
            _po_pending = _po_df[_po_df["status"].astype(str).str.strip().str.lower().isin(["ordered", "approved"])]
            for _, _row in _po_pending.iterrows():
                _sku = str(_row.get("sku", "")).strip().upper()
                if _sku:
                    incoming_stock_map[_sku] = incoming_stock_map.get(_sku, 0.0) + float(_row.get("ordered_qty", 0) or 0)
    except Exception as _e:
        logger.warning("[Brief] Could not pre-build incoming_stock_map: %s", _e)

    # OPTIMIZATION: Cache weather impacts by (category, lead_time) — most products share
    # the same category/lead-time pair, so we compute only the unique combos.
    _weather_cache: dict = {}

    def _get_weather_impact(category: str, lead_time: int) -> dict:
        key = (category, lead_time)
        if key not in _weather_cache:
            _weather_cache[key] = analyze_weather_for_windows(forecast, category, lead_time)
        return _weather_cache[key]

    candidates = []
    for p in products:
        sku_clean = str(p.get("sku", "")).strip().upper()
        # Use pre-built map — no disk I/O per SKU
        incoming = incoming_stock_map.get(sku_clean, 0.0)

        # Create a modified product dict for recommendation logic
        p_effective = p.copy()
        physical_stock = float(p.get("current_stock", 0))
        p_effective["current_stock"] = physical_stock + incoming

        # Use real pattern data
        pattern = all_patterns.get(sku_clean, {
            "avg_daily_sales": avg_sales_map.get(sku_clean, 0),
            "payday_spike": False,
            "weekend_spike": False,
            "confidence": 0.5
        })

        # Cached weather impact — no repeated computation for same category+lead_time
        lead_time = int(p.get("lead_time_days", 7))
        impact = _get_weather_impact(p.get("category", ""), lead_time)

        # MODIFIED: Pass windowed weather impact to reorder calculation
        reorder = calculate_reorder(p_effective, pattern, impact)

        if should_include_in_brief(reorder, cfg):
            candidates.append((p, pattern, reorder, impact, physical_stock, incoming))


    # 1. Urgent items first, then Normal
    # 2. Within those, smallest days_remaining (closest to zero) first
    candidates.sort(key=lambda x: (
        0 if x[2]["urgency"] == "urgent" else (1 if x[2]["urgency"] == "normal" else 2),
        x[2]["days_remaining"]
    ))

    # Use ai_config's max_brief_items (default 100). No hard cap — all stockout items shown.
    max_brief_limit = int(cfg.get("max_brief_items", 100))
    candidates = candidates[:max_brief_limit]
    ai_candidates = _select_ai_candidates(candidates, cfg)

    results = []
    for (p, pattern, reorder, impact, physical_stock, incoming) in candidates:
        drivers = reorder.get("drivers", {})
        fallback_reasoning = (
            drivers.get("natural_explanation", "")
            or f"{p['name']} stock requires attention. Order {reorder['recommended_qty']} {p.get('unit', 'units')} to maintain availability."
        )

        sku_clean = str(p.get("sku", "")).strip().upper()
        supplier_rec = recommend_for_sku(sku_clean, data=supplier_data)
        rec_supplier = supplier_rec.get("recommended")
        mapped_suppliers = [
            {
                "supplier_id": s.get("supplier_id"),
                "name": s.get("name", ""),
                "reliability_score": s.get("reliability_score", 0),
                "default_lead_time_days": s.get("default_lead_time_days", 7),
                "rank": s.get("rank", 1),
                "reasons": s.get("reasons", []),
            }
            for s in supplier_rec.get("all_suppliers", [])
        ]


        results.append({
            "sku": p["sku"],
            "product_name": p["name"],
            "category": p.get("category", ""),
            "current_stock": p["current_stock"],
            "physical_stock": physical_stock,
            "incoming_stock": incoming,
            "effective_stock": physical_stock + incoming,
            "unit": p.get("unit", "units"),
            "avg_daily_sales": round(float(pattern["avg_daily_sales"]), 2),
            "days_remaining": reorder["days_remaining"],
            "lead_time_days": int(p.get("lead_time_days", 7)),
            "recommended_qty": reorder["recommended_qty"],
            "urgency": reorder["urgency"],
            "risk_level": reorder.get("risk_level", "NORMAL"),
            "ai_reasoning": fallback_reasoning,
            "ai_status": "loading",
            "confidence_score": reorder["confidence_score"],
            "weather_confidence": reorder.get("weather_confidence", "HIGH"),
            "delivery_date": reorder.get("delivery_date"),
            "pre_arrival_multiplier": reorder.get("pre_arrival_multiplier"),
            "post_arrival_multiplier": reorder.get("post_arrival_multiplier"),
            "payday_spike": pattern["payday_spike"],
            "declining_trend": pattern["declining_trend"],
            "weather_reason": impact.get("reason"),
            "weather_code": impact.get("peak_code"),
            "weather_temp": impact.get("peak_temp"),
            "order_by_date": reorder.get("order_by_date"),
            "drivers": drivers,
            "recommended_supplier_id": rec_supplier.get("supplier_id") if rec_supplier else "",
            "recommended_supplier_name": rec_supplier.get("name", "") if rec_supplier else "",
            "mapped_suppliers": mapped_suppliers,
        })

        if reorder.get("risk_level") == "CRITICAL_STOCKOUT":
            create_alert(
                user_id="all",
                alert_type="stockout",
                title=f"Critical Stockout: {p['name']}",
                message=f"Stock for {p['name']} will run out in {reorder['days_remaining']} days. Order suggested: {reorder['recommended_qty']} {p.get('unit', 'units')}."
            )

    ref_mtime = datetime.now(timezone.utc).timestamp()
    log[today] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mtime": ref_mtime,
        "items": results,
    }
    save_brief_log(log)
    
    # ── Background AI reasoning with semaphore ───────────────────────────────
    # We schedule a background task to process AI completions and update the JSON log file.
    
    # Build a per-SKU fallback map NOW (before the loop variable changes)
    fallback_map = {}
    for (p, pattern, reorder, impact, physical_stock, incoming) in ai_candidates:
        drivers = reorder.get("drivers", {})
        fallback_map[p["sku"]] = (
            drivers.get("natural_explanation", "")
            or f"{p['name']} stock requires attention. Order {reorder['recommended_qty']} {p.get('unit', 'units')} to maintain availability."
        )

    async def _background_run_ai():
        from logic.groq_key_manager import key_manager
        # Scale concurrency with the number of configured Groq keys so extra
        # backup keys actually speed up the brief instead of sitting idle.
        concurrency = int(cfg.get("groq_concurrency", 4)) * max(1, key_manager.key_count)
        sem = asyncio.Semaphore(max(4, concurrency))
        _file_lock = asyncio.Lock()  # Serialise concurrent writes to brief_log.json

        # generate_reasoning() may retry across multiple backup keys internally
        # (each attempt bounded by groq_timeout_seconds, default 4s). Give the
        # outer watchdog enough room for a couple of those rounds instead of
        # cutting off a retry that a backup key would have won.
        per_item_timeout = max(6.0, float(cfg.get("groq_timeout_seconds", 4)) * 2 * max(1, key_manager.key_count) + 2)

        async def _get_and_persist_reasoning(p, pattern, reorder, impact, sku_fallback):
            """Fetch AI reasoning for one SKU and immediately persist it to the log."""
            sku = p["sku"]
            prompt = build_prompt(p, pattern, reorder, impact)
            async with sem:
                try:
                    reasoning = await asyncio.wait_for(generate_reasoning(prompt), timeout=per_item_timeout)
                except Exception as exc:
                    logger.warning("[Brief] generate_reasoning failed/timed-out for SKU=%s: %s", sku, exc)
                    reasoning = AI_FAIL_MSG

            if not reasoning or "failed" in reasoning.lower() or reasoning == AI_FAIL_MSG:
                reasoning = sku_fallback

            # ── Write this single SKU's result immediately ─────────────────
            async with _file_lock:
                try:
                    current_log = load_brief_log()
                    stored_mtime = current_log.get(today, {}).get("mtime", 0)
                    if today in current_log and abs(stored_mtime - ref_mtime) < 1.0:
                        for item in current_log[today]["items"]:
                            if item["sku"] == sku:
                                item["ai_reasoning"] = reasoning
                                item["ai_status"] = "complete"
                                break
                        save_brief_log(current_log)
                        logger.debug("[Brief] Persisted AI result for SKU=%s", sku)
                    else:
                        logger.warning("[Brief] mtime mismatch for SKU=%s — skipping write", sku)
                except Exception as exc:
                    logger.error("[Brief] Failed to persist result for SKU=%s: %s", sku, exc)

            return sku, reasoning

        # Launch all tasks concurrently — each one writes its own result as soon as it is ready.
        tasks = [
            _get_and_persist_reasoning(p, pattern, reorder, impact, fallback_map.get(p["sku"], ""))
            for (p, pattern, reorder, impact, physical_stock, incoming) in ai_candidates
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # Log any top-level task exceptions (should be rare)
        completed = 0
        for sku_idx, result in enumerate(raw_results):
            if isinstance(result, Exception):
                sku = ai_candidates[sku_idx][0]["sku"]
                logger.error("[Brief] Task exception for SKU=%s: %s", sku, result)
                # Ensure this SKU is still marked complete in the log
                async with _file_lock:
                    try:
                        current_log = load_brief_log()
                        if today in current_log:
                            for item in current_log[today]["items"]:
                                if item["sku"] == sku and item.get("ai_status") == "loading":
                                    item["ai_reasoning"] = fallback_map.get(sku, item["ai_reasoning"])
                                    item["ai_status"] = "complete"
                                    break
                            save_brief_log(current_log)
                    except Exception:
                        pass
            else:
                completed += 1

        logger.info("[Brief] Background AI reasoning complete. %d/%d items succeeded.", completed, len(tasks))

    background_tasks.add_task(_background_run_ai)

    return results


@router.get("/pending")
async def get_pending_brief(
    background_tasks: BackgroundTasks,
    force: bool = Query(False),
    payload: dict = Depends(require_manager_or_admin())
):
    """Return today's brief items that have NOT yet been decided by the manager."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cfg = load_ai_config()
    cache_hours = int(cfg.get("brief_cache_hours", 6))

    # Get today's full brief first
    log = load_brief_log()
    entry = log.get(today)

    force_refresh = force
    if entry and not force_refresh:
        # Check if cache is expired
        try:
            gen_at = datetime.fromisoformat(entry["generated_at"])
            age_hours = (datetime.now(timezone.utc) - gen_at).total_seconds() / 3600
            if age_hours > cache_hours:
                logger.info("[Brief] Cache expired (age=%.1fh, limit=%dh). Regenerating.", age_hours, cache_hours)
                force_refresh = True
        except Exception:
            force_refresh = True

    if not entry or force_refresh:
        # Re-trigger generating today's brief
        all_items = await get_today_brief(background_tasks=background_tasks, force=force_refresh, payload=payload)
    else:
        all_items = entry.get("items", [])

    # Filter out SKUs that the manager has already decided on recently (48h)
    decided_skus = get_decided_skus(48)
    pending = [item for item in all_items if str(item.get("sku", "")).strip().upper() not in decided_skus]

    logger.info(
        "[Pending] today=%s total=%d decided=%d pending=%d",
        today, len(all_items), len(decided_skus), len(pending),
    )
    return pending


@router.get("/history")
def get_brief_history(
    date: str = Query(...),
    payload: dict = Depends(require_manager_or_admin()),
):
    """Return brief items for a specific date that were NOT decided on."""
    log = load_brief_log()
    entry = log.get(date)
    if not entry:
        raise HTTPException(status_code=404, detail=f"No brief found for date {date}")

    all_items = entry.get("items", [])
    # For history, we just show what was in the brief regardless of recent decisions
    # OR we can keep the filter if we only want "truly" pending items for that date.
    # The requirement is specifically about the dashboard mismatch, so let's keep it simple.
    decided_skus = get_decided_skus(48)
    pending = [item for item in all_items if str(item.get("sku", "")).strip().upper() not in decided_skus]

    logger.info("[Brief History] date=%s total=%d pending=%d", date, len(all_items), len(pending))
    return pending
