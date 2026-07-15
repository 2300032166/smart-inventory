import sys
import os
sys.path.append('c:\\Users\\SAIKALAMODEPALLI\\Downloads\\SIRA_CAPSTONE\\SIRA\\backend')
from fastapi.testclient import TestClient
from main import app
from jose import jwt

# Set dummy secret
os.environ["JWT_SECRET_KEY"] = "secret"
token = jwt.encode({"role": "manager"}, "secret", algorithm="HS256")

client = TestClient(app)

def test_pending_brief():
    response = client.get("/api/brief/pending", headers={"Authorization": f"Bearer {token}"})
    print("Status:", response.status_code)
    try:
        print("Response:", response.json()[:2] if isinstance(response.json(), list) else response.json())
    except Exception:
        print("Response Text:", response.text)

if __name__ == "__main__":
    test_pending_brief()
