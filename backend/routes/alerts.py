from fastapi import APIRouter, Depends, HTTPException
import json, os, uuid
from datetime import datetime, timezone

from middleware.auth_middleware import verify_token

router = APIRouter()
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
ALERTS_FILE = os.path.join(DATA_DIR, "alerts.json")


def load_alerts():
    try:
        with open(ALERTS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def save_alerts(data: list):
    with open(ALERTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


@router.get("")
def get_alerts(payload: dict = Depends(verify_token)):
    # Trigger alert generation if needed (lazy-load style)
    # We can't easily import advisor here due to circular imports,
    # but we can implement a basic scan or just wait for the user to visit the dashboard.
    # Actually, let's just ensure the types match the frontend icons.
    user_id = payload.get("sub")
    alerts = load_alerts()
    user_alerts = [a for a in alerts if a.get("user_id") == user_id or a.get("user_id") == "all"]
    user_alerts.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return user_alerts


@router.post("/{alert_id}/read")
def mark_read(alert_id: str, payload: dict = Depends(verify_token)):
    alerts = load_alerts()
    found = False
    for a in alerts:
        if a.get("id") == alert_id:
            a["is_read"] = True
            found = True
            break
    if not found:
        raise HTTPException(status_code=404, detail="Alert not found")
    save_alerts(alerts)
    return {"message": "Marked as read"}


@router.post("/read-all")
def mark_all_read(payload: dict = Depends(verify_token)):
    user_id = payload.get("sub")
    alerts = load_alerts()
    for a in alerts:
        if a.get("user_id") == user_id or a.get("user_id") == "all":
            a["is_read"] = True
    save_alerts(alerts)
    return {"message": "All alerts marked as read"}


def create_alert(user_id: str, alert_type: str, title: str, message: str):
    alerts = load_alerts()
    alerts.append({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "type": alert_type,
        "title": title,
        "message": message,
        "is_read": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    save_alerts(alerts)
