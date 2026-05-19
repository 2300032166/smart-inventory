from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import pandas as pd
import os

from middleware.auth_middleware import verify_token, require_role
from logic.pattern_detector import analyse_sku, load_sales
from logic.reorder_calculator import calculate_reorder

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
PRODUCTS_CSV = os.path.join(DATA_DIR, "products.csv")
SUPPLIERS_CSV = os.path.join(DATA_DIR, "suppliers.csv")


def load_products():
    df = pd.read_csv(PRODUCTS_CSV)
    return df.fillna("").to_dict(orient="records")


def save_products(products: list):
    df = pd.DataFrame(products)
    df.to_csv(PRODUCTS_CSV, index=False)


def load_suppliers():
    df = pd.read_csv(SUPPLIERS_CSV)
    return df.fillna("").to_dict(orient="records")


def save_suppliers(suppliers: list):
    df = pd.DataFrame(suppliers)
    df.to_csv(SUPPLIERS_CSV, index=False)


def enrich_product(p: dict, sales_df=None) -> dict:
    try:
        pattern = analyse_sku(p["sku"], sales_df)
        reorder = calculate_reorder(p, pattern)
        days_remaining = reorder["days_remaining"]
        lead_time = int(p.get("lead_time_days", 7))
        current_stock = float(p.get("current_stock", 0))
        reorder_threshold = float(p.get("reorder_threshold", 0))

        if days_remaining < lead_time:
            status = "at_risk"
        elif current_stock > reorder_threshold * 3:
            status = "overstocked"
        else:
            status = "ok"

        return {**p, "days_remaining": days_remaining, "urgency": reorder["urgency"], "status": status}
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
    notes: str = ""


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
    products = load_products()
    sales_df = load_sales()
    return [enrich_product(p, sales_df) for p in products]


@router.get("/products/{sku}")
def get_product(sku: str, payload: dict = Depends(verify_token)):
    products = load_products()
    p = next((x for x in products if x["sku"] == sku), None)
    if not p:
        raise HTTPException(status_code=404, detail="Product not found")
    return enrich_product(p)


@router.post("/products")
def create_product(body: ProductCreate, payload: dict = Depends(require_role("admin"))):
    products = load_products()
    if any(p["sku"] == body.sku for p in products):
        raise HTTPException(status_code=409, detail="SKU already exists")
    products.append(body.dict())
    save_products(products)
    return body.dict()


@router.put("/products/{sku}")
def update_product(sku: str, body: ProductCreate, payload: dict = Depends(require_role("admin"))):
    products = load_products()
    idx = next((i for i, p in enumerate(products) if p["sku"] == sku), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Product not found")
    products[idx] = body.dict()
    save_products(products)
    return body.dict()


@router.delete("/products/{sku}")
def delete_product(sku: str, payload: dict = Depends(require_role("admin"))):
    products = load_products()
    products = [p for p in products if p["sku"] != sku]
    save_products(products)
    return {"message": "Product deleted"}


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
