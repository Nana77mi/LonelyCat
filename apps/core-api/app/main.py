import os
from contextlib import asynccontextmanager
from pathlib import Path

# 可选：仅当 LONELYCAT_LOAD_DOTENV=1 时从仓库根加载 .env（生产建议用 up.ps1 等脚本层注入）
if os.environ.get("LONELYCAT_LOAD_DOTENV", "").strip() == "1":
    _env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"
    if _env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(_env_file)
        except Exception:
            pass

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
        def __init__(self, title: str | None = None, **kwargs: object) -> None:
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
from app.api.governance import router as governance_router
from app.api.internal import router as internal_router
from app.api.memory import router as memory_router
from app.api.runs import router as runs_router
from app.api.sandbox import router as sandbox_router
from app.api.settings import router as settings_router, get_current_settings
from app.api.skills import router as skills_router
from app.db import SessionLocal, init_db as init_core_db
from app.settings import Settings

# 初始化数据库（包括 conversations 和 messages 表）
init_core_db()

# 初始化 Governance 表
try:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages"))
    from governance.schema import init_governance_db
    init_governance_db()
except Exception as e:
    print(f"[governance] Failed to initialize governance DB: {e}")

settings = Settings()


def _startup_sandbox_docker_log() -> None:
    """启动时输出 docker context 与 docker info 摘要到日志（PR1.5 Win/WSL 联调）。"""
    try:
        from app.services.sandbox.docker_health import log_docker_context_and_info
        db = SessionLocal()
        try:
            settings = get_current_settings(db)
            cli = (settings.get("sandbox") or {}).get("docker") or {}
            cli_path = (cli.get("cli_path") or "").strip() or "docker"
            log_docker_context_and_info(cli_path)
        finally:
            db.close()
    except Exception as e:
        print(f"[sandbox] startup docker log skipped: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup_sandbox_docker_log()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
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
app.include_router(settings_router, prefix="/settings", tags=["settings"])
app.include_router(sandbox_router, prefix="/sandbox")
app.include_router(skills_router, prefix="/skills")
app.include_router(governance_router)  # Governance endpoints (WriteGate)
app.include_router(internal_router)  # 内部 API，无需 prefix（已在 router 中定义）


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    await websocket.send_json({"message": "welcome"})
    await websocket.close()
