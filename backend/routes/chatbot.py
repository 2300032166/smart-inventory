from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import os, json, logging, asyncio, datetime, time
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

from middleware.auth_middleware import require_any_role
from .dead_stock import get_analysis_data
from logic.chatbot_data import data_manager
from logic.intent_router import intent_router

logger = logging.getLogger(__name__)

router = APIRouter()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# ── Data & Metrics Helpers ───────────────────────────────────────────────────

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="chatbot-io")

def _get_sales_summary() -> str:
    """Uses cached in-memory sales data to generate a summary."""
    df = data_manager.sales_df
    if df is None or df.empty:
        return "Sales data not available."

    try:
        max_date = df["InvoiceDate"].max()
        def _top(days):
            cutoff = max_date - datetime.timedelta(days=days)
            subset = df[df["InvoiceDate"] >= cutoff]
            top = subset.groupby("Description")["Quantity"].sum().sort_values(ascending=False).head(5)
            return ", ".join([f"{n} ({int(q)})" for n, q in top.items()]) if not top.empty else "No data"

        s7, s30, s90 = _top(7), _top(30), _top(90)
        yesterday_date = (max_date - datetime.timedelta(days=1)).date()
        y_sub = df[df["InvoiceDate"].dt.date == yesterday_date]
        if not y_sub.empty:
            y_top = y_sub.groupby("Description")["Quantity"].sum().sort_values(ascending=False).head(5)
            s_yesterday = ", ".join([f"{n} ({int(q)})" for n, q in y_top.items()])
        else:
            s_yesterday = "No data"

        summary = (
            f"- YESTERDAY ({yesterday_date}): {s_yesterday}\n"
            f"- LAST 7 DAYS: {s7}\n"
            f"- LAST 30 DAYS: {s30}\n"
            f"- LAST 90 DAYS: {s90}\n"
        )
        return summary
    except Exception as e:
        logger.error(f"[Chatbot] Sales summary failed: {e}")
        return "Error calculating sales trends."

# ── Groq chatbot client ──
from logic.chatbot_groq import ChatbotGroqClient
groq_client = ChatbotGroqClient()

async def stream_chatbot_groq(messages):
    """Streams response from Groq with token-by-token updates."""
    try:
        async for chunk in groq_client.stream_chat(messages):
            yield f"data: {json.dumps({'content': chunk})}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as e:
        logger.error("[Chatbot] Groq stream error: %s", e)
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

# ── Route Models ─────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage]

def _has_write_intent(text: str) -> bool:
    """Regex to block mutation requests."""
    pats = [
        r"(delete|remove|clear|wipe|erase)\s+(product|stock|inventory|order|record|supplier|discount)",
        r"(add|create|new|insert|post)\s+(product|stock|inventory|order|record|supplier|discount)",
        r"(update|edit|modify|change|set|reset)\s+(stock|price|threshold|quantity|status|supplier|product)",
        r"(place|cancel|approve|reject)\s+(order|purchase|discount|recommendation)",
    ]
    return any(re.search(p, text.lower()) for p in pats)

import re

