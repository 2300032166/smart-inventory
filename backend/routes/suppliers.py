from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os, uuid, logging
from datetime import datetime, timedelta

from middleware.auth_middleware import verify_token

logger = logging.getLogger(__name__)

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
SUPPLIERS_CSV        = os.path.join(DATA_DIR, "suppliers.csv")
SUPPLIER_PRODUCTS_CSV = os.path.join(DATA_DIR, "supplier_products.csv")
PURCHASE_ORDERS_CSV  = os.path.join(DATA_DIR, "purchase_orders.csv")
PRODUCTS_CSV         = os.path.join(DATA_DIR, "products.csv")


# ── Auth helper ───────────────────────────────────────────────

def require_manager_or_admin(payload: dict = Depends(verify_token)):
    if payload.get("role") not in ("manager", "admin"):
        raise HTTPException(status_code=403, detail="Access denied: manager or admin required")
    return payload


# ── Data helpers ──────────────────────────────────────────────

def load_suppliers():
    if not os.path.exists(SUPPLIERS_CSV):
        return []
    return pd.read_csv(SUPPLIERS_CSV).fillna("").to_dict(orient="records")


def save_suppliers(suppliers: list):
    cols = ["supplier_id","name","company_name","contact_person","phone","email",
            "address","status","default_lead_time_days","delivery_schedule","notes"]
    df = pd.DataFrame(suppliers)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    df[cols].to_csv(SUPPLIERS_CSV, index=False)


def load_sp():
    if not os.path.exists(SUPPLIER_PRODUCTS_CSV):
        return []
    return pd.read_csv(SUPPLIER_PRODUCTS_CSV).fillna("").to_dict(orient="records")


def save_sp(mappings: list):
    pd.DataFrame(mappings).to_csv(SUPPLIER_PRODUCTS_CSV, index=False)


def load_pos():
    if not os.path.exists(PURCHASE_ORDERS_CSV):
        return []
    return pd.read_csv(PURCHASE_ORDERS_CSV).fillna("").to_dict(orient="records")


def save_pos(orders: list):
    pd.DataFrame(orders).to_csv(PURCHASE_ORDERS_CSV, index=False)


def load_products_map() -> dict:
    """Return {sku: {name, category, unit, unit_price}} for fast lookups."""
    if not os.path.exists(PRODUCTS_CSV):
        return {}
    df = pd.read_csv(PRODUCTS_CSV).fillna("")
    return {str(r["sku"]): r.to_dict() for _, r in df.iterrows()}


def is_supplier_mapped_to_sku(supplier_id: str, sku: str) -> bool:
    sp = load_sp()
    return any(
        str(m.get("supplier_id", "")).strip().upper() == str(supplier_id).strip().upper()
        and str(m.get("sku", "")).strip().upper() == str(sku).strip().upper()
        for m in sp
    )


# ── Metrics calculation ────────────────────────────────────────

