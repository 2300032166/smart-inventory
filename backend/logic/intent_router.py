import re
import datetime
from typing import Optional, Tuple, Dict
from .chatbot_data import data_manager

class IntentRouter:
    def __init__(self):
        # Patterns for direct lookups
        self.patterns = {
            "stock_lookup": [
                r"stock (?:of|for) (.+)",
                r"how (?:many|much) (.+) (?:do we have|is in stock|is there)",
                r"quantity (?:of|for) (.+)"
            ],
            "price_lookup": [
                r"price (?:of|for) (.+)",
                r"how much is (.+)",
                r"cost (?:of|for) (.+)"
            ],
            "incoming_lookup": [
                r"incoming stock (?:of|for) (.+)",
                r"any incoming (?:stock|shipment|order) (?:of|for) (.+)",
                r"is (.+) incoming",
                r"when (?:is|will) (.+) (?:arrive|arriving|come|coming)"
            ],
            "summary_lookup": [
                r"inventory summary",
                r"total portfolio value",
                r"how many products"
            ],
            "ordered_lookup": [
                r"how many orders are (?:in ordered|ordered)",
                r"how many items are ordered"
            ],
            "weather_lookup": [
                r"weather (?:now|today|forecast)",
                r"how is the weather"
            ],
            "festival_lookup": [
                r"upcoming festival",
                r"what is (?:the )?next festival",
                r"festival (?:calendar|info)"
            ],
            "review_lookup": [
                r"how many (?:products|items) (?:need|require) review",
                r"pending review",
                r"review (?:need to be|needs to be) done",
                r"how many items are pending"
            ],
            "dead_stock_lookup": [
                r"dead stock",
                r"how many (?:products|items) (?:are )?dead",
            ],
            "slow_moving_lookup": [
                r"slow moving",
                r"slow-moving",
                r"how many (?:products|items) (?:are )?slow moving",
            ],
            "overstock_lookup": [
                r"overstock",
                r"over stocked",
                r"how many (?:products|items) (?:are )?overstock",
            ],
            "expiry_summary_lookup": [
                r"expir(?:y|ing) (?:batches|summary|status|overview)",
                r"how many (?:batches|products) (?:are )?expir",
                r"expiry dashboard",
            ],
            "expiry_soon_lookup": [
                r"(?:products|items|batches) expiring soon",
                r"what(?:'s| is) expiring soon",
                r"near(?:ing)? expiry",
            ],
            "expired_lookup": [
                r"expired (?:batches|products|items|stock)",
                r"what(?:'s| is| has) expired",
                r"how many (?:batches|products|items) (?:have )?expired",
            ],
            "supplier_count_lookup": [
                r"how many suppliers",
                r"total suppliers",
                r"number of suppliers",
            ],
            "orders_week_lookup": [
                r"orders (?:this|per) week",
                r"how many orders (?:this|per) week",
                r"weekly orders?",
            ],
            "today_recs_lookup": [
                r"today'?s? recommendations?",
                r"what (?:should|needs to) (?:i|we) reorder today",
                r"what needs reordering today",
                r"what needs to be reordered today",
                r"what to reorder today",
                r"recommendations? for today",
                r"reorder today",
            ],
            "supplier_list_lookup": [
                r"list (?:all )?suppliers",
                r"(?:all )?suppliers(?: details)?",
                r"show suppliers",
                r"supplier directory",
            ],
            "supplier_mapping_lookup": [
                r"suppliers? (?:for|of) (.+)",
                r"who supplies? (.+)",
                r"who (?:is the|are the) suppliers? (?:for|of) (.+)",
                r"supplier mapping (?:for|of) (.+)",
            ],
            "best_supplier_overall_lookup": [
                r"best supplier overall",
                r"top supplier",
                r"(?:which is the )?best supplier",
                r"highest ranked supplier",
            ],
            "best_supplier_product_lookup": [
                r"best supplier (?:for|of) (.+)",
                r"recommended supplier (?:for|of) (.+)",
                r"top supplier (?:for|of) (.+)",
                r"which supplier (?:is best|should i use) (?:for|with) (.+)",
            ],
            "discounts_lookup": [
                r"discounts?",
                r"active discounts?",
                r"pending discounts?",
                r"approved discounts?",
                r"rejected discounts?",
                r"discount recommendations?",
            ],
            "upcoming_stock_lookup": [
                r"upcoming stock",
                r"incoming stock",
                r"stock (?:coming|on the way|in transit)",
                r"orders? (?:in transit|on the way|not received|ordered|approved|pending)",
                r"purchase orders? (?:not received|ordered|approved|pending)",
                r"what stock is coming",
                r"orders? in transit",
            ],
            "stockout_lookup": [
                r"stockout products?",
                r"out of stock products?",
                r"zero stock products?",
                r"products? with no stock",
                r"no stock products?",
            ],
            "expiring_7_days_lookup": [
                r"expir(?:ing|es) (?:in |within )?7(?: days)?",
                r"products? expiring (?:in |within )?7(?: days)?",
                r"expiring next week",
            ],
            "expiring_15_days_lookup": [
                r"expir(?:ing|es) (?:in |within )?15(?: days)?",
                r"products? expiring (?:in |within )?15(?: days)?",
            ],
            "expiring_30_days_lookup": [
                r"expir(?:ing|es) (?:in |within )?30(?: days)?",
                r"products? expiring (?:in |within )?30(?: days)?",
            ],
            "product_details_lookup": [
                r"details? (?:of|for|about)?\s*(.+)",
                r"tell me about (.+)",
                r"product info(?:rmation)? (?:for|about)?\s*(.+)",
                r"product details? (?:for|about)?\s*(.+)",
                r"info (?:on|about) (.+)",
            ],
        }

    def route(self, query: str) -> Optional[str]:
        """
        Classifies the query and returns a direct string answer if possible.
        If returns None, the request should fall back to the LLM.
        """
        q = query.lower().strip()

        # 0. Specific keyword-based intents are checked FIRST, before the
        # broad/greedy generic stock & price lookup patterns below, so
        # queries like "how many suppliers do we have" aren't misrouted
        # into a generic product stock lookup.

        # 4. Dead stock
        for pattern in self.patterns["dead_stock_lookup"]:
            if re.search(pattern, q):
                dead = data_manager.caches.get("dead_stock", [])
                if not dead:
                    return "No dead stock (unsold for 30+ days) at the moment. Everything is moving."
                sample = ", ".join(dead[:10])
                more = f" and {len(dead) - 10} more" if len(dead) > 10 else ""
                return f"There are **{len(dead)}** dead stock items (no sales in 30+ days): {sample}{more}."

        # 5. Slow moving
        for pattern in self.patterns["slow_moving_lookup"]:
            if re.search(pattern, q):
                slow = data_manager.caches.get("slow_stock", [])
                if not slow:
                    return "No slow-moving products right now."
                sample = ", ".join(slow[:10])
                more = f" and {len(slow) - 10} more" if len(slow) > 10 else ""
                return f"There are **{len(slow)}** slow-moving items (15-30 days without a sale): {sample}{more}."

        # 6. Overstock
        for pattern in self.patterns["overstock_lookup"]:
            if re.search(pattern, q):
                over = data_manager.caches.get("overstock", [])
                if not over:
                    return "No overstocked products detected right now."
                sample = ", ".join(over[:10])
                more = f" and {len(over) - 10} more" if len(over) > 10 else ""
                return f"There are **{len(over)}** overstocked items (90+ days of stock on hand): {sample}{more}."

        # 7. Expiry summary
        for pattern in self.patterns["expiry_summary_lookup"]:
            if re.search(pattern, q):
                summ = data_manager.caches.get("expiry_summary", {})
                if not summ:
                    return "Expiry batch data is not available."
                sc = summ.get("status_counts", {})
                return (
                    f"**Expiry overview**: {summ.get('total_active_batches', 0)} active batches. "
                    f"Expired: {sc.get('Expired', 0)}, Expiring Soon: {sc.get('Expiring Soon', 0)}, "
                    f"High Risk: {sc.get('High Risk', 0)}, Caution: {sc.get('Caution', 0)}, "
                    f"Monitor: {sc.get('Monitor', 0)}, Healthy: {sc.get('Healthy', 0)}. "
                    f"Value at risk: \u20b9{summ.get('at_risk_value', 0):,.0f}. Disposed so far: {summ.get('disposed_count', 0)}."
                )

        # 8. Expiring soon
        for pattern in self.patterns["expiry_soon_lookup"]:
            if re.search(pattern, q):
                soon = data_manager.caches.get("expiry_soon_batches", [])
                if not soon:
                    return "No batches are currently expiring soon or at high risk."
                sample = ", ".join([f"{b['product_name']} (batch {b['batch_no']}, {b['days_left']}d left)" for b in soon[:8]])
                more = f" and {len(soon) - 8} more" if len(soon) > 8 else ""
                return f"**{len(soon)}** batches are expiring soon / high risk: {sample}{more}."

        # 9. Expired
        for pattern in self.patterns["expired_lookup"]:
            if re.search(pattern, q):
                expired = data_manager.caches.get("expiry_expired_batches", [])
                if not expired:
                    return "No expired batches currently — nice and clean!"
                sample = ", ".join([f"{b['product_name']} (batch {b['batch_no']})" for b in expired[:8]])
                more = f" and {len(expired) - 8} more" if len(expired) > 8 else ""
                return f"**{len(expired)}** batches have expired: {sample}{more}."

        # 10. Supplier count
        for pattern in self.patterns["supplier_count_lookup"]:
            if re.search(pattern, q):
                suppliers = data_manager.suppliers or []
                return f"We currently work with **{len(suppliers)}** suppliers."

        # 11. Orders per week
        for pattern in self.patterns["orders_week_lookup"]:
            if re.search(pattern, q):
                now = datetime.datetime.now()
                week_ago = now - datetime.timedelta(days=7)
                count = 0
                for o in data_manager.overrides:
                    try:
                        ts_str = o.get("timestamp", "")
                        if not ts_str:
                            continue
                        ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
                        if ts > week_ago and o.get("status") != "cancelled":
                            count += 1
                    except Exception:
                        continue
                return f"There have been **{count}** active orders/decisions placed in the last 7 days."

        # 12. Today's recommendations
        for pattern in self.patterns["today_recs_lookup"]:
            if re.search(pattern, q):
                today_str = datetime.datetime.now().strftime("%Y-%m-%d")
                today_items = data_manager.brief_log.get(today_str, {}).get("items", [])
                decided_skus = {o.get("sku") for o in data_manager.overrides if (o.get("timestamp") or "").startswith(today_str)}
                pending_items = [i for i in today_items if i.get("sku") not in decided_skus]
                if not pending_items:
                    return "No pending replenishment recommendations for today — you're all caught up!"
                sample = ", ".join([f"{i['product_name']} (Qty: {i.get('recommended_qty', 0)})" for i in pending_items[:10]])
                more = f" and {len(pending_items) - 10} more" if len(pending_items) > 10 else ""
                return f"**{len(pending_items)}** products need review today: {sample}{more}."

        # 14. Supplier list / details
        for pattern in self.patterns["supplier_list_lookup"]:
            if re.search(pattern, q):
                perf = data_manager.caches.get("supplier_performance", [])
                if not perf:
                    return "Supplier data is not available."
                lines = []
                for s in perf[:15]:
                    lines.append(
                        f"**{s.get('name')}** — reliability {s.get('reliability_score', 0)}, "
                        f"on-time {s.get('on_time_pct', 0)}%, lead time {s.get('avg_lead_time', 0)}d, "
                        f"products {s.get('product_count', 0)}, contact: {s.get('contact_person', '')} ({s.get('phone', '')})"
                    )
                more = f"\n… and {len(perf) - 15} more suppliers." if len(perf) > 15 else ""
                return f"We work with **{len(perf)}** suppliers:\n" + "\n".join(lines) + more

        # 15. Best supplier for a specific product
        for pattern in self.patterns["best_supplier_product_lookup"]:
            match = re.search(pattern, q)
            if match:
                term = match.group(1).strip()
                prod = data_manager.get_product(term)
                if not prod:
                    return f"I couldn't find a product matching '{term}' in the inventory."
                sku = str(prod.get("sku", "")).strip().upper()
                best = data_manager.get_best_supplier_for_sku(sku)
                if not best:
                    return f"{prod.get('name')} (SKU: {sku}) has no mapped suppliers to compare."
                return (
                    f"The recommended supplier for **{prod.get('name')}** (SKU: {sku}) is **{best.get('name')}** "
                    f"with a reliability score of **{best.get('reliability_score', 0)}**. "
                    f"On-time: {best.get('on_time_pct', 0)}%, lead time: {best.get('avg_lead_time', 0)} days, "
                    f"quality rating: {best.get('quality_rating', 0)}."
                )

        # 16. Best supplier overall
        for pattern in self.patterns["best_supplier_overall_lookup"]:
            if re.search(pattern, q):
                best = data_manager.caches.get("best_supplier_overall")
                if not best:
                    return "Supplier performance data is not available yet."
                return (
                    f"The best overall supplier is **{best.get('name')}** "
                    f"with a reliability score of **{best.get('reliability_score', 0)}**. "
                    f"On-time delivery: {best.get('on_time_pct', 0)}%, average lead time: {best.get('avg_lead_time', 0)} days, "
                    f"fill rate: {best.get('fill_rate', 0)}%, quality rating: {best.get('quality_rating', 0)}."
                )

        # 17. Supplier mapping for a product
        for pattern in self.patterns["supplier_mapping_lookup"]:
            match = re.search(pattern, q)
            if match:
                term = match.group(1).strip()
                prod = data_manager.get_product(term)
                if not prod:
                    return f"I couldn't find a product matching '{term}' in the inventory."
                sku = str(prod.get("sku", "")).strip().upper()
                suppliers = data_manager.get_suppliers_for_sku(sku)
                perf = data_manager.caches.get("supplier_performance", [])
                if not suppliers:
                    return f"{prod.get('name')} (SKU: {sku}) has no mapped suppliers."
                lines = []
                for s in suppliers:
                    sid = str(s.get("supplier_id", "")).strip().upper()
                    metrics = next((p for p in perf if p.get("supplier_id") == sid), {})
                    lines.append(
                        f"- **{s.get('name', sid)}** — reliability {metrics.get('reliability_score', 0)}, "
                        f"on-time {metrics.get('on_time_pct', 0)}%, lead time {metrics.get('avg_lead_time', 0)}d"
                    )
                return f"Suppliers mapped to **{prod.get('name')}** (SKU: {sku}):\n" + "\n".join(lines)

        # 18. Discounts
        for pattern in self.patterns["discounts_lookup"]:
            if re.search(pattern, q):
                status = None
                if "active" in q:
                    status = "active"
                elif "pending" in q:
                    status = "pending"
                elif "approved" in q:
                    status = "approved"
                elif "rejected" in q:
                    status = "rejected"
                items = data_manager.get_discounts_by_status(status or "all")
                if not items:
                    return f"No {status or ''} discounts found."
                label = status.title() if status else "All"
                sample = ", ".join([
                    f"{i.get('product_name', i.get('sku', ''))} ({i.get('discount_percent', i.get('suggested_discount', 0))}% off)"
                    for i in items[:10]
                ])
                more = f" and {len(items) - 10} more" if len(items) > 10 else ""
                return f"**{len(items)}** {label.lower()} discounts: {sample}{more}."

        # 19. Upcoming / incoming stock
        for pattern in self.patterns["upcoming_stock_lookup"]:
            if re.search(pattern, q):
                upcoming = data_manager.caches.get("upcoming_stock", [])
                total = data_manager.caches.get("upcoming_stock_total", 0)
                if not upcoming:
                    return "No upcoming stock on the way — all POs have been received or cancelled."
                sample = ", ".join([
                    f"{u.get('product_name')} ({int(u.get('qty', 0))} units, PO {u.get('po_number', '')})"
                    for u in upcoming[:10]
                ])
                more = f" and {len(upcoming) - 10} more POs" if len(upcoming) > 10 else ""
                return f"**{len(upcoming)}** POs are incoming with **{int(total)}** total units: {sample}{more}."

        # 20. Stockout products
        for pattern in self.patterns["stockout_lookup"]:
            if re.search(pattern, q):
                stockouts = data_manager.caches.get("stockout_products", [])
                if not stockouts:
                    return "No stockout products right now. Every product has available stock."
                sample = ", ".join([f"{p.get('name')} (SKU: {p.get('sku')})" for p in stockouts[:10]])
                more = f" and {len(stockouts) - 10} more" if len(stockouts) > 10 else ""
                return f"**{len(stockouts)}** products are currently out of stock: {sample}{more}."

        # 21. Expiring in 7 / 15 / 30 days
        for bucket, label in [("expiring_7_days", "7"), ("expiring_15_days", "15"), ("expiring_30_days", "30")]:
            for pattern in self.patterns[f"{bucket}_lookup"]:
                if re.search(pattern, q):
                    items = data_manager.caches.get(bucket, [])
                    if not items:
                        return f"No products expiring in the next {label} days."
                    sample = ", ".join([f"{i.get('product_name')} (batch {i.get('batch_no')}, {i.get('days_left')}d left)" for i in items[:10]])
                    more = f" and {len(items) - 10} more" if len(items) > 10 else ""
                    return f"**{len(items)}** batches expire within {label} days: {sample}{more}."

        # 22. Product details (rich summary)
        for pattern in self.patterns["product_details_lookup"]:
            match = re.search(pattern, q)
            if match:
                term = match.group(1).strip()
                prod = data_manager.get_product(term)
                if not prod:
                    return f"I couldn't find a product matching '{term}' in the inventory."
                sku = str(prod.get("sku", "")).strip().upper()
                stock = int(float(prod.get("current_stock", 0)))
                threshold = int(float(prod.get("reorder_threshold", 0)))
                price = float(prod.get("unit_price", 0))
                suppliers = data_manager.get_suppliers_for_sku(sku)
                best = data_manager.get_best_supplier_for_sku(sku)
                upcoming = data_manager.get_upcoming_stock_for_sku(sku)
                parts = [
                    f"**{prod.get('name')}** (SKU: {sku})",
                    f"Category: {prod.get('category', '—')}",
                    f"Stock: **{stock}** units (reorder threshold: {threshold})",
                    f"Unit price: ₹{price:,.2f}",
                    f"Lead time: {prod.get('lead_time_days', '—')} days",
                    f"Primary supplier: {prod.get('supplier_name', '—')}",
                ]
                if suppliers:
                    parts.append(f"Mapped suppliers: {', '.join([s.get('name', '') for s in suppliers])}")
                if best:
                    parts.append(f"Recommended supplier: **{best.get('name')}** (reliability {best.get('reliability_score', 0)})")
                if upcoming:
                    parts.append(f"Incoming: {sum(u.get('qty', 0) for u in upcoming)} units on the way")
                return "\n".join(parts)

        # 23. Generic stock lookup (broad pattern — kept last so it doesn't
        # swallow more specific intents like supplier/dead-stock/expiry queries)
        for pattern in self.patterns["stock_lookup"]:
            match = re.search(pattern, q)
            if match:
                term = match.group(1).strip()
                prod = data_manager.get_product(term)
                if prod:
                    return f"We currently have **{int(float(prod.get('current_stock', 0)))}** units of {prod.get('name')} (SKU: {prod.get('sku')}) in stock."
                return f"I couldn't find a product matching '{term}' in the inventory."

        # 14. Generic price lookup
        for pattern in self.patterns["price_lookup"]:
            match = re.search(pattern, q)
            if match:
                term = match.group(1).strip()
                prod = data_manager.get_product(term)
                if prod:
                    return f"The unit price for {prod.get('name')} is **\u20b9{float(prod.get('unit_price', 0)):,.2f}**."
                return f"I couldn't find price data for '{term}'."

        # 15. Incoming stock lookup (per product)
        for pattern in self.patterns["incoming_lookup"]:
            match = re.search(pattern, q)
            if match:
                term = match.group(1).strip()
                prod = data_manager.get_product(term)
                if not prod:
                    return f"I couldn't find a product matching '{term}' in the inventory."
                sku = str(prod.get("sku", "")).strip().upper()
                items = data_manager.caches.get("incoming_stock_items", [])
                match_item = next((i for i in items if i["sku"] == sku), None)
                if match_item:
                    return f"Yes — **{int(match_item['qty'])}** units of {prod.get('name')} are incoming (approved/ordered)."
                return f"No incoming stock currently for {prod.get('name')}."

        return None # Fallback to LLM for all NL/Summary/Metric queries

intent_router = IntentRouter()