def gather_live_context() -> str:
    """Build a comprehensive inventory context string using cached in-memory data."""
    lines = []
    now = datetime.datetime.now()
    week_ago = now - datetime.timedelta(days=7)

    # 1. Product & Inventory (from memory)
    products = data_manager.products
    if products:
        total_products = len(products)
        total_val = sum(float(p.get("current_stock", 0) or 0) * float(p.get("unit_price", 0) or 0) for p in products)
        lines.append(f"TOTAL_INVENTORY_PORTFOLIO_SIZE: {total_products} unique products.")
        lines.append(f"TOTAL_PORTFOLIO_VALUE: ₹{total_val:,.0f}")
        
        # Product details sample (for LLM context)
        sample = [f"{p.get('sku')}:{p.get('name')}|Qty:{p.get('current_stock')}|Supplier:{p.get('supplier_name')}" for p in products[:50]]
        lines.append("PRODUCT_MASTER_DATA_SAMPLE: " + " | ".join(sample))

    # 2. Replenishment Recommendations (Manager Action Required)
    brief_log = data_manager.brief_log
    today_str = now.strftime("%Y-%m-%d")
    today_items = brief_log.get(today_str, {}).get("items", [])
    
    # Calculate PENDING REVIEWS (Today's recommendations NOT yet decided)
    decided_skus = {o.get("sku") for o in data_manager.overrides if (o.get("timestamp") or "").startswith(today_str)}
    pending_items = [i for i in today_items if i.get("sku") not in decided_skus]
    pending_count = len(pending_items)
    critical_count = len([i for i in pending_items if "STOCKOUT" in i.get("risk_level", "")])
    
    lines.append(f"PENDING_MANAGER_REVIEWS_TODAY: {pending_count} products awaiting review/decision.")
    if pending_count > 0:
        lines.append(f"CRITICAL_PENDING_REVIEWS: {critical_count} items at critical stockout risk.")
        recs_sample = [f"{i['product_name']} (SKU:{i['sku']}, RecQty:{i.get('recommended_qty', 0)})" for i in pending_items[:12]]
        lines.append(f"PENDING_REVIEW_SAMPLES: {', '.join(recs_sample)}")
    
    # 3. Orders This Week (Already decided/approved)
    all_overrides = data_manager.overrides
    weekly_active = []
    for o in all_overrides:
        try:
            ts_str = o.get("timestamp", "")
            if not ts_str: continue
            ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
            if ts > week_ago and o.get("status") != "cancelled":
                weekly_active.append(o)
        except:
            continue
    
    lines.append(f"RECENT_DECISIONS_SUMMARY: Total active orders/decisions (last 7 days): {len(weekly_active)}.")
    
    # 3b. Today's Specific Activity
    today_decisions = [o for o in all_overrides if (o.get("timestamp") or "").startswith(today_str)]
    today_approved = len([o for o in today_decisions if o.get("decision") == "approved"])
    today_overridden = len([o for o in today_decisions if o.get("decision") == "overridden"])
    lines.append(f"TODAYS_ACTIVITY: Approved: {today_approved}, Overridden: {today_overridden}, Total Decisions Made Today: {len(today_decisions)}.")

    if weekly_active:
        items = [f"{o.get('product_name')} ({o.get('status')})" for o in weekly_active[:10]]
        lines.append(f"RECENT_ORDER_SAMPLES: {', '.join(items)}")

    # 4. Pipeline/Stock Alerts
    pending_pipeline = data_manager.caches["pending_orders"]
    lines.append(f"TOTAL_PIPELINE_ORDERS: {len(pending_pipeline)} currently in 'approved' or 'ordered' status.")

    low_stock = data_manager.caches['low_stock']
    lines.append(f"SYSTEM_LOW_STOCK_ALERTS: {len(low_stock)} items are technically below reorder threshold.")

    # 6. Dead & Slow Stock (from cache)
    dead = data_manager.caches.get("dead_stock", [])
    slow = data_manager.caches.get("slow_stock", [])
    lines.append(f"DEAD STOCK (>30 days): {len(dead)} items.")
    if dead:
        lines.append(f"DEAD_STOCK_SAMPLES: {', '.join(dead[:10])}")
    
    lines.append(f"SLOW MOVING (15-30 days): {len(slow)} items.")
    if slow:
        lines.append(f"SLOW_MOVING_SAMPLES: {', '.join(slow[:10])}")

    # 6b. Overstock
    overstock = data_manager.caches.get("overstock", [])
    lines.append(f"OVERSTOCK (90+ days of stock on hand): {len(overstock)} items.")
    if overstock:
        lines.append(f"OVERSTOCK_SAMPLES: {', '.join(overstock[:10])}")

    # 6c. Incoming Stock (approved/ordered, not yet received)
    incoming_total = data_manager.caches.get("incoming_stock_total", 0)
    incoming_items = data_manager.caches.get("incoming_stock_items", [])
    lines.append(f"INCOMING_STOCK_TOTAL_UNITS: {int(incoming_total)} units across {len(incoming_items)} products.")
    if incoming_items:
        inc_sample = [f"{i['name']} ({int(i['qty'])} units)" for i in incoming_items[:10]]
        lines.append(f"INCOMING_STOCK_SAMPLES: {', '.join(inc_sample)}")

    # 6d. Expiry & Batches
    expiry_summary = data_manager.caches.get("expiry_summary", {})
    if expiry_summary:
        sc = expiry_summary.get("status_counts", {})
        lines.append(
            f"EXPIRY_OVERVIEW: {expiry_summary.get('total_active_batches', 0)} active batches. "
            f"Expired: {sc.get('Expired', 0)}, Expiring Soon: {sc.get('Expiring Soon', 0)}, "
            f"High Risk: {sc.get('High Risk', 0)}, Caution: {sc.get('Caution', 0)}, "
            f"Monitor: {sc.get('Monitor', 0)}, Healthy: {sc.get('Healthy', 0)}. "
            f"Value at risk (expiring within 30 days): ₹{expiry_summary.get('at_risk_value', 0):,.0f}. "
            f"Disposed batches to date: {expiry_summary.get('disposed_count', 0)}."
        )
        soon = data_manager.caches.get("expiry_soon_batches", [])
        if soon:
            soon_sample = [f"{b['product_name']} (batch {b['batch_no']}, {b['days_left']}d left, qty {int(b['quantity'])})" for b in soon[:8]]
            lines.append(f"EXPIRING_SOON_BATCH_SAMPLES: {', '.join(soon_sample)}")
        expired = data_manager.caches.get("expiry_expired_batches", [])
        if expired:
            expired_sample = [f"{b['product_name']} (batch {b['batch_no']}, qty {int(b['quantity'])})" for b in expired[:8]]
            lines.append(f"EXPIRED_BATCH_SAMPLES: {', '.join(expired_sample)}")
    else:
        lines.append("EXPIRY_OVERVIEW: No batch/expiry data available.")

    # 6. Weather & Festivals (from cache)
    lines.append(data_manager.caches["weather_summary"])
    
    fest_sum = data_manager.caches["festival_summary"]
    fest_ready = data_manager.caches.get("festival_readiness", {})
    if fest_ready:
        fest_sum += f" Readiness for {fest_ready['festival']}: {fest_ready['readiness_pct']}% ({fest_ready['ready_count']}/{fest_ready['total_catalog']} critical items in stock)."
    lines.append(fest_sum)

    # 7. Suppliers & Performance
    suppliers = data_manager.suppliers
    if suppliers:
        sup_intel = data_manager.caches.get("supplier_intel", [])
        if sup_intel:
            sup_info = [f"{s['name']} (Prods:{s['product_count']}, Lead:{s['avg_lead_time']}d)" for s in sup_intel]
            lines.append(f"TOP_SUPPLIERS: {', '.join(sup_info)}")
        else:
            sup_info = [f"{s.get('name')} (Lead:{s.get('default_lead_time_days')}d)" for s in suppliers[:5]]
            lines.append(f"SUPPLIERS: {', '.join(sup_info)}")

    # 8. Inventory Health & Metrics (Dashboard)
    health = data_manager.caches.get("inventory_health", {})
    if health:
        lines.append(f"DASHBOARD_HEALTH_METRICS: Healthy: {health['healthy_pct']}%, Low Stock: {health['low_stock_pct']}%, Dead Stock: {health['dead_stock_pct']}%, Stockout Risk: {health.get('stockout_risk_items', 0)} items.")

    # 9. Supplier Performance & Mapping
    supplier_perf = data_manager.caches.get("supplier_performance", [])
    if supplier_perf:
        lines.append(f"TOTAL_SUPPLIERS: {len(supplier_perf)}")
        best = data_manager.caches.get("best_supplier_overall", {})
        if best:
            lines.append(
                f"BEST_SUPPLIER_OVERALL: {best.get('name')} — reliability {best.get('reliability_score')}, "
                f"on-time {best.get('on_time_pct')}%, lead time {best.get('avg_lead_time')}d, "
                f"fill rate {best.get('fill_rate')}%, quality {best.get('quality_rating')}."
            )
        top_sample = [f"{s.get('name')} (rel {s.get('reliability_score')})" for s in supplier_perf[:5]]
        lines.append(f"TOP_SUPPLIERS: {', '.join(top_sample)}")
    mapping = data_manager.caches.get("supplier_mapping", {})
    lines.append(f"SUPPLIER_PRODUCT_MAPPINGS: {mapping.get('total_mappings', 0)} total mappings.")

    # 10. Upcoming / Incoming Stock
    upcoming = data_manager.caches.get("upcoming_stock", [])
    upcoming_total = data_manager.caches.get("upcoming_stock_total", 0)
    lines.append(f"UPCOMING_STOCK: {len(upcoming)} POs, {int(upcoming_total)} total units incoming.")
    if upcoming:
        up_sample = [f"{u.get('product_name')} ({int(u.get('qty'))} units, PO {u.get('po_number')})" for u in upcoming[:8]]
        lines.append(f"UPCOMING_SAMPLES: {', '.join(up_sample)}")

    # 11. Discounts
    lines.append(data_manager.caches.get("discounts_summary", "Discount data unavailable."))

    # 12. Stockout Products
    stockouts = data_manager.caches.get("stockout_products", [])
    lines.append(f"STOCKOUT_PRODUCTS: {len(stockouts)} products currently have zero stock.")
    if stockouts:
        stockout_samples = [f"{p.get('name')} (SKU: {p.get('sku')})" for p in stockouts[:8]]
        lines.append(f"STOCKOUT_SAMPLES: {', '.join(stockout_samples)}")

    # 13. Expiring windows
    for bucket, label in [("expiring_7_days", "7 days"), ("expiring_15_days", "15 days"), ("expiring_30_days", "30 days")]:
        items = data_manager.caches.get(bucket, [])
        if items:
            sample = [f"{i.get('product_name')} (batch {i.get('batch_no')}, {i.get('days_left')}d)" for i in items[:5]]
            lines.append(f"EXPIRING_{label.upper().replace(' ', '_')}: {len(items)} batches — {', '.join(sample)}")

    return "\n".join(lines) if lines else "Live context unavailable."