def _parse_date(value: str):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def calc_metrics(supplier_id: str, pos: list) -> dict:
    sup_pos   = [p for p in pos if str(p.get("supplier_id")) == supplier_id]
    received  = [p for p in sup_pos if p.get("status") == "received"]
    total     = len(sup_pos)
    total_rcv = len(received)

    if total == 0:
        return dict(total_orders=0, on_time_pct=0, avg_lead_time=0,
                    avg_delay=0, fill_rate=0, quality_rating=0,
                    acceptance_rate=0, reliability_score=0)

    on_time = 0
    total_delay = 0
    lead_times = []
    fill_rates = []
    ratings = []

    for p in received:
        try:
            act = datetime.strptime(str(p["actual_delivery_date"])[:10], "%Y-%m-%d")
            exp = datetime.strptime(str(p["expected_delivery_date"])[:10], "%Y-%m-%d")
            ord_d = datetime.strptime(str(p["order_date"])[:10], "%Y-%m-%d")
            lead_times.append((act - ord_d).days)
            if act <= exp:
                on_time += 1
            else:
                total_delay += (act - exp).days
        except Exception:
            pass

        try:
            oq = float(p.get("ordered_qty") or 0)
            rq = float(p.get("received_qty") or 0)
            if oq > 0:
                fill_rates.append(rq / oq * 100)
        except Exception:
            pass

        try:
            qr = p.get("quality_rating")
            if qr not in ("", None):
                ratings.append(float(qr))
        except Exception:
            pass

    on_time_pct   = round(on_time / total_rcv * 100, 1) if total_rcv else 0
    delayed       = total_rcv - on_time
    avg_delay     = round(total_delay / delayed, 1) if delayed > 0 else 0
    avg_lead      = round(sum(lead_times) / len(lead_times), 1) if lead_times else 0
    avg_fill      = round(sum(fill_rates) / len(fill_rates), 1) if fill_rates else 0
    avg_quality   = round(sum(ratings) / len(ratings), 2) if ratings else 0
    acceptance    = round(total_rcv / total * 100, 1)

    # Lead time score: lower = better; normalise against 14-day cap
    lead_score    = max(0.0, (1 - avg_lead / 14)) * 100
    quality_score = (avg_quality / 5) * 100

    reliability = round(
        on_time_pct  * 0.45 +
        lead_score   * 0.25 +
        avg_fill     * 0.20 +
        quality_score * 0.10,
        1
    )

    return dict(
        total_orders   = total,
        on_time_pct    = on_time_pct,
        avg_lead_time  = avg_lead,
        avg_delay      = avg_delay,
        fill_rate      = avg_fill,
        quality_rating = avg_quality,
        acceptance_rate = acceptance,
        reliability_score = reliability,
    )


def perf_level(score: float) -> str:
    if score >= 95: return "Excellent"
    if score >= 85: return "Very Good"
    if score >= 70: return "Good"
    if score >= 50: return "Average"
    return "Poor"


def stars(score: float) -> float:
    return round(score / 20, 1)


def enrich(s: dict, pos: list) -> dict:
    m = calc_metrics(s["supplier_id"], pos)
    return {**s, **m, "performance_level": perf_level(m["reliability_score"]),
            "stars": stars(m["reliability_score"])}


def supplier_data_snapshot() -> tuple:
    """Return (suppliers, supplier_products, purchase_orders) for reuse across calls."""
    return load_suppliers(), load_sp(), load_pos()


def _build_supplier_reasons(e: dict) -> list:
    reasons = []
    if e.get("reliability_score", 0) >= 85:
        reasons.append("High Reliability Score")
    if e.get("on_time_pct", 0) >= 90:
        reasons.append("Excellent Delivery Performance")
    if e.get("avg_lead_time", 0) <= 5:
        reasons.append("Short Lead Time")
    if e.get("fill_rate", 0) >= 95:
        reasons.append("High Fill Rate")
    if e.get("quality_rating", 0) >= 4.2:
        reasons.append("High Product Quality")
    return reasons


def recommend_for_sku(sku: str, data: tuple = None) -> dict:
    """Recommend the best supplier for a product based on mapped suppliers and performance."""
    suppliers, sp, pos = data if data is not None else supplier_data_snapshot()
    mapped = [m for m in sp if str(m.get("sku", "")).strip().upper() == str(sku).strip().upper()]
    if not mapped:
        return {"recommended": None, "all_suppliers": []}

    result = []
    for m in mapped:
        s = next(
            (x for x in suppliers
             if x["supplier_id"] == m.get("supplier_id")
             and x.get("status", "Active") != "Inactive"),
            None,
        )
        if not s:
            continue
        e = enrich(s, pos)
        e["reasons"] = _build_supplier_reasons(e)
        result.append(e)

    result.sort(key=lambda x: x.get("reliability_score", 0), reverse=True)
    for i, s in enumerate(result):
        s["rank"] = i + 1
    return {"recommended": result[0] if result else None, "all_suppliers": result}


# ── Pydantic models ───────────────────────────────────────────

class SupplierIn(BaseModel):
    supplier_id: str
    name: str
    company_name: str = ""
    contact_person: str = ""
    phone: str = ""
    email: str = ""
    address: str = ""
    status: str = "Active"
    default_lead_time_days: int = 7
    delivery_schedule: str = ""
    notes: str = ""


