try:
    from fastapi import FastAPI, WebSocket
except ModuleNotFoundError:  # pragma: no cover - exercised in offline tests
    class WebSocket:  # type: ignore[no-redef]
        async def accept(self) -> None:
            raise NotImplementedError

        async def send_json(self, data: dict) -> None:
            raise NotImplementedError

        async def close(self) -> None:
            raise NotImplementedError

    class FastAPI:  # type: ignore[no-redef]
        def __init__(self, title: str | None = None) -> None:
            self.title = title

        def get(self, path: str):
            def decorator(func):
                return func

            return decorator

        def websocket(self, path: str):
            def decorator(func):
                return func

            return decorator

from app.settings import Settings

settings = Settings()
app = FastAPI(title=settings.app_name)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"message": "welcome"})
    await websocket.close()
