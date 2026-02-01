import asyncio

from app.main import websocket_endpoint


class FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.closed = False
        self.messages: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        self.messages.append(data)

    async def close(self) -> None:
        self.closed = True


def test_websocket_welcome():
    websocket = FakeWebSocket()
    asyncio.run(websocket_endpoint(websocket))
    assert websocket.accepted is True
    assert websocket.closed is True
    assert websocket.messages == [{"message": "welcome"}]
