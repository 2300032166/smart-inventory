import os
import json
import logging
import time
import pandas as pd
import datetime
from threading import Lock
from typing import Dict, Any, List, Optional
from datetime import timezone

from routes.suppliers import calc_metrics

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

class ChatbotDataManager:
    _instance = None
    _lock = Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(ChatbotDataManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def initialize(self):
        if self._initialized:
            return
        
        start_time = time.perf_counter()
        logger.info("[ChatbotData] Initializing in-memory manager...")
        
        self.products: List[Dict] = []
        self.product_lookup: Dict[str, Dict] = {} # SKU -> Product
        self.suppliers: List[Dict] = []
        self.supplier_lookup: Dict[str, Dict] = {} # supplier_id -> Supplier
        self.supplier_products: List[Dict] = []    # supplier-product mapping rows
        self.purchase_orders: List[Dict] = []        # PO rows
        self.discounts: Dict = {}
        self.sales_df: Optional[pd.DataFrame] = None
        self.overrides: List[Dict] = []
        self.brief_log: Dict = {}
        self.weather: List[Dict] = []
        self.festivals: List[Dict] = []
        
        self.caches = {
            "inventory_summary": "",
            "low_stock": [],
            "dead_stock": [],
            "slow_stock": [],
            "overstock": [],
            "pending_orders": [],
            "incoming_stock_total": 0.0,
            "incoming_stock_items": [],
            "expiry_summary": {},
            "expiry_soon_batches": [],
            "expiry_expired_batches": [],
            "supplier_summary": "",
            "supplier_mapping": {},
            "supplier_performance": [],
            "best_supplier_overall": {},
            "best_suppliers_per_product": {},
            "upcoming_stock": [],
            "upcoming_stock_total": 0.0,
            "discounts_summary": "",
            "active_discounts": [],
            "pending_discount_recommendations": [],
            "expiring_7_days": [],
            "expiring_15_days": [],
            "expiring_30_days": [],
            "stockout_products": [],
            "weather_summary": "",
            "festival_summary": "",
            "festival_readiness": {},
            "inventory_health": {},
            "last_refresh": 0.0
        }
        
        self.reload_all()
        self._start_background_refresh()
        
        end_time = time.perf_counter()
        logger.info(f"[ChatbotData] Initialization complete in {end_time - start_time:.4f}s")
        self._initialized = True

    def _start_background_refresh(self):
        import threading
        def _refresh_loop():
            while True:
                time.sleep(300) # Refresh every 5 minutes
                try:
                    self.reload_all()
                    logger.info("[ChatbotData] Background refresh complete.")
                except Exception as e:
                    logger.error(f"[ChatbotData] Background refresh failed: {e}")
        
        thread = threading.Thread(target=_refresh_loop, daemon=True)
        thread.start()

    def reload_all(self):
        """Load all CSV/JSON files into memory and build lookups."""
        start_time = time.perf_counter()
        
        # 1. Products
        prod_path = os.path.join(DATA_DIR, "products.csv")
        if os.path.exists(prod_path):
            from logic.pattern_detector import load_products_dynamic
            try:
                self.products = load_products_dynamic()
            except Exception as e:
                logger.error(f"[ChatbotData] Failed load_products_dynamic: {e}")
                df = pd.read_csv(prod_path)
                self.products = df.fillna("").to_dict(orient="records")
            self.product_lookup = {str(p.get("sku", "")).strip().upper(): p for p in self.products}
        
        # 2. Suppliers
        sup_path = os.path.join(DATA_DIR, "suppliers.csv")
        if os.path.exists(sup_path):
            df = pd.read_csv(sup_path)
            self.suppliers = df.fillna("").to_dict(orient="records")
            self.supplier_lookup = {str(s.get("supplier_id", "")).strip().upper(): s for s in self.suppliers}

        # 2b. Supplier-Product mapping
        sp_path = os.path.join(DATA_DIR, "supplier_products.csv")
        if os.path.exists(sp_path):
            df = pd.read_csv(sp_path)
            self.supplier_products = df.fillna("").to_dict(orient="records")

        # 2c. Purchase Orders
        po_path = os.path.join(DATA_DIR, "purchase_orders.csv")
        if os.path.exists(po_path):
            df = pd.read_csv(po_path)
            self.purchase_orders = df.fillna("").to_dict(orient="records")

        # 2d. Discounts
        self.discounts = self._load_json("discounts.json", {"recommendations": [], "active_discounts": [], "history": []})

        # 3. Sales (keep last 50k for performance, but in-memory)
        sales_path = os.path.join(DATA_DIR, "sales.csv")
        if os.path.exists(sales_path):
            self.sales_df = pd.read_csv(sales_path).tail(50000)
            self.sales_df["InvoiceDate"] = pd.to_datetime(self.sales_df["InvoiceDate"])

        # 4. Overrides & Brief Log
        self.overrides = self._load_json("override_history.json", [])
        self.brief_log = self._load_json("brief_log.json", {})

        # 5. Weather (Vijayawada) - Using a sync-friendly way to call async
        try:
            from logic.weather_client import fetch_weather_forecast
            import asyncio
            
            try:
                # Try to get the existing loop (works in main thread)
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If running, we can't block. For initialization, we'll try to reach it
                    # via a separate thread to get the result synchronously 
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        def run_in_new_loop():
                            return asyncio.run(fetch_weather_forecast())
                        future = pool.submit(run_in_new_loop)
                        self.weather = future.result(timeout=5)
                else:
                    self.weather = loop.run_until_complete(fetch_weather_forecast())
            except Exception:
                # Fallback for background threads or if above fails
                self.weather = asyncio.run(fetch_weather_forecast())

            if not self.weather:
                logger.warning("[ChatbotData] Weather fetch returned empty list.")
        except Exception as e:
            logger.error(f"[ChatbotData] Weather fetch failed: {e}")
            self.weather = []

        # 6. Festivals
        self.festivals = self._load_json("festivals.json", [])

        # 7. Build Caches
        self._refresh_caches()
        
        self.caches["last_refresh"] = time.time()
        logger.info(f"[ChatbotData] Reloaded all files in {time.perf_counter() - start_time:.4f}s")

    def _load_json(self, filename, default):
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            return default
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading {filename}: {e}")
            return default

    def _refresh_caches(self):
        """Pre-calculate summaries and lists for fast lookup."""
        try:
            # 1. Inventory Summary
            total_val = sum(float(p.get("current_stock", 0) or 0) * float(p.get("unit_price", 0) or 0) for p in self.products)
            cats = {}
            for p in self.products:
                c = p.get("category", "General")
                cats[c] = cats.get(c, 0) + 1
            
            self.caches["inventory_summary"] = (
                f"OVERVIEW: {len(self.products)} products in {len(cats)} categories. "
                f"Total portfolio value: \u20b9{total_val:,.0f}."
            )

            # 2. Low Stock / Stockout Risk
            low_stock = []
            for p in self.products:
                stock = float(p.get("current_stock", 0) or 0)
                thr = float(p.get("reorder_threshold", 0) or 0)
                if stock <= thr:
                    low_stock.append(p.get("name", "Unknown"))
            self.caches["low_stock"] = low_stock

            # 3. Dead Stock & Slow Moving
            dead_stock = []
            slow_moving = []
            
            # Use sales_df to find last sale date for each product
            last_sales = {}
            if self.sales_df is not None and not self.sales_df.empty:
                # Group by StockCode and get max InvoiceDate
                last_sales = self.sales_df.groupby("StockCode")["InvoiceDate"].max().to_dict()
            
            # Determine "today" based on current system time
            now_dt = datetime.datetime.now()
            
            for p in self.products:
                sku = str(p.get("sku", "")).strip().upper()
                stock = float(p.get("current_stock", 0) or 0)
                if stock <= 0:
                    continue
                
                last_sale = last_sales.get(sku)
                if last_sale is None:
                    # Never sold - treat as dead if older than 30 days or general caution
                    dead_stock.append(p.get("name", "Unknown"))
                    continue
                
                # Check if last_sale is a timestamp or datetime
                if isinstance(last_sale, pd.Timestamp):
                    last_sale = last_sale.to_pydatetime()
                
                # Ensure last_sale is naive if now_dt is naive
                if last_sale.tzinfo is not None:
                    last_sale = last_sale.replace(tzinfo=None)
                
                days_since = (now_dt - last_sale).days
                if days_since > 30:
                    dead_stock.append(p.get("name", "Unknown"))
                elif days_since > 15:
                    slow_moving.append(p.get("name", "Unknown"))
            
            self.caches["dead_stock"] = dead_stock
            self.caches["slow_stock"] = slow_moving

            # 3b. Overstock (using avg daily sales velocity vs current stock)
            overstock = []
            try:
                from logic.pattern_detector import get_avg_sales_map
                avg_sales_map = get_avg_sales_map()
            except Exception:
                avg_sales_map = {}
            for p in self.products:
                sku = str(p.get("sku", "")).strip().upper()
                stock = float(p.get("current_stock", 0) or 0)
                avg_v = avg_sales_map.get(sku, 0)
                if avg_v > 0 and (stock / avg_v) > 90:
                    overstock.append(p.get("name", "Unknown"))
            self.caches["overstock"] = overstock

            # 4. Pending Orders
            pending = [o for o in self.overrides if o.get("status") in ["approved", "pending", "ordered"]]
            self.caches["pending_orders"] = pending

            # 4b. Incoming Stock (orders approved/ordered, grouped by product)
            incoming_items = []
            incoming_total = 0.0
            sku_to_name = {str(p.get("sku", "")).strip().upper(): p.get("name", "") for p in self.products}
            incoming_by_sku: Dict[str, float] = {}
            for o in pending:
                sku = str(o.get("sku", "")).strip().upper()
                qty = float(o.get("actual_qty", 0) or 0)
                if qty <= 0:
                    continue
                incoming_by_sku[sku] = incoming_by_sku.get(sku, 0.0) + qty
            for sku, qty in incoming_by_sku.items():
                incoming_total += qty
                incoming_items.append({"sku": sku, "name": sku_to_name.get(sku, sku), "qty": qty})
            incoming_items.sort(key=lambda x: x["qty"], reverse=True)
            self.caches["incoming_stock_total"] = incoming_total
            self.caches["incoming_stock_items"] = incoming_items

            # 4c. Expiry & Batches
            self._refresh_expiry_cache()

            # 4. Supplier Summary
            self.caches["supplier_summary"] = f"Active Suppliers: {', '.join([s.get('name', '') for s in self.suppliers[:5]])}..."

            # 5. Weather Summary
            if self.weather:
                today = self.weather[0]
                self.caches["weather_summary"] = f"WEATHER (Vijayawada): {today.get('max_temp')}\u00b0C max, {today.get('precip')}mm precip. 7-day forecast available."
            else:
                self.caches["weather_summary"] = "Weather data unavailable."

            # 6. Festival Summary
            if self.festivals:
                now = datetime.datetime.now()
                upcoming = None
                for f in self.festivals:
                    f_date_str = f.get(f"date_{now.year}")
                    if f_date_str:
                        f_date = datetime.datetime.strptime(f_date_str, "%Y-%m-%d")
                        if f_date >= now:
                            if not upcoming or f_date < upcoming[1]:
                                upcoming = (f.get("name"), f_date)
                
                if upcoming:
                    self.caches["festival_summary"] = f"UPCOMING FESTIVAL: {upcoming[0]} on {upcoming[1].strftime('%Y-%m-%d')}."
                    
                    # Calculate Readiness for upcoming festival
                    fest_obj = next((f for f in self.festivals if f.get("name") == upcoming[0]), None)
                    if fest_obj:
                        catalog = fest_obj.get("catalog_products", [])
                        if catalog:
                            in_stock_count = 0
                            for item_name in catalog:
                                # Find product by name or substring
                                p = next((p for p in self.products if item_name.lower() in p.get("name", "").lower()), None)
                                if p and float(p.get("current_stock", 0)) > float(p.get("reorder_threshold", 0)):
                                    in_stock_count += 1
                            pct = round((in_stock_count / len(catalog)) * 100)
                            self.caches["festival_readiness"] = {
                                "festival": upcoming[0],
                                "readiness_pct": pct,
                                "total_catalog": len(catalog),
                                "ready_count": in_stock_count
                            }
                else:
                    self.caches["festival_summary"] = "No major upcoming festivals found for the current year."
            else:
                self.caches["festival_summary"] = "Festival calendar unavailable."

            # 7. Inventory Health Metrics
            total_items = len(self.products)
            if total_items > 0:
                low_stock_count = len(self.caches["low_stock"])
                dead_stock_count = len(self.caches["dead_stock"])
                healthy_count = total_items - low_stock_count - dead_stock_count
                
                self.caches["inventory_health"] = {
                    "healthy_pct": round((healthy_count / total_items) * 100, 1),
                    "low_stock_pct": round((low_stock_count / total_items) * 100, 1),
                    "dead_stock_pct": round((dead_stock_count / total_items) * 100, 1),
                    "stockout_risk_items": low_stock_count
                }

            # 8. Supplier Intelligence
            if self.suppliers:
                supplier_stats = []
                for s in self.suppliers:
                    s_name = s.get("name")
                    s_prods = [p for p in self.products if p.get("supplier_name") == s_name]
                    if s_prods:
                        avg_lead = sum(float(p.get("lead_time_days", 0)) for p in s_prods) / len(s_prods)
                        supplier_stats.append({
                            "name": s_name,
                            "product_count": len(s_prods),
                            "avg_lead_time": round(avg_lead, 1)
                        })
                
                # Sort by product count as a proxy for "importance"
                supplier_stats.sort(key=lambda x: x["product_count"], reverse=True)
                self.caches["supplier_intel"] = supplier_stats[:5] # Keep top 5

            # 9. Supplier mapping, performance, upcoming stock, discounts, stockout
            self._refresh_supplier_order_caches()

        except Exception as e:
            logger.error(f"Error refreshing caches: {e}")

    def _refresh_expiry_cache(self):
        """Load inventory_batches.csv and build a compact expiry summary."""
        try:
            batches_path = os.path.join(DATA_DIR, "inventory_batches.csv")
            if not os.path.exists(batches_path):
                return

            try:
                from routes.expiry import sync_expired_batches
                df = sync_expired_batches(batches_path)
            except Exception as sync_err:
                logger.error(f"[ChatbotData] Failed to sync expired batch statuses: {sync_err}")
                df = pd.read_csv(batches_path).fillna("")
            if df.empty:
                return

            prod_price = {str(p.get("sku", "")).strip().upper(): float(p.get("unit_price", 0) or 0) for p in self.products}
            today = datetime.datetime.now()

            status_counts = {"Healthy": 0, "Monitor": 0, "Caution": 0, "High Risk": 0, "Expiring Soon": 0, "Expired": 0}
            soon_batches = []
            expired_batches = []
            expiring_7_days = []
            expiring_15_days = []
            expiring_30_days = []
            total_active_batches = 0
            at_risk_value = 0.0
            disposed_count = int((df["status"] == "disposed").sum()) if "status" in df.columns else 0

            for _, row in df.iterrows():
                if row.get("status") not in ("active", "expired"):
                    continue
                sku = str(row.get("sku", "")).strip().upper()
                qty = float(row.get("quantity", 0) or 0)
                if qty <= 0:
                    continue

                try:
                    expiry_dt = datetime.datetime.strptime(str(row.get("expiry_date")), "%Y-%m-%d")
                    days_left = (expiry_dt - today).days
                except Exception:
                    days_left = 999

                if days_left <= 0:
                    status = "Expired"
                elif days_left <= 7:
                    status = "Expiring Soon"
                elif days_left <= 15:
                    status = "High Risk"
                elif days_left <= 30:
                    status = "Caution"
                elif days_left <= 60:
                    status = "Monitor"
                else:
                    status = "Healthy"

                total_active_batches += 1
                status_counts[status] += 1
                value = qty * prod_price.get(sku, 0.0)
                if status in ("High Risk", "Expiring Soon", "Caution"):
                    at_risk_value += value

                entry = {
                    "sku": sku,
                    "product_name": row.get("product_name", sku),
                    "batch_no": row.get("batch_no", ""),
                    "quantity": qty,
                    "expiry_date": row.get("expiry_date", ""),
                    "days_left": days_left,
                    "status": status,
                }
                if status == "Expired":
                    expired_batches.append(entry)
                elif status in ("Expiring Soon", "High Risk"):
                    soon_batches.append(entry)

                if 0 < days_left <= 7:
                    expiring_7_days.append(entry)
                if 0 < days_left <= 15:
                    expiring_15_days.append(entry)
                if 0 < days_left <= 30:
                    expiring_30_days.append(entry)

            soon_batches.sort(key=lambda x: x["days_left"])
            expired_batches.sort(key=lambda x: x["days_left"])
            expiring_7_days.sort(key=lambda x: x["days_left"])
            expiring_15_days.sort(key=lambda x: x["days_left"])
            expiring_30_days.sort(key=lambda x: x["days_left"])

            self.caches["expiry_summary"] = {
                "total_active_batches": total_active_batches,
                "status_counts": status_counts,
                "at_risk_value": round(at_risk_value, 2),
                "disposed_count": disposed_count,
            }
            self.caches["expiry_soon_batches"] = soon_batches[:15]
            self.caches["expiry_expired_batches"] = expired_batches[:15]
            self.caches["expiring_7_days"] = expiring_7_days[:15]
            self.caches["expiring_15_days"] = expiring_15_days[:15]
            self.caches["expiring_30_days"] = expiring_30_days[:15]
        except Exception as e:
            logger.error(f"[ChatbotData] Error refreshing expiry cache: {e}")

    def _refresh_supplier_order_caches(self):
        """Build supplier mapping, performance metrics, upcoming stock, discounts, and stockout caches."""
        try:
            # 1. Supplier ↔ Product mapping
            sku_to_suppliers: Dict[str, List[str]] = {}
            supplier_to_skus: Dict[str, List[str]] = {}
            for row in self.supplier_products:
                sid = str(row.get("supplier_id", "")).strip().upper()
                sku = str(row.get("sku", "")).strip().upper()
                if not sid or not sku:
                    continue
                sku_to_suppliers.setdefault(sku, []).append(sid)
                supplier_to_skus.setdefault(sid, []).append(sku)

            self.caches["supplier_mapping"] = {
                "sku_to_suppliers": sku_to_suppliers,
                "supplier_to_skus": supplier_to_skus,
                "total_mappings": len(self.supplier_products)
            }

            # 2. Supplier performance metrics (using PO history)
            supplier_perf = []
            for s in self.suppliers:
                sid = str(s.get("supplier_id", "")).strip().upper()
                if not sid:
                    continue
                metrics = calc_metrics(sid, self.purchase_orders)
                supplier_perf.append({
                    "supplier_id": sid,
                    "name": s.get("name", ""),
                    "company_name": s.get("company_name", ""),
                    "contact_person": s.get("contact_person", ""),
                    "phone": s.get("phone", ""),
                    "email": s.get("email", ""),
                    "lead_time_days": s.get("default_lead_time_days", ""),
                    "status": s.get("status", ""),
                    "product_count": len(supplier_to_skus.get(sid, [])),
                    **metrics
                })
            supplier_perf.sort(key=lambda x: x.get("reliability_score", 0), reverse=True)
            self.caches["supplier_performance"] = supplier_perf
            if supplier_perf:
                self.caches["best_supplier_overall"] = supplier_perf[0]

            # 3. Best supplier per product (mapped products only)
            best_per_product: Dict[str, List[Dict]] = {}
            for sku, sids in sku_to_suppliers.items():
                candidates = []
                for sid in sids:
                    s = self.supplier_lookup.get(sid)
                    metrics = next((p for p in supplier_perf if p.get("supplier_id") == sid), None)
                    if not s or not metrics:
                        continue
                    candidates.append({
                        "supplier_id": sid,
                        "name": s.get("name", ""),
                        "reliability_score": metrics.get("reliability_score", 0),
                        "on_time_pct": metrics.get("on_time_pct", 0),
                        "avg_lead_time": metrics.get("avg_lead_time", 0),
                        "quality_rating": metrics.get("quality_rating", 0),
                        "fill_rate": metrics.get("fill_rate", 0),
                    })
                candidates.sort(key=lambda x: x.get("reliability_score", 0), reverse=True)
                if candidates:
                    best_per_product[sku] = candidates
            self.caches["best_suppliers_per_product"] = best_per_product

            # 4. Upcoming stock (POs not yet received or cancelled)
            today = datetime.datetime.now()
            upcoming = []
            upcoming_total = 0.0
            for po in self.purchase_orders:
                status = str(po.get("status", "")).strip().lower()
                if status in ("received", "cancelled"):
                    continue
                sku = str(po.get("sku", "")).strip().upper()
                qty = float(po.get("ordered_qty", 0) or 0)
                if qty <= 0:
                    continue
                expected = po.get("expected_delivery_date", "")
                days_to_delivery = None
                try:
                    exp_dt = datetime.datetime.strptime(str(expected)[:10], "%Y-%m-%d")
                    days_to_delivery = (exp_dt - today).days
                except Exception:
                    pass
                product_name = po.get("product_name", self.product_lookup.get(sku, {}).get("name", sku))
                upcoming.append({
                    "sku": sku,
                    "product_name": product_name,
                    "po_number": po.get("po_number", ""),
                    "supplier_name": po.get("supplier_name", ""),
                    "qty": qty,
                    "expected_delivery_date": expected,
                    "days_to_delivery": days_to_delivery,
                    "status": status,
                })
                upcoming_total += qty
            upcoming.sort(key=lambda x: x.get("days_to_delivery") if x.get("days_to_delivery") is not None else 9999)
            self.caches["upcoming_stock"] = upcoming
            self.caches["upcoming_stock_total"] = upcoming_total

            # 5. Discounts
            active = self.discounts.get("active_discounts", []) or []
            recs = self.discounts.get("recommendations", []) or []
            pending_recs = [r for r in recs if str(r.get("status", "")).lower() == "pending"]
            approved_recs = [r for r in recs if str(r.get("status", "")).lower() == "approved"]
            self.caches["active_discounts"] = active
            self.caches["pending_discount_recommendations"] = pending_recs
            self.caches["discounts_summary"] = (
                f"Active discounts: {len(active)}. "
                f"Pending recommendations: {len(pending_recs)}. "
                f"Approved lifetime: {len(approved_recs)}. "
                f"Total recommendations: {len(recs)}."
            )

            # 6. Stockout products
            stockout = []
            for p in self.products:
                stock = float(p.get("current_stock", 0) or 0)
                if stock <= 0:
                    stockout.append({
                        "sku": str(p.get("sku", "")).strip().upper(),
                        "name": p.get("name", ""),
                        "category": p.get("category", ""),
                        "unit_price": float(p.get("unit_price", 0) or 0),
                    })
            self.caches["stockout_products"] = stockout

        except Exception as e:
            logger.error(f"[ChatbotData] Error refreshing supplier/order caches: {e}")

    def get_suppliers_for_sku(self, sku: str) -> List[Dict]:
        """Return mapped supplier details for a given SKU."""
        sku = str(sku).strip().upper()
        mapping = self.caches.get("supplier_mapping", {})
        sids = mapping.get("sku_to_suppliers", {}).get(sku, [])
        return [self.supplier_lookup.get(sid, {"supplier_id": sid, "name": sid}) for sid in sids]

    def get_best_supplier_for_sku(self, sku: str) -> Optional[Dict]:
        """Return the top-ranked supplier for a given SKU."""
        sku = str(sku).strip().upper()
        best = self.caches.get("best_suppliers_per_product", {}).get(sku, [])
        return best[0] if best else None

    def get_upcoming_stock_for_sku(self, sku: str) -> List[Dict]:
        """Return upcoming PO rows for a given SKU."""
        sku = str(sku).strip().upper()
        return [u for u in self.caches.get("upcoming_stock", []) if u.get("sku") == sku]

    def get_discounts_by_status(self, status: str) -> List[Dict]:
        """Return discounts by status: active, pending, approved, rejected."""
        status = status.lower()
        if status == "active":
            return self.discounts.get("active_discounts", []) or []
        if status == "pending":
            return self.caches.get("pending_discount_recommendations", [])
        recs = self.discounts.get("recommendations", []) or []
        if status in ("approved", "rejected"):
            return [r for r in recs if str(r.get("status", "")).lower() == status]
        return recs

    def get_product(self, sku_or_name: str) -> Optional[Dict]:
        """Fast lookup by SKU or Name."""
        sku_clean = sku_or_name.strip().upper()
        if sku_clean in self.product_lookup:
            return self.product_lookup[sku_clean]
        
        # Search by name if not SKU
        for p in self.products:
            if sku_or_name.lower() in str(p.get("name", "")).lower():
                return p
        return None

    def get_context_summary(self) -> str:
        """Lightweight context for LLM if cache is fresh."""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d")
        today_recs = self.brief_log.get(now_str, {}).get("items", [])
        decided_skus = {o.get("sku") for o in self.overrides if (o.get("timestamp") or "").startswith(now_str)}
        pending_review_count = len([i for i in today_recs if i.get("sku") not in decided_skus])

        lines = [
            self.caches["inventory_summary"],
            f"PENDING REVIEWS (TODAY): {pending_review_count} items.",
            f"STOCKOUT RISK: {len(self.caches['low_stock'])} items.",
            f"DEAD STOCK (>30 days): {len(self.caches.get('dead_stock', []))} items.",
            f"SLOW MOVING (15-30 days): {len(self.caches.get('slow_stock', []))} items.",
            f"PENDING ORDERS: {len(self.caches['pending_orders'])}.",
            self.caches["supplier_summary"]
        ]
        return "\n".join(lines)

# Global Instance
data_manager = ChatbotDataManager()
