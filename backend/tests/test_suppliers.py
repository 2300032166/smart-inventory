"""Tests for the supplier routes and regenerated supplier data."""
import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app
from middleware.auth_middleware import verify_token


# ── helpers ───────────────────────────────────────────────────────────────────

def _fake_token(role="admin"):
    def verify(credentials=None):
        return {
            "sub": "USR001",
            "role": role,
            "name": "Test User",
            "email": "test@store.com",
        }

    return verify


@pytest.fixture
def client_manager():
    """Return a TestClient authenticated as a manager."""
    from fastapi.testclient import TestClient

    app.dependency_overrides[verify_token] = _fake_token("manager")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def client_admin():
    """Return a TestClient authenticated as an admin."""
    from fastapi.testclient import TestClient

    app.dependency_overrides[verify_token] = _fake_token("admin")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ── data-shape tests ───────────────────────────────────────────────────────────

def test_supplier_master_has_expected_fields(client_admin):
    r = client_admin.get("/api/suppliers")
    assert r.status_code == 200, r.text
    suppliers = r.json()
    assert 50 <= len(suppliers) <= 80, f"Expected 50-80 suppliers, got {len(suppliers)}"
    required = {"supplier_id", "name", "company_name", "contact_person", "phone",
                "email", "address", "status", "default_lead_time_days", "delivery_schedule"}
    for s in suppliers:
        assert required.issubset(s.keys()), f"Missing fields in supplier {s.get('supplier_id')}"


def test_supplier_metrics_are_computed(client_admin):
    r = client_admin.get("/api/suppliers/metrics/all")
    assert r.status_code == 200, r.text
    suppliers = r.json()
    for s in suppliers:
        assert "total_orders" in s
        assert s["total_orders"] > 0, f"{s['name']} has no orders"
        assert 0 <= s.get("reliability_score", 0) <= 100
        assert 0 <= s.get("on_time_pct", 0) <= 100


def test_product_has_multiple_suppliers(client_admin):
    # Use a stable product from the catalog.
    catalog = client_admin.get("/api/customer-products/?limit=1")
    assert catalog.status_code == 200, catalog.text
    products = catalog.json().get("products", [])
    if not products:
        pytest.skip("No products in catalog")
    sku = products[0]["sku"]

    r = client_admin.get(f"/api/suppliers/product/{sku}/suppliers")
    assert r.status_code == 200, r.text
    suppliers = r.json()
    assert len(suppliers) >= 2, f"Product {sku} has only {len(suppliers)} supplier(s)"


def test_recommendation_returns_ranked_suppliers(client_admin):
    catalog = client_admin.get("/api/customer-products/?limit=1")
    assert catalog.status_code == 200, catalog.text
    products = catalog.json().get("products", [])
    if not products:
        pytest.skip("No products in catalog")
    sku = products[0]["sku"]

    r = client_admin.get(f"/api/suppliers/recommendation/{sku}")
    assert r.status_code == 200, r.text
    body = r.json()
    if body["all_suppliers"]:
        assert body["recommended"] is not None
        assert body["recommended"]["rank"] == 1


# ── purchase-order data-quality tests ──────────────────────────────────────────

def test_purchase_order_dates_are_realistic(client_admin):
    # Iterate all pages so the invariant is checked across the full dataset.
    page = 1
    total_checked = 0
    while True:
        r = client_admin.get(f"/api/suppliers/purchase-orders/list?limit=200&page={page}")
        assert r.status_code == 200, r.text
        body = r.json()
        orders = body.get("items", [])
        for o in orders:
            order_date = datetime.strptime(o["order_date"], "%Y-%m-%d").date()
            expected = datetime.strptime(o["expected_delivery_date"], "%Y-%m-%d").date()
            assert expected >= order_date, (
                f"PO {o['po_number']} expected delivery {expected} is before order {order_date}"
            )
            if o.get("status") == "received" and o.get("actual_delivery_date"):
                actual = datetime.strptime(o["actual_delivery_date"], "%Y-%m-%d").date()
                assert actual >= order_date, (
                    f"PO {o['po_number']} actual delivery {actual} is before order {order_date}"
                )
            total_checked += 1
        if page >= body.get("total", 0) / 200:
            break
        page += 1
    assert total_checked > 0


