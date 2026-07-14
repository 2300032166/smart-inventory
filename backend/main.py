from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
import os, logging
from logic.chatbot_data import data_manager

load_dotenv()

logger = logging.getLogger(__name__)

from routes import auth, inventory, sales, advisor, orders, alerts, admin, analytics, weather, dead_stock, chatbot, expiry, discounts, festival_planner
from routes import customers, customer_products, customer_orders, admin_customer_orders, reviews
from routes import suppliers as suppliers_mgmt

# Configuration from environment variables (Calibo standard)
# Trigger reload
port = int(os.getenv('port', 4040))
context = os.getenv('context', '/')

# Ensure context starts with / and doesn't end with / (unless it's just /)
if not context.startswith('/'):
    context = '/' + context
if context.endswith('/') and len(context) > 1:
    context = context[:-1]

app = FastAPI(
    title="SIRA", 
    version="1.0.0",
    root_path=context if context != "/" else ""
)

@app.on_event("startup")
async def startup_event():
    """Execute startup tasks like pre-loading chatbot data."""
    try:
        data_manager.initialize()
    except Exception as e:
        logger.error(f"Failed to initialize chatbot data manager: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routes
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["inventory"])
app.include_router(sales.router, prefix="/api/sales", tags=["sales"])
app.include_router(advisor.router, prefix="/api/brief", tags=["brief"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(weather.router, prefix="/api/weather", tags=["weather"])
app.include_router(dead_stock.router, prefix="/api/dead-stock", tags=["dead-stock"])
app.include_router(chatbot.router, prefix="/api/chatbot", tags=["chatbot"])
app.include_router(expiry.router, prefix="/api/expiry", tags=["expiry"])
app.include_router(discounts.router, prefix="/api/discounts", tags=["discounts"])
app.include_router(festival_planner.router, prefix="/api/festival-planner", tags=["festival-planner"])
app.include_router(suppliers_mgmt.router, prefix="/api/suppliers", tags=["suppliers"])

# Customer module routes
app.include_router(customers.router,               prefix="/api/customers",            tags=["customers"])
app.include_router(customer_products.router,       prefix="/api/customer-products",    tags=["customer-products"])
app.include_router(customer_orders.router,         prefix="/api/customer-orders",      tags=["customer-orders"])
app.include_router(admin_customer_orders.router,   prefix="/api/admin/customer-orders",tags=["admin-customer-orders"])
app.include_router(reviews.router,                 prefix="/api/reviews",              tags=["reviews"])


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "SIRA"}


# Serve the frontend static files (must be AFTER all API routes)
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    # Mount at the specified context path
    app.mount(context, StaticFiles(directory=frontend_dir, html=True), name="frontend")
    
    # Redirect base context or root to index if context is not /
    if context != "/":
        @app.get("/")
        def root_redirect():
            return RedirectResponse(url=context)
