from fastapi import FastAPI, WebSocket

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