def test_received_orders_have_quality_and_fill(client_admin):
    r = client_admin.get("/api/suppliers/purchase-orders/list?status=received&limit=200")
    assert r.status_code == 200, r.text
    orders = r.json().get("items", [])
    assert orders, "No received orders found"
    for o in orders:
        assert o.get("received_qty", ""), f"PO {o['po_number']} received_qty missing"
        assert o.get("quality_rating", ""), f"PO {o['po_number']} quality_rating missing"
        fill = float(o["received_qty"]) / float(o["ordered_qty"]) * 100
        assert 0 <= fill <= 100, f"PO {o['po_number']} fill rate out of range"


# ── server-side validation tests ──────────────────────────────────────────────

def test_create_po_rejects_invalid_dates(client_admin):
    r = client_admin.post("/api/suppliers/purchase-orders", json={
        "supplier_id": "SUP001",
        "sku": "BB-10007",
        "ordered_qty": 100,
        "order_date": "2026-01-10",
        "expected_delivery_date": "2026-01-05",
        "notes": "",
    })
    assert r.status_code == 400, r.text
    assert "before order date" in r.json().get("detail", "").lower()

    r = client_admin.post("/api/suppliers/purchase-orders", json={
        "supplier_id": "SUP001",
        "sku": "BB-10007",
        "ordered_qty": 100,
        "order_date": "invalid-date",
        "expected_delivery_date": "2026-01-10",
        "notes": "",
    })
    assert r.status_code == 400, r.text


def test_update_po_rejects_invalid_dates(client_admin):
    # Find an editable PO (status != received).
    page = 1
    editable_po = None
    while True:
        r = client_admin.get(f"/api/suppliers/purchase-orders/list?limit=200&page={page}")
        assert r.status_code == 200, r.text
        body = r.json()
        for o in body.get("items", []):
            if o.get("status") != "received":
                editable_po = o
                break
        if editable_po or page >= body.get("total", 0) / 200:
            break
        page += 1

    if not editable_po:
        pytest.skip("No editable PO found")

    po_id = editable_po["po_id"]

    r = client_admin.put(f"/api/suppliers/purchase-orders/{po_id}", json={
        "order_date": "not-a-date",
    })
    assert r.status_code == 400, r.text

    r = client_admin.put(f"/api/suppliers/purchase-orders/{po_id}", json={
        "expected_delivery_date": "1900-01-01",
    })
    assert r.status_code == 400, r.text
    assert "before order date" in r.json().get("detail", "").lower()


def test_receive_po_rejects_invalid_actual_date(client_admin):
    page = 1
    editable_po = None
    while True:
        r = client_admin.get(f"/api/suppliers/purchase-orders/list?limit=200&page={page}")
        assert r.status_code == 200, r.text
        body = r.json()
        for o in body.get("items", []):
            if o.get("status") != "received":
                editable_po = o
                break
        if editable_po or page >= body.get("total", 0) / 200:
            break
        page += 1

    if not editable_po:
        pytest.skip("No editable PO found")

    r = client_admin.post(f"/api/suppliers/purchase-orders/{editable_po['po_id']}/receive", json={
        "received_qty": 10,
        "actual_delivery_date": "1900-01-01",
        "quality_rating": 4,
    })
    assert r.status_code == 400, r.text


# ── mapping-coverage tests ────────────────────────────────────────────────────

def test_every_supplier_has_products_and_orders(client_admin):
    suppliers = client_admin.get("/api/suppliers").json()

    # Collect purchase order supplier IDs across all pages (max 200 per page).
    po_suppliers = set()
    page = 1
    while True:
        r = client_admin.get(f"/api/suppliers/purchase-orders/list?limit=200&page={page}")
        assert r.status_code == 200, r.text
        body = r.json()
        for o in body.get("items", []):
            po_suppliers.add(o["supplier_id"])
        if page >= body.get("total", 0) / 200:
            break
        page += 1

    supplier_ids = {s["supplier_id"] for s in suppliers}
    assert supplier_ids.issubset(po_suppliers), (
        f"Suppliers without purchase orders: {supplier_ids - po_suppliers}"
    )

    for s in suppliers:
        detail = client_admin.get(f"/api/suppliers/{s['supplier_id']}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body.get("mapped_products"), f"Supplier {s['supplier_id']} has no mapped products"
        assert body.get("total_orders") > 0, f"Supplier {s['supplier_id']} has no computed orders"