@router.post("/message")
async def chat_message(
    req: ChatRequest,
    payload: dict = Depends(require_any_role()),
):
    start_time = time.perf_counter()
    
    # 1. Server-side read-only enforcement
    if _has_write_intent(req.message):
        async def _blocked_stream():
            msg = "⛔ I'm read-only and cannot perform that action."
            yield f"data: {json.dumps({'content': msg})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_blocked_stream(), media_type="text/event-stream")

    # 2. OPTIMIZED INTENT ROUTING (Sub-millisecond)
    intent_start = time.perf_counter()
    direct_reply = intent_router.route(req.message)
    intent_duration = time.perf_counter() - intent_start
    
    if direct_reply:
        total_msg_time = time.perf_counter() - start_time
        logger.info(f"[Chatbot] Direct intent match in {intent_duration:.4f}s. Total: {total_msg_time:.4f}s")
        
        async def _direct_stream():
            yield f"data: {json.dumps({'content': direct_reply})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(_direct_stream(), media_type="text/event-stream")

    # 3. LLM PATH (Memory Context)
    context_start = time.perf_counter()
    sales_summary = _get_sales_summary()
    context = gather_live_context()
    context_duration = time.perf_counter() - context_start
    
    user_name = payload.get("name", "Manager")
    user_role = payload.get("role", "manager")
    
    from datetime import datetime, timedelta, timezone
    ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    current_date_ist = ist_now.strftime("%A, %Y-%m-%d")
    current_time_ist = ist_now.strftime("%I:%M %p")

    system_prompt = f"""You are 'SIRABot', the friendly and knowledgeable AI assistant for SIRA — like a real e-commerce ops/support assistant — for a retail store in India.

CURRENT DATE (IST): {current_date_ist}, {current_time_ist}

SALES INSIGHTS:
{sales_summary}

LIVE SYSTEM STATE (Use these numbers for 100% accuracy):
{context}

YOU CAN ANSWER QUESTIONS ABOUT:
- Product catalog: total number of products, stock levels, unit prices, categories, and rich product details.
- Stockout products: items with zero current stock.
- Expiry & batches: expiry dates, batches expiring in 7, 15, or 30 days, expired batches, disposed batches, value at risk.
- Dead stock (30+ days unsold), slow-moving items (15-30 days unsold), and overstock (excess stock relative to sales velocity).
- Incoming stock / shipments for any product (approved or ordered but not yet received).
- Upcoming stock: purchase orders not yet received and their expected delivery dates.
- Today's replenishment recommendations and pending manager reviews.
- Orders placed this week, and recent order/decision activity.
- Supplier data: full supplier directory, supplier-product mappings, best supplier overall, and best supplier per product.
- Discounts: active discounts, pending recommendations, approved/rejected discount history.
- Weather and upcoming festival readiness.

STRICT GUIDELINES:
1. ACCURACY: Check the context carefully. Distinguish between 'Total Products' (total inventory size) and 'Pending Reviews' (items requiring manager action today).
2. INTENT: Understand the user's intent. Answer questions about stock, expiry, dead stock, overstock, slow-moving items, incoming stock, suppliers, and orders naturally and directly.
3. CONTEXT: Use the chat history to handle follow-up questions (e.g., 'who supplies it?' refers to the last product discussed).
4. TONE: Be warm, professional, and business-focused — like a helpful e-commerce support agent who knows the store inside out. Include actionable recommendations (e.g., 'I suggest reviewing the 5 critical items first') where appropriate.
5. LIMITATIONS: You are strictly READ-ONLY — you cannot create, update, delete, place, cancel, or approve anything. If asked to perform an action, politely explain you can only provide information. If data is not in the context, clearly state you don't have access to that information. Do NOT hallucinate SKUs, stock levels, or expiry dates.
6. FORMATTING: Use ₹ for currency. Use Markdown for clarity (bolding, lists). Keep answers concise and to the point to save tokens — a few sentences or a short list is usually enough.
"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in req.history[-6:]:
        if msg.role in ("user", "assistant"):
            messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": req.message})

    logger.info(f"[Chatbot] LLM Path engaged. Context duration: {context_duration:.4f}s")
    return StreamingResponse(
        stream_chatbot_groq(messages),
        media_type="text/event-stream"
    )
