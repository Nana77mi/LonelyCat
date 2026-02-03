try:
    from fastapi import FastAPI, WebSocket
    from fastapi.middleware.cors import CORSMiddleware
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

        def include_router(self, router, prefix: str | None = None, tags: list[str] | None = None) -> None:
            return None

        def add_middleware(self, middleware, **kwargs) -> None:
            return None

        def websocket(self, path: str):
            def decorator(func):
                return func

            return decorator

    class CORSMiddleware:  # type: ignore[no-redef]
        def __init__(self, app, **kwargs) -> None:
            self.app = app

from app.api.conversations import router as conversations_router
from app.api.internal import router as internal_router
from app.api.memory import router as memory_router
from app.api.runs import router as runs_router
from app.db import init_db as init_core_db
from app.settings import Settings

# 初始化数据库（包括 conversations 和 messages 表）
init_core_db()

settings = Settings()
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://localhost:8001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(memory_router, prefix="/memory", tags=["memory"])
app.include_router(conversations_router, prefix="/conversations", tags=["conversations"])
app.include_router(runs_router, prefix="/runs", tags=["runs"])
app.include_router(internal_router)  # 内部 API，无需 prefix（已在 router 中定义）


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"message": "welcome"})
    await websocket.close()