class MappingIn(BaseModel):
    supplier_id: str
    sku: str
    category: str = ""


class POCreate(BaseModel):
    supplier_id: str
    supplier_name: str = ""
    sku: str
    product_name: str = ""
    ordered_qty: float
    order_date: str
    expected_delivery_date: str
    notes: str = ""


class POUpdate(BaseModel):
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    sku: Optional[str] = None
    product_name: Optional[str] = None
    ordered_qty: Optional[float] = None
    order_date: Optional[str] = None
    expected_delivery_date: Optional[str] = None
    notes: Optional[str] = None


class POReceive(BaseModel):
    received_qty: float
    actual_delivery_date: str
    quality_rating: Optional[int] = None


class PORate(BaseModel):
    quality_rating: int


# ═══════════════════════════════════════════════════════════════
#  SUPPLIER CRUD
# ═══════════════════════════════════════════════════════════════

@router.get("")
def list_suppliers(payload: dict = Depends(require_manager_or_admin)):
    suppliers = load_suppliers()
    pos = load_pos()
    result = [enrich(s, pos) for s in suppliers]
    result.sort(key=lambda x: x["reliability_score"], reverse=True)
    for i, s in enumerate(result):
        s["rank"] = i + 1
    return result


@router.post("")
def create_supplier(body: SupplierIn, payload: dict = Depends(require_manager_or_admin)):
    suppliers = load_suppliers()
    if any(s["supplier_id"] == body.supplier_id for s in suppliers):
        raise HTTPException(status_code=409, detail="Supplier ID already exists")
    rec = body.dict()
    suppliers.append(rec)
    save_suppliers(suppliers)
    return rec


@router.get("/metrics/all")
def all_metrics(payload: dict = Depends(require_manager_or_admin)):
    """All suppliers with computed metrics — used for comparison page."""
    suppliers = load_suppliers()
    pos = load_pos()
    result = [enrich(s, pos) for s in suppliers
              if s.get("status", "Active") != "Inactive"]
    result.sort(key=lambda x: x["reliability_score"], reverse=True)
    for i, s in enumerate(result):
        s["rank"] = i + 1
    return result


@router.get("/recommendation/{sku}")
def recommend(sku: str, payload: dict = Depends(require_manager_or_admin)):
    return recommend_for_sku(sku)


@router.get("/{sid}")
def get_supplier(sid: str, payload: dict = Depends(require_manager_or_admin)):
    suppliers = load_suppliers()
    s = next((x for x in suppliers if x["supplier_id"] == sid), None)
    if not s:
        raise HTTPException(status_code=404, detail="Supplier not found")
    pos = load_pos()
    sp  = load_sp()
    e   = enrich(s, pos)

    skus = [m["sku"] for m in sp if m["supplier_id"] == sid]
    products = []
    if skus and os.path.exists(PRODUCTS_CSV):
        pdf = pd.read_csv(PRODUCTS_CSV).fillna("")
        products = pdf[pdf["sku"].isin(skus)][
            ["sku", "name", "category", "unit", "unit_price", "current_stock"]
        ].to_dict(orient="records")

    sup_pos = sorted(
        [p for p in pos if p.get("supplier_id") == sid],
        key=lambda x: x.get("order_date", ""), reverse=True
    )
    e["mapped_products"] = products
    e["recent_orders"]   = sup_pos[:15]
    return e


