from fastapi.testclient import TestClient

from app.main import app


def test_websocket_welcome():
    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        data = websocket.receive_json()
        assert data == {"message": "welcome"}
