"""
Smoke tests for the Customer Module:
  - signup / login / forgot-password / reset-password
  - no debug_token in production mode (SANDBOX_MODE unset)
  - sandbox token auto-fill when SANDBOX_MODE=true
  - cart add + checkout (if products exist)
"""
import os
import pytest
from fastapi.testclient import TestClient

# Ensure SANDBOX_MODE is NOT set when testing production behaviour
os.environ.pop("SANDBOX_MODE", None)

# TestClient must be imported after env is configured
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from backend.main import app

client = TestClient(app)

TEST_EMAIL = "test_customer_smoke@example.com"
TEST_PASSWORD = "TestPass123"


# ── helpers ───────────────────────────────────────────────────────────────────

def ensure_account():
    """Create account if not already present; return (email, password)."""
    r = client.post("/api/customers/signup", json={
        "name": "Smoke Test",
        "email": TEST_EMAIL,
        "mobile": "9876543210",
        "password": TEST_PASSWORD,
        "confirm_password": TEST_PASSWORD,
        "address": "123 Test Lane",
    })
    assert r.status_code in (200, 400), r.text
    return TEST_EMAIL, TEST_PASSWORD


def login(email=TEST_EMAIL, password=TEST_PASSWORD):
    r = client.post("/api/customers/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


# ── tests ─────────────────────────────────────────────────────────────────────

def test_signup_and_login():
    """Signup creates account; login returns a token."""
    ensure_account()
    data = login()
    assert "token" in data
    assert "customer_id" in data


def test_forgot_password_never_returns_token_in_production():
    """forgot-password must NOT expose debug_token when SANDBOX_MODE is unset."""
    ensure_account()
    r = client.post("/api/customers/forgot-password", json={"email": TEST_EMAIL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "debug_token" not in body, (
        "forgot-password returned debug_token in production mode — "
        "this is a critical account-takeover vulnerability."
    )


def test_forgot_password_returns_token_in_sandbox(monkeypatch):
    """In sandbox mode the token IS returned so the demo flow works."""
    monkeypatch.setenv("SANDBOX_MODE", "true")
    ensure_account()

    # Re-import to pick up patched env
    import importlib, backend.routes.customers as cm
    importlib.reload(cm)
    from fastapi.testclient import TestClient as TC
    from backend.main import app as _app
    sc = TC(_app)

    r = sc.post("/api/customers/forgot-password", json={"email": TEST_EMAIL})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "debug_token" in body, "Expected debug_token in sandbox mode"


def test_reset_password_full_flow(monkeypatch):
    """Full reset flow: get sandbox token → reset → login with new password → revert."""
    monkeypatch.setenv("SANDBOX_MODE", "true")
    ensure_account()

    import importlib, backend.routes.customers as cm
    importlib.reload(cm)
    from fastapi.testclient import TestClient as TC
    from backend.main import app as _app
    sc = TC(_app)

    forgot = sc.post("/api/customers/forgot-password", json={"email": TEST_EMAIL})
    assert forgot.status_code == 200, forgot.text
    token = forgot.json().get("debug_token")
    assert token, "No debug_token in sandbox mode"

    NEW_PW = "NewPass12345!"
    reset = sc.post("/api/customers/reset-password", json={"token": token, "new_password": NEW_PW})
    assert reset.status_code == 200, reset.text

    new_login = sc.post("/api/customers/login", json={"email": TEST_EMAIL, "password": NEW_PW})
    assert new_login.status_code == 200, "Login with new password failed"

    # Revert so test is idempotent
    forgot2 = sc.post("/api/customers/forgot-password", json={"email": TEST_EMAIL})
    token2 = forgot2.json().get("debug_token")
    sc.post("/api/customers/reset-password", json={"token": token2, "new_password": TEST_PASSWORD})


def test_cart_and_checkout():
    """Add a product to cart, then checkout; assert no server crash."""
    ensure_account()
    data = login()
    auth = {"Authorization": f"Bearer {data['token']}"}

    catalog = client.get("/api/customer-products/?limit=1")
    assert catalog.status_code == 200, catalog.text
    products = catalog.json().get("products", [])
    if not products:
        pytest.skip("No products in catalogue — skipping cart test")

    sku = products[0]["sku"]
    add = client.post("/api/customer-orders/cart", json={"sku": sku, "quantity": 1}, headers=auth)
    assert add.status_code in (200, 400), add.text

    if add.status_code == 200:
        checkout = client.post("/api/customer-orders/checkout", json={
            "delivery_address": "123 Test Lane",
            "contact_number": "9876543210",
            "payment_method": "cod",
        }, headers=auth)
        # 200 = order placed; 400 = stock insufficient — both are valid outcomes
        assert checkout.status_code in (200, 400), checkout.text