@router.put("/{sid}")
def update_supplier(sid: str, body: SupplierIn, payload: dict = Depends(require_manager_or_admin)):
    suppliers = load_suppliers()
    idx = next((i for i, s in enumerate(suppliers) if s["supplier_id"] == sid), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    suppliers[idx] = body.dict()
    save_suppliers(suppliers)
    return body.dict()


@router.delete("/{sid}")
def disable_supplier(sid: str, payload: dict = Depends(require_manager_or_admin)):
    suppliers = load_suppliers()
    idx = next((i for i, s in enumerate(suppliers) if s["supplier_id"] == sid), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    suppliers[idx]["status"] = "Inactive"
    save_suppliers(suppliers)
    return {"message": "Supplier disabled"}


# ═══════════════════════════════════════════════════════════════
#  PRODUCT MAPPINGS
# ═══════════════════════════════════════════════════════════════

@router.get("/{sid}/products")
def supplier_products(sid: str, payload: dict = Depends(require_manager_or_admin)):
    sp  = load_sp()
    pmap = load_products_map()
    result = []
    for m in sp:
        if m["supplier_id"] != sid:
            continue
        p = pmap.get(str(m["sku"]), {})
        result.append({
            "supplier_id": sid,
            "sku": m["sku"],
            "category": m.get("category", p.get("category", "")),
            "product_name": p.get("name", ""),
            "unit": p.get("unit", ""),
            "unit_price": p.get("unit_price", ""),
            "current_stock": p.get("current_stock", ""),
        })
    return result


@router.get("/product/{sku}/suppliers")
def product_suppliers(sku: str, payload: dict = Depends(require_manager_or_admin)):
    sp        = load_sp()
    suppliers = load_suppliers()
    pos       = load_pos()
    result = []
    for m in sp:
        if m["sku"] != sku:
            continue
        s = next((x for x in suppliers if x["supplier_id"] == m["supplier_id"]), None)
        if s:
            e = enrich(s, pos)
            result.append(e)
    result.sort(key=lambda x: x["reliability_score"], reverse=True)
    return result


@router.post("/mappings")
def add_mapping(body: MappingIn, payload: dict = Depends(require_manager_or_admin)):
    sp = load_sp()
    if any(m["supplier_id"] == body.supplier_id and m["sku"] == body.sku for m in sp):
        raise HTTPException(status_code=409, detail="Mapping already exists")
    if not body.category and os.path.exists(PRODUCTS_CSV):
        pdf = pd.read_csv(PRODUCTS_CSV)
        row = pdf[pdf["sku"] == body.sku]
        if not row.empty:
            body.category = str(row.iloc[0].get("category", ""))
    sp.append(body.dict())
    save_sp(sp)
    return body.dict()


@router.delete("/mappings/{sid}/{sku}")
def remove_mapping(sid: str, sku: str, payload: dict = Depends(require_manager_or_admin)):
    sp = load_sp()
    sp = [m for m in sp if not (m["supplier_id"] == sid and m["sku"] == sku)]
    save_sp(sp)
    return {"message": "Mapping removed"}


# ═══════════════════════════════════════════════════════════════
#  PURCHASE ORDERS
# ═══════════════════════════════════════════════════════════════

@router.get("/purchase-orders/list")
def list_pos(
    supplier_id: Optional[str] = Query(None),
    status:      Optional[str] = Query(None),
    date_from:   Optional[str] = Query(None),
    date_to:     Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=500),
    payload: dict = Depends(require_manager_or_admin),
):
    pos = load_pos()
    if supplier_id: pos = [p for p in pos if p.get("supplier_id") == supplier_id]
    if status:      pos = [p for p in pos if p.get("status") == status]
    if date_from:   pos = [p for p in pos if p.get("order_date", "") >= date_from]
    if date_to:     pos = [p for p in pos if p.get("order_date", "") <= date_to]
    pos.sort(key=lambda x: x.get("order_date", ""), reverse=True)
    total = len(pos)
    start = (page - 1) * limit
    return {"total": total, "page": page, "limit": limit, "items": pos[start: start + limit]}


@router.post("/purchase-orders")
def create_po(body: POCreate, payload: dict = Depends(require_manager_or_admin)):
    order_date = _parse_date(body.order_date)
    expected_date = _parse_date(body.expected_delivery_date)
    if order_date is None or expected_date is None:
        raise HTTPException(status_code=400, detail="Invalid order or expected delivery date")
    if expected_date < order_date:
        raise HTTPException(status_code=400, detail="Expected delivery date cannot be before order date")
    if not is_supplier_mapped_to_sku(body.supplier_id, body.sku):
        raise HTTPException(status_code=400, detail="Selected supplier is not mapped to this product")

    pos = load_pos()
    if not body.supplier_name:
        sups = load_suppliers()
        s = next((x for x in sups if x["supplier_id"] == body.supplier_id), None)
        if s: body.supplier_name = s.get("name", "")
    if not body.product_name and os.path.exists(PRODUCTS_CSV):
        pdf = pd.read_csv(PRODUCTS_CSV)
        row = pdf[pdf["sku"] == body.sku]
        if not row.empty: body.product_name = str(row.iloc[0]["name"])

    po = {
        "po_id":                   str(uuid.uuid4()),
        "po_number":               f"PO-{len(pos) + 2000}",
        "supplier_id":             body.supplier_id,
        "supplier_name":           body.supplier_name,
        "sku":                     body.sku,
        "product_name":            body.product_name,
        "ordered_qty":             body.ordered_qty,
        "received_qty":            0,
        "order_date":              body.order_date,
        "expected_delivery_date":  body.expected_delivery_date,
        "actual_delivery_date":    "",
        "status":                  "ordered",
        "quality_rating":          "",
        "notes":                   body.notes,
        "created_by":              payload.get("sub"),
    }
    pos.append(po)
    save_pos(pos)
    return po


@router.put("/purchase-orders/{po_id}")
def update_po(po_id: str, body: POUpdate, payload: dict = Depends(require_manager_or_admin)):
    pos = load_pos()
    idx = next((i for i, p in enumerate(pos) if p["po_id"] == po_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="PO not found")
    if pos[idx].get("status") == "received":
        raise HTTPException(status_code=400, detail="Cannot edit a received PO")

    # Validate date ordering if either date is being changed.
    raw_order = body.order_date if body.order_date is not None else pos[idx].get("order_date")
    raw_expected = body.expected_delivery_date if body.expected_delivery_date is not None else pos[idx].get("expected_delivery_date")
    order_date = _parse_date(raw_order)
    expected_date = _parse_date(raw_expected)
    if (body.order_date is not None or body.expected_delivery_date is not None) and (order_date is None or expected_date is None):
        raise HTTPException(status_code=400, detail="Invalid order or expected delivery date")
    if order_date and expected_date and expected_date < order_date:
        raise HTTPException(status_code=400, detail="Expected delivery date cannot be before order date")

    # Enforce product-supplier mapping when changing SKU or supplier.
    new_supplier_id = body.supplier_id if body.supplier_id is not None else pos[idx].get("supplier_id")
    new_sku = body.sku if body.sku is not None else pos[idx].get("sku")
    if not is_supplier_mapped_to_sku(new_supplier_id, new_sku):
        raise HTTPException(status_code=400, detail="Selected supplier is not mapped to this product")

    # Preserve supplier change history separately from free-text notes.
    old_supplier_id = pos[idx].get("supplier_id")
    old_supplier_name = pos[idx].get("supplier_name")
    new_supplier_id = body.supplier_id if body.supplier_id is not None else old_supplier_id
    new_supplier_name = body.supplier_name if body.supplier_name is not None else old_supplier_name

    if body.supplier_id is not None and body.supplier_id != old_supplier_id:
        if not new_supplier_name or new_supplier_name == old_supplier_name:
            sups = load_suppliers()
            s = next((x for x in sups if x["supplier_id"] == new_supplier_id), None)
            new_supplier_name = s.get("name", "") if s else ""
        ts = datetime.now().isoformat()
        entry = (
            f"{ts}: supplier changed from {old_supplier_name or old_supplier_id} "
            f"to {new_supplier_name or new_supplier_id}"
        )
        hist = pos[idx].get("supplier_history", "")
        pos[idx]["supplier_history"] = (hist + "\n" + entry).strip()

    for field, value in body.dict(exclude_unset=True).items():
        if value is not None:
            pos[idx][field] = value

    pos[idx]["supplier_id"] = new_supplier_id
    pos[idx]["supplier_name"] = new_supplier_name
    save_pos(pos)
    return pos[idx]


@router.post("/purchase-orders/{po_id}/receive")
def receive_po(po_id: str, body: POReceive, payload: dict = Depends(require_manager_or_admin)):
    pos = load_pos()
    idx = next((i for i, p in enumerate(pos) if p["po_id"] == po_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="PO not found")
    if pos[idx].get("status") == "cancelled":
        raise HTTPException(status_code=400, detail="Cannot receive a cancelled PO")

    actual_date = _parse_date(body.actual_delivery_date)
    if actual_date is None:
        raise HTTPException(status_code=400, detail="Invalid actual delivery date")
    order_date = _parse_date(pos[idx].get("order_date"))
    if order_date and actual_date < order_date:
        raise HTTPException(status_code=400, detail="Actual delivery date cannot be before order date")

    pos[idx]["status"]               = "received"
    pos[idx]["received_qty"]         = body.received_qty
    pos[idx]["actual_delivery_date"] = body.actual_delivery_date
    if body.quality_rating is not None:
        pos[idx]["quality_rating"] = body.quality_rating
    save_pos(pos)

    # Update inventory: add received batch and update product stock total.
    try:
        sku = pos[idx].get("sku")
        qty = float(body.received_qty)
        if sku and qty > 0:
            prod_name = pos[idx].get("product_name", sku)
            supplier_name = pos[idx].get("supplier_name", "Unknown")
            BATCHES_CSV = os.path.join(DATA_DIR, "inventory_batches.csv")
            if os.path.exists(BATCHES_CSV):
                df_batches = pd.read_csv(BATCHES_CSV)
                existing = df_batches[df_batches["sku"].astype(str).str.strip().str.upper() == sku.strip().upper()]
                count = len(existing) + 1
                batch_id = f"BN-{sku}-{count:02d}"
                now = datetime.now()
                new_batch = {
                    "sku": sku,
                    "product_name": prod_name,
                    "supplier": supplier_name,
                    "batch_no": batch_id,
                    "quantity": qty,
                    "mfg_date": (now - timedelta(days=30)).strftime("%Y-%m-%d"),
                    "expiry_date": (now + timedelta(days=365)).strftime("%Y-%m-%d"),
                    "received_date": body.actual_delivery_date,
                    "status": "active"
                }
                df_batches = pd.concat([df_batches, pd.DataFrame([new_batch])], ignore_index=True)
                df_batches.to_csv(BATCHES_CSV, index=False)

            # Update products.csv directly (bypass load_products_dynamic which already
            # sums from batches — adding qty again there would cause a double-count).
            if os.path.exists(PRODUCTS_CSV):
                import pandas as _pd
                _pdf = _pd.read_csv(PRODUCTS_CSV).fillna("")
                _pmask = _pdf["sku"].astype(str).str.strip().str.upper() == sku.strip().upper()
                if _pmask.any():
                    _cur = float(_pdf.loc[_pmask, "current_stock"].values[0] or 0)
                    _pdf.loc[_pmask, "current_stock"] = _cur + qty
                    _pdf.to_csv(PRODUCTS_CSV, index=False)
                    logger.info("[Suppliers] products.csv stock updated for %s: %s -> %s", sku, _cur, _cur + qty)
    except Exception as e:
        logger.error(f"[Suppliers] Failed to update stock on PO receive {po_id}: {e}")

    return pos[idx]


@router.post("/purchase-orders/{po_id}/cancel")
def cancel_po(po_id: str, payload: dict = Depends(require_manager_or_admin)):
    pos = load_pos()
    idx = next((i for i, p in enumerate(pos) if p["po_id"] == po_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="PO not found")
    if pos[idx].get("status") == "received":
        raise HTTPException(status_code=400, detail="Cannot cancel a received PO")
    pos[idx]["status"] = "cancelled"
    save_pos(pos)
    return pos[idx]


@router.post("/purchase-orders/{po_id}/rate")
def rate_po(po_id: str, body: PORate, payload: dict = Depends(require_manager_or_admin)):
    pos = load_pos()
    idx = next((i for i, p in enumerate(pos) if p["po_id"] == po_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="PO not found")
    pos[idx]["quality_rating"] = body.quality_rating
    save_pos(pos)
    return pos[idx]
