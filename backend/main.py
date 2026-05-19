from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
import os

load_dotenv()

from routes import auth, inventory, sales, advisor, orders, alerts, admin, analytics

app = FastAPI(title="Smart Inventory Replenishment Advisor", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["inventory"])
app.include_router(sales.router, prefix="/api/sales", tags=["sales"])
app.include_router(advisor.router, prefix="/api/brief", tags=["brief"])
app.include_router(orders.router, prefix="/api/orders", tags=["orders"])
app.include_router(alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": "Smart Inventory Replenishment Advisor"}


# Serve the frontend static files (must be AFTER all API routes)
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
