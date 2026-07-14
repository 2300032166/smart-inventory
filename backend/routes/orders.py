from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel
from typing import Optional
import json, os, uuid, logging
from datetime import datetime, timezone, timedelta

from middleware.auth_middleware import require_manager_or_admin
from .suppliers import load_suppliers, load_pos, save_pos

logger = logging.getLogger(__name__)

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OVERRIDE_FILE = os.path.join(DATA_DIR, "override_history.json")
AUDIT_FILE = os.path.join(DATA_DIR, "audit_log.json")
PRODUCTS_CSV = os.path.join(DATA_DIR, "products.csv")


def load_overrides() -> list:
    try:
        with open(OVERRIDE_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_overrides(data: list):
    with open(OVERRIDE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_audit() -> list:
    try:
        with open(AUDIT_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_audit(data: list):
    with open(AUDIT_FILE, "w") as f:
        json.dump(data, f, indent=2)


def _create_po_from_decision(
    sku: str,
    product_name: str,
    supplier_id: str,
    supplier_name: str,
    qty: float,
    lead_time: int,
    decision_id: str,
    payload: dict,
) -> dict:
    """Create a purchase order for an approved/overridden manager decision."""
    pos = load_pos()

    if not supplier_name:
        sups = load_suppliers()
        s = next((x for x in sups if x["supplier_id"] == supplier_id), None)
        supplier_name = s.get("name", "") if s else ""

    if not product_name and os.path.exists(PRODUCTS_CSV):
        try:
            import pandas as pd
            pdf = pd.read_csv(PRODUCTS_CSV).fillna("")
            row = pdf[pdf["sku"].astype(str).str.strip().str.upper() == str(sku).strip().upper()]
            if not row.empty:
                product_name = str(row.iloc[0].get("name", ""))
        except Exception as e:
            logger.warning("[Orders] Failed to look up product name for PO: %s", e)

    today = datetime.now(timezone.utc).date()
    order_date = today.isoformat()
    expected_delivery = (today + timedelta(days=lead_time)).isoformat()

    po = {
        "po_id": str(uuid.uuid4()),
        "po_number": f"PO-{len(pos) + 2000}",
        "supplier_id": supplier_id,
        "supplier_name": supplier_name,
        "sku": sku,
        "product_name": product_name,
        "ordered_qty": qty,
        "received_qty": 0,
        "order_date": order_date,
        "expected_delivery_date": expected_delivery,
        "actual_delivery_date": "",
        "status": "approved",
        "quality_rating": "",
        "notes": f"Created from approval decision {decision_id}",
        "created_by": payload.get("sub"),
    }
    pos.append(po)
    save_pos(pos)
    return po


class DecisionRequest(BaseModel):
    sku: str
    product_name: str = ""
    decision: str
    ai_suggested_qty: float = 0
    actual_qty: float = 0
    reason_category: str = ""
    reason_text: str = ""
    supplier_id: str = ""
    supplier_name: str = ""


class EditReasonRequest(BaseModel):
    reason_category: str
    reason_text: str


@router.post("/decide")
def record_decision(
    body: DecisionRequest,
    request: Request,
    payload: dict = Depends(require_manager_or_admin()),
):
    if body.decision not in ("approved", "overridden", "skipped"):
        raise HTTPException(
            status_code=400, detail="decision must be approved, overridden, or skipped"
        )

    # Fetch product lead time for arrival calculation
    # We load products.csv to get lead_time_days
    from .inventory import load_products as get_prods
    products = get_prods()
    prod = next((p for p in products if p["sku"] == body.sku), {})
    lead_time = int(prod.get("lead_time_days", 7))
    
    overrides = load_overrides()
    
    # Calculate arrival date
    now = datetime.now(timezone.utc)
    expected_arrival = (now + timedelta(days=lead_time)).isoformat()

    record = {
        "id": str(uuid.uuid4()),
        "timestamp": now.isoformat(),
        "sku": body.sku,
        "product_name": body.product_name,
        "ai_suggested_qty": body.ai_suggested_qty,
        "actual_qty": body.actual_qty,
        "decision": body.decision,
        "reason_category": body.reason_category,
        "reason_text": body.reason_text,
        "manager_id": payload.get("sub"),
        "manager_name": payload.get("name"),
        "supplier_id": body.supplier_id,
        "supplier_name": body.supplier_name,
        "status": "approved" if body.decision == "approved" else body.decision,
        "approval_date": now.isoformat() if body.decision in ("approved", "overridden") else None,
        "lead_time": lead_time,
        "expected_arrival_date": expected_arrival if body.decision in ("approved", "overridden") else None,
        "received_date": None,
        "po_id": None,
        "po_number": None,
    }
    overrides.append(record)
    save_overrides(overrides)

    created_po = None
    if body.decision in ("approved", "overridden") and body.supplier_id:
        try:
            created_po = _create_po_from_decision(
                body.sku,
                body.product_name,
                body.supplier_id,
                body.supplier_name,
                body.actual_qty,
                lead_time,
                record["id"],
                payload,
            )
            record["po_id"] = created_po.get("po_id")
            record["po_number"] = created_po.get("po_number")
            save_overrides(overrides)
            logger.info(
                "[Orders] Created PO %s for approved decision %s",
                created_po.get("po_number"), record["id"],
            )
        except Exception as e:
            logger.error("[Orders] Failed to create PO for approved decision: %s", e)

    audit = load_audit()
    ip = request.client.host if request.client else "unknown"
    audit.append({
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": payload.get("sub"),
        "user_name": payload.get("name"),
        "role": payload.get("role"),
        "action_type": f"ORDER_{body.decision.upper()}",
        "description": (
            f"{body.decision.title()} order for {body.product_name} "
            f"(SKU: {body.sku}), qty: {body.actual_qty}, supplier: {body.supplier_name or body.supplier_id}"
        ),
        "ip_address": ip,
    })
    save_audit(audit)

    logger.info(
        "[Orders] Decision recorded | sku=%s | decision=%s | manager=%s | supplier=%s",
        body.sku, body.decision, payload.get("name"), body.supplier_name or body.supplier_id,
    )
    return {"message": "Decision recorded", "id": record["id"], "po": created_po}


class OrderStatusUpdate(BaseModel):
    status: str
    mfg_date: Optional[str] = None
    expiry_date: Optional[str] = None
    batch_no: Optional[str] = None
    quantity_received: Optional[float] = None


@router.post("/{order_id}/status")
def update_order_status(
    order_id: str,
    body: OrderStatusUpdate,
    request: Request,
    payload: dict = Depends(require_manager_or_admin()),
):
    status = body.status
    if status not in ("approved", "ordered", "received", "cancelled"):
        raise HTTPException(status_code=400, detail="Invalid status")

    overrides = load_overrides()
    idx = next((i for i, o in enumerate(overrides) if o.get("id") == order_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Order not found")

    old_status = overrides[idx].get("status")
    overrides[idx]["status"] = status
    
    if status == "received" and old_status != "received":
        now = datetime.now(timezone.utc)
        overrides[idx]["received_date"] = now.isoformat()
        
        sku = overrides[idx]["sku"]
        # Use provided quantity or fallback to ordered quantity
        qty = body.quantity_received if body.quantity_received is not None else float(overrides[idx]["actual_qty"])
        prod_name = overrides[idx].get("product_name", sku)
        
        # 1. Determine Batch Number
        BATCHES_CSV = os.path.join(DATA_DIR, "inventory_batches.csv")
        try:
            import pandas as pd
            df_batches = pd.read_csv(BATCHES_CSV)
            existing_batches = df_batches[df_batches["sku"].str.upper() == sku.upper()]
            
            if body.batch_no:
                batch_id = body.batch_no
            else:
                # Auto-generate next sequence
                count = len(existing_batches) + 1
                batch_id = f"BN-{sku}-{count:02d}"
                
            new_batch = {
                "sku": sku,
                "product_name": prod_name,
                "supplier": overrides[idx].get("supplier_name", "Unknown"),
                "batch_no": batch_id,
                "quantity": qty,
                "mfg_date": body.mfg_date or (now - timedelta(days=30)).strftime("%Y-%m-%d"),
                "expiry_date": body.expiry_date or (now + timedelta(days=365)).strftime("%Y-%m-%d"),
                "received_date": now.strftime("%Y-%m-%d"),
                "status": "active"
            }
            
            # Double check sorting to ensure newly received batches 
            # have later dates than previous (business rule logic check could go here)
            
            df_batches = pd.concat([df_batches, pd.DataFrame([new_batch])], ignore_index=True)
            df_batches.to_csv(BATCHES_CSV, index=False)
        except Exception as e:
            logger.error(f"Failed to update batches: {e}")
            raise HTTPException(status_code=500, detail="Failed to create inventory batch")

        # 2. Update total stock in products master
        from .inventory import load_products, save_products
        products = load_products()
        p_idx = next((i for i, p in enumerate(products) if p["sku"] == sku), None)
        if p_idx is not None:
            current = float(products[p_idx].get("current_stock", 0))
            products[p_idx]["current_stock"] = current + qty
            save_products(products)
            logger.info("[Orders] Stock updated for %s: +%f (New Batch: %s)", sku, qty, batch_id)

        # 3. Update the associated purchase order if one was created from this decision
        po_id = overrides[idx].get("po_id")
        if po_id:
            try:
                pos = load_pos()
                po_idx = next((i for i, p in enumerate(pos) if p.get("po_id") == po_id), None)
                if po_idx is not None:
                    pos[po_idx]["status"] = "received"
                    pos[po_idx]["received_qty"] = qty
                    pos[po_idx]["actual_delivery_date"] = now.strftime("%Y-%m-%d")
                    pos[po_idx]["quality_rating"] = pos[po_idx].get("quality_rating", "")
                    save_pos(pos)
                    logger.info("[Orders] Associated PO %s marked as received", pos[po_idx].get("po_number"))
            except Exception as e:
                logger.error("[Orders] Failed to update associated PO for received decision: %s", e)

    # Update associated PO status for cancelled/re-activated/ordered decisions
    if status in ("cancelled", "approved", "ordered"):
        po_id = overrides[idx].get("po_id")
        if po_id:
            try:
                pos = load_pos()
                po_idx = next((i for i, p in enumerate(pos) if p.get("po_id") == po_id), None)
                if po_idx is not None:
                    current_po_status = pos[po_idx].get("status")
                    if status == "cancelled":
                        if current_po_status != "cancelled":
                            pos[po_idx]["status"] = "cancelled"
                            save_pos(pos)
                            logger.info("[Orders] Associated PO %s marked as cancelled", pos[po_idx].get("po_number"))
                    elif current_po_status != "received":
                        # Match the PO status exactly to the AI decision status
                        if current_po_status != status:
                            pos[po_idx]["status"] = status
                            save_pos(pos)
                            logger.info("[Orders] Associated PO %s marked as %s", pos[po_idx].get("po_number"), status)
            except Exception as e:
                logger.error("[Orders] Failed to update associated PO for %s decision: %s", status, e)

    overrides[idx]["last_updated"] = datetime.now(timezone.utc).isoformat()
    overrides[idx]["updated_by"] = payload.get("sub")

    # Store dates in override record too for history
    if body.mfg_date: overrides[idx]["mfg_date"] = body.mfg_date
    if body.expiry_date: overrides[idx]["expiry_date"] = body.expiry_date
    
    save_overrides(overrides)

    # Add to Audit Log
    audit = load_audit()
    ip = request.client.host if request.client else "unknown"
    sku = overrides[idx].get("sku", "N/A")
    audit.append({
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": payload.get("sub"),
        "user_name": payload.get("name"),
        "role": payload.get("role"),
        "action_type": f"ORDER_{status.upper()}",
        "description": f"Changed status of order ID {order_id} (SKU: {sku}) from {old_status} to {status}.",
        "ip_address": ip,
    })
    save_audit(audit)

    logger.info("[Orders] Order %s status updated to %s", order_id, status)
    return {"message": "Status updated", "order": overrides[idx]}


@router.post("/{order_id}/reason")
def update_order_reason(
    order_id: str,
    body: EditReasonRequest,
    payload: dict = Depends(require_manager_or_admin()),
):
    overrides = load_overrides()
    idx = next((i for i, o in enumerate(overrides) if o.get("id") == order_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Order not found")

    overrides[idx]["reason_category"] = body.reason_category
    overrides[idx]["reason_text"] = body.reason_text
    overrides[idx]["last_updated"] = datetime.now(timezone.utc).isoformat()
    overrides[idx]["updated_by"] = payload.get("sub")

    save_overrides(overrides)
    logger.info("[Orders] Order %s reason updated", order_id)
    return {"message": "Reason updated"}


@router.get("/reviewed")
def get_reviewed_by_date(
    date: str = Query(None),
    payload: dict = Depends(require_manager_or_admin())
):
    """Return all manager decisions made on a specific date (or today if None)."""
    target_date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    overrides = load_overrides()
    day_items = [o for o in overrides if o.get("timestamp", "")[:10] == target_date]
    day_items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    logger.info("[Orders] Reviewed on %s: %d items", target_date, len(day_items))
    return day_items


@router.get("/history")
def get_order_history(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sku: Optional[str] = Query(None),
    decision: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    payload: dict = Depends(require_manager_or_admin()),
):
    overrides = load_overrides()
    overrides.sort(key=lambda x: x.get("timestamp", ""), reverse=True)

    if sku:
        q = sku.lower()
        overrides = [o for o in overrides if q in (o.get("sku") or "").lower() or q in (o.get("product_name") or "").lower()]
    if decision:
        overrides = [o for o in overrides if o.get("decision") == decision]
    if date_from:
        overrides = [o for o in overrides if o.get("timestamp", "") >= date_from]
    if date_to:
        overrides = [o for o in overrides if o.get("timestamp", "")[:10] <= date_to]

    total = len(overrides)
    start = (page - 1) * limit
    items = overrides[start: start + limit]

    return {"total": total, "page": page, "limit": limit, "items": items}
