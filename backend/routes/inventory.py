from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

from middleware.auth_middleware import verify_token, require_role, require_any_role
from logic.pattern_detector import analyse_sku, load_sales, load_products_dynamic
from logic.reorder_calculator import calculate_reorder
from logic.chatbot_data import data_manager

def _refresh_chatbot_inventory():
    """Trigger chatbot data reload so live context includes new inventory data instantly."""
    import threading
    def _run():
        try:
            data_manager.reload_all()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True).start()

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PRODUCTS_CSV = os.path.join(DATA_DIR, "products.csv")
SUPPLIERS_CSV = os.path.join(DATA_DIR, "suppliers.csv")


def load_products():
    return load_products_dynamic()


def save_products(products: list):
    columns = ["sku", "name", "unit", "current_stock", "reorder_threshold", "supplier_name", "lead_time_days", "category", "notes", "unit_price"]
    df = pd.DataFrame(products)
    existing_cols = [c for c in columns if c in df.columns]
    df_to_save = df[existing_cols]
    df_to_save.to_csv(PRODUCTS_CSV, index=False)


def sync_batches_to_stock(sku: str, new_stock: float):
    batches_csv = os.path.join(DATA_DIR, "inventory_batches.csv")
    if not os.path.exists(batches_csv):
        return
    try:
        bdf = pd.read_csv(batches_csv)
        sku_mask = (bdf['sku'].astype(str).str.strip().str.upper() == sku.strip().upper())
        if not sku_mask.any():
            # If no batches exist for this product, let's create a new batch!
            products_path = os.path.join(DATA_DIR, "products.csv")
            prod_name = sku
            supplier = "Unknown"
            if os.path.exists(products_path):
                try:
                    pdf = pd.read_csv(products_path)
                    p_row = pdf[pdf['sku'].astype(str).str.strip().str.upper() == sku.strip().upper()]
                    if not p_row.empty:
                        prod_name = str(p_row.iloc[0]['name'])
                        supplier = str(p_row.iloc[0].get('supplier_name', 'Unknown'))
                except:
                    pass
            new_batch = {
                "sku": sku,
                "batch_no": f"BN-{sku}-01",
                "quantity": new_stock,
                "mfg_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "expiry_date": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                "status": "active",
                "received_date": datetime.now().strftime("%Y-%m-%d"),
                "product_name": prod_name,
                "supplier": supplier
            }
            bdf = pd.concat([bdf, pd.DataFrame([new_batch])], ignore_index=True)
            bdf.to_csv(batches_csv, index=False)
            return
            
        bdf['expiry_date_dt'] = pd.to_datetime(bdf['expiry_date'], errors='coerce')
        today_dt = pd.to_datetime(datetime.now().date())
        
        # Identify active/non-expired batches for this SKU
        active_mask = sku_mask & (bdf['status'] == 'active') & ((bdf['expiry_date_dt'] > today_dt) | bdf['expiry_date_dt'].isna())
        active_indices = bdf[active_mask].index.tolist()
        
        if not active_indices:
            # Create a new active batch for this SKU since all existing batches are expired/None
            first_row = bdf[sku_mask].iloc[0]
            new_batch = {
                "sku": sku,
                "batch_no": f"BN-{sku}-{len(bdf[sku_mask]) + 1:02d}",
                "quantity": new_stock,
                "mfg_date": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "expiry_date": (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                "status": "active",
                "received_date": datetime.now().strftime("%Y-%m-%d"),
                "product_name": first_row.get("product_name", sku),
                "supplier": first_row.get("supplier", "Unknown")
            }
            bdf.drop(columns=['expiry_date_dt'], inplace=True, errors='ignore')
            bdf = pd.concat([bdf, pd.DataFrame([new_batch])], ignore_index=True)
            bdf.to_csv(batches_csv, index=False)
            return
            
        # Back-allocate the stock to active batches (adjust newer ones first)
        remaining = new_stock
        for idx in reversed(active_indices):
            if remaining <= 0:
                bdf.at[idx, 'quantity'] = 0.0
            else:
                if idx == active_indices[0]:
                    bdf.at[idx, 'quantity'] = max(0.0, remaining)
                else:
                    val = float(bdf.at[idx, 'quantity'])
                    if val <= remaining:
                        remaining -= val
                    else:
                        bdf.at[idx, 'quantity'] = remaining
                        remaining = 0.0
                        
        bdf.drop(columns=['expiry_date_dt'], inplace=True, errors='ignore')
        bdf.to_csv(batches_csv, index=False)
    except Exception as e:
        logger.error(f"Failed to sync batches to manual stock update: {e}")


def deduct_stock_for_sales(rows: list) -> None:
    """Deduct stock from products.csv and inventory_batches.csv (FEFO) for a list
    of sales rows.  Each row must contain 'StockCode' (SKU) and 'Quantity' keys.
    Quantities are aggregated per SKU before writing, so one file update per SKU.
    Call this after appending new rows to sales.csv.
    """
    from collections import defaultdict
    sku_qty: dict = defaultdict(float)
    for r in rows:
        sku = str(r.get("StockCode", "")).strip()
        try:
            qty = float(r.get("Quantity", 0) or 0)
        except (ValueError, TypeError):
            qty = 0.0
        if sku and qty > 0:
            sku_qty[sku] += qty

    if not sku_qty:
        return

    products_csv = os.path.join(DATA_DIR, "products.csv")
    if os.path.exists(products_csv):
        try:
            pdf = pd.read_csv(products_csv, dtype=str).fillna("")
            changed = False
            for sku, qty in sku_qty.items():
                pmask = pdf["sku"].astype(str).str.strip().str.upper() == sku.upper()
                if pmask.any():
                    cur = float(pdf.loc[pmask, "current_stock"].values[0] or 0)
                    pdf.loc[pmask, "current_stock"] = str(max(0.0, round(cur - qty, 4)))
                    changed = True
            if changed:
                tmp = products_csv + ".tmp"
                pdf.to_csv(tmp, index=False)
                os.replace(tmp, products_csv)
        except Exception as e:
            logger.error("deduct_stock_for_sales: failed to update products.csv: %s", e)

    batches_csv = os.path.join(DATA_DIR, "inventory_batches.csv")
    if not os.path.exists(batches_csv):
        return
    try:
        bdf = pd.read_csv(batches_csv)
        bdf["expiry_date_dt"] = pd.to_datetime(bdf["expiry_date"], errors="coerce")
        today_dt = pd.to_datetime(datetime.now().date())
        modified = False

        for sku, qty in sku_qty.items():
            sku_mask = bdf["sku"].astype(str).str.strip().str.upper() == sku.upper()
            active_mask = (
                sku_mask
                & (bdf["status"] == "active")
                & (bdf["quantity"].astype(float) > 0)
                & ((bdf["expiry_date_dt"] > today_dt) | bdf["expiry_date_dt"].isna())
            )
            active_batches = bdf[active_mask].sort_values(
                "expiry_date_dt", ascending=True, na_position="last"
            )
            remaining = float(qty)
            for idx in active_batches.index:
                if remaining <= 0:
                    break
                batch_qty = float(bdf.at[idx, "quantity"])
                deduct = min(batch_qty, remaining)
                bdf.at[idx, "quantity"] = round(batch_qty - deduct, 4)
                remaining -= deduct
                modified = True

        bdf.drop(columns=["expiry_date_dt"], inplace=True, errors="ignore")
        if modified:
            tmp = batches_csv + ".tmp"
            bdf.to_csv(tmp, index=False)
            os.replace(tmp, batches_csv)
    except Exception as e:
        logger.error("deduct_stock_for_sales: failed to update inventory_batches.csv: %s", e)


def load_suppliers():
    df = pd.read_csv(SUPPLIERS_CSV)
    return df.fillna("").to_dict(orient="records")


def save_suppliers(suppliers: list):
    df = pd.DataFrame(suppliers)
    df.to_csv(SUPPLIERS_CSV, index=False)


def get_incoming_stock(sku: str) -> float:
    """Sum quantities of all orders and supplier POs with status 'approved' or 'ordered'."""
    from .orders import load_overrides
    overrides = load_overrides()
    sku_upper = str(sku).strip().upper()
    # Only count items that have an explicit 'status' field (modern orders) and have no po_id (avoid double counting)
    pending = [o for o in overrides if str(o.get("sku", "")).strip().upper() == sku_upper and o.get("status") in ("approved", "ordered") and not o.get("po_id")]
    total = sum(float(o.get("actual_qty", 0)) for o in pending)

    # Also count manually created supplier POs that are still in 'ordered' status.
    po_csv = os.path.join(DATA_DIR, "purchase_orders.csv")
    if os.path.exists(po_csv):
        try:
            pdf = pd.read_csv(po_csv).fillna("")
            po_pending = pdf[
                (pdf["sku"].astype(str).str.strip().str.upper() == sku_upper) &
                (pdf["status"].astype(str).str.strip().str.lower().isin(["ordered", "approved"]))
            ]
            total += po_pending["ordered_qty"].astype(float).sum()
        except Exception as e:
            logger.error(f"Failed to include PO incoming stock for {sku}: {e}")
    return total


def enrich_product_fast(p: dict, avg_sales_map: dict, incoming_stock_map: dict = None, ai_stockout_map: dict = None) -> dict:
    try:
        current_stock = float(p.get("current_stock", 0))
        reorder_threshold = float(p.get("reorder_threshold", 0))
        avg_v = avg_sales_map.get(p["sku"], 0)
        
        # Fast status logic without full reorder calculation
        lead_time = int(p.get("lead_time_days", 7))
        days_remaining = round(current_stock / avg_v, 1) if avg_v > 0 else 999
        
        status = "ok"
        
        # Override with exact AI definitions for stockouts:
        if ai_stockout_map and p["sku"] in ai_stockout_map:
            days_remaining = ai_stockout_map[p["sku"]]
            status = "at_risk"
        elif days_remaining <= lead_time:
            status = "at_risk"
        elif avg_v > 0 and days_remaining > lead_time + 90:
            status = "overstocked"
            
        if incoming_stock_map is None:
            incoming = get_incoming_stock(p["sku"])
        else:
            incoming = incoming_stock_map.get(str(p["sku"]).strip().upper(), 0.0)
            
        
        return {
            **p, 
            "days_remaining": days_remaining,
            "status": status,
            "incoming_stock": incoming,
            "effective_stock": current_stock + incoming
        }
    except Exception:
        return {**p, "days_remaining": 999, "status": "ok"}


def enrich_product(p: dict, sales_df=None) -> dict:
    try:
        from logic.pattern_detector import analyse_sku
        from logic.reorder_calculator import calculate_reorder

        pattern = analyse_sku(p["sku"], sales_df)
        reorder = calculate_reorder(p, pattern)
        days_remaining = reorder["days_remaining"]
        lead_time = int(p.get("lead_time_days", 7))
        current_stock = float(p.get("current_stock", 0))
        reorder_threshold = float(p.get("reorder_threshold", 0))

        avg_daily = pattern.get("avg_daily_sales", 0)
        if reorder.get("risk_level") == "CRITICAL_STOCKOUT":
            status = "at_risk"
        elif avg_daily > 0 and days_remaining > lead_time + 90:
            status = "overstocked"
        else:
            status = "ok"

        incoming = get_incoming_stock(p["sku"])
        
        return {
            **p, 
            "days_remaining": days_remaining, 
            "urgency": reorder["urgency"], 
            "status": status,
            "incoming_stock": incoming,
            "effective_stock": current_stock + incoming
        }
    except Exception:
        return {**p, "days_remaining": 999, "urgency": "low", "status": "ok"}


class ProductCreate(BaseModel):
    sku: str
    name: str
    unit: str = "units"
    current_stock: float = 0
    reorder_threshold: float = 0
    supplier_name: str = ""
    lead_time_days: int = 7
    category: str = ""
    unit_price: float = 0
    notes: str = ""
    mfg_date: Optional[str] = None
    expiry_date: Optional[str] = None


class StockUpdate(BaseModel):
    current_stock: float


class SupplierCreate(BaseModel):
    supplier_id: str
    name: str
    contact_person: str = ""
    phone: str = ""
    email: str = ""
    default_lead_time_days: int = 7
    delivery_schedule: str = ""
    notes: str = ""


@router.get("/products")
def get_products(payload: dict = Depends(verify_token)):
    products_raw = load_products()
    if not products_raw:
        return []

    # load_products_dynamic() already returns one row per SKU with current_stock
    # correctly summed from active batches. We use it directly without re-aggregating.
    products = [{k: (v if v is not None else "") for k, v in p.items()} for p in products_raw]
    
    # ADJUST LEAD TIME based on expiry (Business Rule)
    BATCHES_CSV = os.path.join(DATA_DIR, "inventory_batches.csv")
    if os.path.exists(BATCHES_CSV):
        try:
            bdf = pd.read_csv(BATCHES_CSV)
            bdf['expiry_date'] = pd.to_datetime(bdf['expiry_date'])
            today = datetime.now()
            # min expiry per active sku
            active_b = bdf[(bdf['status'] == 'active') & (bdf['quantity'] > 0)]
            if not active_b.empty:
                min_exp = active_b.groupby('sku')['expiry_date'].min()
                expiry_map = (min_exp - today).dt.days.to_dict()
                
                for p in products:
                    sku = p['sku']
                    if sku in expiry_map:
                        exp_days = expiry_map[sku]
                        lt = int(p.get('lead_time_days', 7))
                        if exp_days <= lt:
                            p['lead_time_days'] = max(1, exp_days - 2)
        except Exception as e:
            logger.error(f"Lead time adjustment failed: {e}")
    
    # PERFORMANCE: Pre-calculate sales velocity for all products in ONE pass
    sales_df = load_sales()
    recent_sales = sales_df.groupby("StockCode")["Quantity"].sum().to_dict()
    
    # Calculate days passed in the current year (to avoid dividing by 365 when we only have partial year data)
    days_in_year = max(1, datetime.now().timetuple().tm_yday)
    avg_sales_map = {sku: qty/days_in_year for sku, qty in recent_sales.items()}
    
    # PERFORMANCE: Pre-calculate incoming stock map
    # Include BOTH manager decisions (override_history.json) AND manually created POs (purchase_orders.csv)
    try:
        from .orders import load_overrides
        overrides = load_overrides()
        incoming_stock_map = {}
        # 1. Manager decisions that are 'approved' or 'ordered'
        for o in overrides:
            if o.get("status") in ("approved", "ordered") and not o.get("po_id"):
                sku = str(o.get("sku", "")).strip().upper()
                if not sku: continue
                qty = float(o.get("actual_qty", 0))
                incoming_stock_map[sku] = incoming_stock_map.get(sku, 0.0) + qty
        # 2. Manually created POs from purchase_orders.csv that are still 'ordered'
        po_csv = os.path.join(DATA_DIR, "purchase_orders.csv")
        if os.path.exists(po_csv):
            try:
                po_df = pd.read_csv(po_csv).fillna("")
                po_pending = po_df[po_df["status"].astype(str).str.strip().str.lower().isin(["ordered", "approved"])]
                for _, row in po_pending.iterrows():
                    sku = str(row.get("sku", "")).strip().upper()
                    if not sku:
                        continue
                    qty = float(row.get("ordered_qty", 0) or 0)
                    incoming_stock_map[sku] = incoming_stock_map.get(sku, 0.0) + qty
            except Exception as e:
                logger.error(f"Failed to include PO incoming stock in map: {e}")
    except Exception:
        incoming_stock_map = {}
        
    # Align at-risk flags and days_remaining with the daily brief's critical stockouts
    ai_stockout_map = {}
    try:
        import json
        with open(os.path.join(DATA_DIR, "brief_log.json")) as f:
            brief_data = json.load(f)
            latest_date = max(brief_data.keys())
            for item in brief_data[latest_date].get("items", []):
                if item.get("risk_level") == "CRITICAL_STOCKOUT":
                    ai_stockout_map[item["sku"]] = float(item.get("days_remaining", 0))
    except Exception as e:
        logger.error(f"Failed to load brief_log.json: {e}")
        
    return [enrich_product_fast(p, avg_sales_map, incoming_stock_map, ai_stockout_map) for p in products]


@router.get("/products/{sku}")
def get_product(sku: str, payload: dict = Depends(verify_token)):
    products = load_products()
    p = next((x for x in products if x["sku"] == sku), None)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return enrich_product(p)


@router.post("/products")
def create_product(body: ProductCreate, payload: dict = Depends(require_any_role())):
    products = load_products()
    if any(p["sku"] == body.sku for p in products):
        raise HTTPException(status_code=409, detail="SKU already exists")
    
    product_dict = body.dict()
    # Strip batch-specific fields before saving to products CSV
    mfg_date = product_dict.pop("mfg_date", None)
    expiry_date = product_dict.pop("expiry_date", None)
    
    products.append(product_dict)
    save_products(products)
    
    # If initial stock > 0, create a batch in inventory_batches.csv
    if body.current_stock > 0:
        BATCHES_CSV = os.path.join(DATA_DIR, "inventory_batches.csv")
        try:
            batch_no = f"BN-{body.sku}-01"
            new_batch = {
                "sku": body.sku,
                "batch_no": batch_no,
                "quantity": body.current_stock,
                "mfg_date": mfg_date or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
                "expiry_date": expiry_date or (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d"),
                "status": "active",
                "received_date": datetime.now().strftime("%Y-%m-%d"),
                "product_name": body.name,
                "supplier": body.supplier_name or "Unknown"
            }
            if os.path.exists(BATCHES_CSV):
                bdf = pd.read_csv(BATCHES_CSV)
                bdf = pd.concat([bdf, pd.DataFrame([new_batch])], ignore_index=True)
            else:
                bdf = pd.DataFrame([new_batch])
            bdf.to_csv(BATCHES_CSV, index=False)
        except Exception as e:
            logger.error(f"Failed to create initial batch for {body.sku}: {e}")
    
    _refresh_chatbot_inventory()
    return product_dict


@router.put("/products/{sku}")
def update_product(sku: str, body: ProductCreate, payload: dict = Depends(require_any_role())):
    products = load_products()
    idx = next((i for i, p in enumerate(products) if p["sku"] == sku), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Product not found")
    products[idx] = body.dict()
    save_products(products)
    return body.dict()


@router.patch("/products/{sku}/stock")
def update_product_stock(sku: str, body: StockUpdate, payload: dict = Depends(require_any_role())):
    products = load_products()
    idx = next((i for i, p in enumerate(products) if p["sku"] == sku), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Product not found")
        
    new_stock = float(body.current_stock)
    sync_batches_to_stock(sku, new_stock)
    
    # Reload/Update product cache and save
    products[idx]["current_stock"] = new_stock
    save_products(products)
    
    _refresh_chatbot_inventory()
    return {"sku": sku, "current_stock": new_stock}


@router.delete("/products/{sku}")
def delete_product(sku: str, payload: dict = Depends(require_any_role())):
    products = load_products()
    products = [p for p in products if p["sku"] != sku]
    save_products(products)
    
    # Cascade delete: remove all batches for this SKU
    BATCHES_CSV = os.path.join(DATA_DIR, "inventory_batches.csv")
    if os.path.exists(BATCHES_CSV):
        try:
            bdf = pd.read_csv(BATCHES_CSV)
            bdf = bdf[bdf["sku"].astype(str).str.strip().str.upper() != sku.strip().upper()]
            bdf.to_csv(BATCHES_CSV, index=False)
        except Exception as e:
            logger.error(f"Failed to delete batches for {sku}: {e}")
    
    _refresh_chatbot_inventory()
    return {"message": "Product and all its batches deleted"}


@router.get("/suppliers")
def get_suppliers(payload: dict = Depends(verify_token)):
    suppliers = load_suppliers()
    products = load_products()
    result = []
    for s in suppliers:
        count = sum(1 for p in products if p.get("supplier_name") == s.get("name"))
        result.append({**s, "products_count": count})
    return result


@router.post("/suppliers")
def create_supplier(body: SupplierCreate, payload: dict = Depends(require_role("admin"))):
    suppliers = load_suppliers()
    if any(s["supplier_id"] == body.supplier_id for s in suppliers):
        raise HTTPException(status_code=409, detail="Supplier ID already exists")
    suppliers.append(body.dict())
    save_suppliers(suppliers)
    return body.dict()


@router.put("/suppliers/{sid}")
def update_supplier(sid: str, body: SupplierCreate, payload: dict = Depends(require_role("admin"))):
    suppliers = load_suppliers()
    idx = next((i for i, s in enumerate(suppliers) if s["supplier_id"] == sid), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    suppliers[idx] = body.dict()
    save_suppliers(suppliers)
    return body.dict()


@router.delete("/suppliers/{sid}")
def delete_supplier(sid: str, payload: dict = Depends(require_role("admin"))):
    suppliers = load_suppliers()
    suppliers = [s for s in suppliers if s["supplier_id"] != sid]
    save_suppliers(suppliers)
    return {"message": "Supplier deleted"}
@router.get("/batches")
def get_all_batches(sku: Optional[str] = None, payload: dict = Depends(verify_token)):
    BATCHES_CSV = os.path.join(DATA_DIR, "inventory_batches.csv")
    if not os.path.exists(BATCHES_CSV):
        return []
    
    try:
        df = pd.read_csv(BATCHES_CSV)
        if sku:
            df = df[df["sku"].str.upper() == sku.strip().upper()]
        
        # Sort by expiry date
        df["expiry_date_dt"] = pd.to_datetime(df["expiry_date"])
        df = df.sort_values("expiry_date_dt")
        df = df.drop(columns=["expiry_date_dt"])
        
        return df.fillna("").to_dict(orient="records")
    except Exception as e:
        logger.error(f"Failed to load batches: {e}")
        return []

@router.delete("/batches/{batch_no}")
def delete_batch(batch_no: str, payload: dict = Depends(require_role("admin"))):
    BATCHES_CSV = os.path.join(DATA_DIR, "inventory_batches.csv")
    if not os.path.exists(BATCHES_CSV):
        raise HTTPException(status_code=404, detail="Batch file not found")
    
    try:
        df = pd.read_csv(BATCHES_CSV)
        idx = df[df["batch_no"] == batch_no].index
        if idx.empty:
            raise HTTPException(status_code=404, detail="Batch not found")
        
        # Before deleting, we should ideally adjust the product stock
        # but manual deletion usually implies a correction.
        # For simplicity, we just delete the batch record.
        df = df.drop(idx)
        df.to_csv(BATCHES_CSV, index=False)
        _refresh_chatbot_inventory()
        return {"message": "Batch deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

