"""应用设置 API：GET/PUT /settings，合并 DB > env > defaults；供 run 创建时注入 settings_snapshot。"""
from __future__ import annotations

import os
from copy import deepcopy
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import SessionLocal, SettingsModel

router = APIRouter()

SETTINGS_KEY = "v0"


def get_db():
    """获取数据库会话（依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 与 agent-worker baidu_html 保持一致，避免百度 302→验证码；空字符串表示使用 backend 内置 UA
_DEFAULT_FETCH_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


# Bocha 官方 API 默认 base_url（可被 BOCHA_BASE_URL / web.providers.bocha.base_url 覆盖）
BOCHA_DEFAULT_BASE_URL = "https://api.bochaai.com"


def _default_settings() -> Dict[str, Any]:
    """默认设置（stub、15000；fetch 含 timeout/max_bytes/user_agent 桌面 Chrome；sandbox Win/WSL 双栈）"""
    return {
        "version": "settings_v0",
        "sandbox": {
            "workspace_root_win": "",  # e.g. D:\\Project\\lonelycat\\workspace
            "workspace_root_wsl": "",  # e.g. /mnt/d/Project/lonelycat/workspace
            "runtime_mode": "auto",    # auto | windows | wsl
            "docker": {
                "cli_path": "",       # optional, e.g. docker.exe on Windows
            },
        },
        "web": {
            "search": {
                "backend": "stub",
                "timeout_ms": 15000,
                "baidu": {
                    "cooldown_minutes": 10,
                    "warm_up_enabled": True,
                    "warm_up_ttl_seconds": 600,
                },
            },
            "fetch": {
                "timeout_ms": 15000,
                "max_bytes": 5 * 1024 * 1024,
                "user_agent": _DEFAULT_FETCH_USER_AGENT,
                "fetch_delay_seconds": 0,
            },
            "providers": {
                "bocha": {
                    "enabled": False,
                    "api_key": "",
                    "base_url": BOCHA_DEFAULT_BASE_URL,
                    "timeout_ms": 15000,
                    "top_k_default": 5,
                },
            },
        },
    }


def _env_settings() -> Dict[str, Any]:
    """从环境变量读取的设置（用于合并，未设的键不出现）"""
    out: Dict[str, Any] = {}
    backend = (os.getenv("WEB_SEARCH_BACKEND") or "").strip().lower()
    if backend in ("stub", "ddg_html", "baidu_html", "searxng", "bocha"):
        out.setdefault("web", {}).setdefault("search", {})["backend"] = backend
    raw_timeout = os.getenv("WEB_SEARCH_TIMEOUT_MS")
    if raw_timeout is not None and str(raw_timeout).strip():
        try:
            out.setdefault("web", {}).setdefault("search", {})["timeout_ms"] = max(
                1000, int(raw_timeout)
            )
        except (TypeError, ValueError):
            pass
    if backend == "searxng":
        base_url = (os.getenv("SEARXNG_BASE_URL") or "").strip()
        if base_url:
            out.setdefault("web", {}).setdefault("search", {}).setdefault(
                "searxng", {}
            )["base_url"] = base_url
        api_key = (os.getenv("SEARXNG_API_KEY") or "").strip() or None
        if api_key is not None:
            out.setdefault("web", {}).setdefault("search", {}).setdefault(
                "searxng", {}
            )["api_key"] = api_key
        raw_st = os.getenv("SEARXNG_TIMEOUT_MS")
        if raw_st is not None and str(raw_st).strip():
            try:
                out.setdefault("web", {}).setdefault("search", {}).setdefault(
                    "searxng", {}
                )["timeout_ms"] = max(1000, int(raw_st))
            except (TypeError, ValueError):
                pass
    # web.providers.bocha: 从 BOCHA_* env 合并；支持 env 引用 $BOCHA_API_KEY
    bocha_key = (os.getenv("BOCHA_API_KEY") or "").strip() or None
    if backend == "bocha" or bocha_key is not None:
        out.setdefault("web", {}).setdefault("providers", {}).setdefault("bocha", {})
        out["web"]["providers"]["bocha"]["enabled"] = backend == "bocha" or bool(bocha_key)
        if bocha_key is not None:
            out["web"]["providers"]["bocha"]["api_key"] = bocha_key
        base_url = (os.getenv("BOCHA_BASE_URL") or "").strip() or BOCHA_DEFAULT_BASE_URL
        out["web"]["providers"]["bocha"]["base_url"] = base_url
        raw_bocha_timeout = os.getenv("BOCHA_TIMEOUT_MS")
        if raw_bocha_timeout is not None and str(raw_bocha_timeout).strip():
            try:
                out["web"]["providers"]["bocha"]["timeout_ms"] = max(1000, int(raw_bocha_timeout))
            except (TypeError, ValueError):
                pass
        raw_top_k = os.getenv("BOCHA_TOP_K_DEFAULT")
        if raw_top_k is not None and str(raw_top_k).strip():
            try:
                out["web"]["providers"]["bocha"]["top_k_default"] = max(1, min(10, int(raw_top_k)))
            except (TypeError, ValueError):
                pass
    # web.fetch: proxy, timeout_ms, max_bytes, user_agent
    proxy = (os.getenv("WEB_FETCH_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or "").strip()
    if proxy:
        out.setdefault("web", {}).setdefault("fetch", {})["proxy"] = proxy
    raw_ft = os.getenv("WEB_FETCH_TIMEOUT_MS")
    if raw_ft is not None and str(raw_ft).strip():
        try:
            out.setdefault("web", {}).setdefault("fetch", {})["timeout_ms"] = max(1000, int(raw_ft))
        except (TypeError, ValueError):
            pass
    raw_mb = os.getenv("WEB_FETCH_MAX_BYTES")
    if raw_mb is not None and str(raw_mb).strip():
        try:
            out.setdefault("web", {}).setdefault("fetch", {})["max_bytes"] = max(1024, int(raw_mb))
        except (TypeError, ValueError):
            pass
    # 仅当显式设置且非旧 LonelyCat 时覆盖，避免 env 把 UA 回填为 LonelyCat/1.0
    ua = (os.getenv("WEB_FETCH_USER_AGENT") or "").strip()
    if ua and "LonelyCat" not in ua:
        out.setdefault("web", {}).setdefault("fetch", {})["user_agent"] = ua
    raw_delay = os.getenv("WEB_FETCH_DELAY_SECONDS")
    if raw_delay is not None and str(raw_delay).strip():
        try:
            delay = max(0, int(raw_delay))
            out.setdefault("web", {}).setdefault("fetch", {})["fetch_delay_seconds"] = delay
        except (TypeError, ValueError):
            pass
    # sandbox: workspace roots, runtime_mode, docker.cli_path
    win_root = (os.getenv("SANDBOX_WORKSPACE_ROOT_WIN") or "").strip()
    if win_root:
        out.setdefault("sandbox", {})["workspace_root_win"] = win_root
    wsl_root = (os.getenv("SANDBOX_WORKSPACE_ROOT_WSL") or "").strip()
    if wsl_root:
        out.setdefault("sandbox", {})["workspace_root_wsl"] = wsl_root
    runtime = (os.getenv("SANDBOX_RUNTIME_MODE") or "").strip().lower()
    if runtime in ("auto", "windows", "wsl"):
        out.setdefault("sandbox", {})["runtime_mode"] = runtime
    cli_path = (os.getenv("SANDBOX_DOCKER_CLI_PATH") or "").strip()
    if cli_path:
        out.setdefault("sandbox", {}).setdefault("docker", {})["cli_path"] = cli_path
    # core_api_url：worker 从 settings_snapshot 取此 URL 调用 GET /skills、POST /skills/{id}/invoke
    core_url = (os.getenv("LONELYCAT_CORE_API_URL") or os.getenv("CORE_API_URL") or "").strip()
    if core_url:
        out["core_api_url"] = core_url
    return out


def _db_settings(db: Session) -> Dict[str, Any]:
    """从 DB 读取的设置（未存则返回空 dict）"""
    row = db.query(SettingsModel).filter(SettingsModel.key == SETTINGS_KEY).first()
    if row is None or not isinstance(row.value, dict):
        return {}
    return deepcopy(row.value)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """递归合并 override 到 base（override 优先），不修改 base。"""
    result = deepcopy(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = deepcopy(v)
    return result


def _resolve_bocha_api_key_from_env(settings: Dict[str, Any]) -> None:
    """若 web.providers.bocha.api_key 为 $BOCHA_API_KEY，则用环境变量替换（原地修改）。"""
    try:
        bocha = ((settings.get("web") or {}).get("providers") or {}).get("bocha")
        if not isinstance(bocha, dict):
            return
        key = bocha.get("api_key")
        if isinstance(key, str) and key.strip().startswith("$"):
            ref = key.strip()[1:].strip() or "BOCHA_API_KEY"
            bocha["api_key"] = (os.getenv(ref) or "").strip() or ""
    except (KeyError, TypeError):
        pass


def get_current_settings(db: Session) -> Dict[str, Any]:
    """当前生效设置（合并：defaults <- env <- db）。用于 GET /settings 与创建 run 时写入 settings_snapshot。"""
    base = _default_settings()
    base = _deep_merge(base, _env_settings())
    base = _deep_merge(base, _db_settings(db))
    _resolve_bocha_api_key_from_env(base)
    return base


def _redact_secrets_for_display(settings: Dict[str, Any]) -> Dict[str, Any]:
    """脱敏 API key 等，仅用于 GET /settings 返回给前端，避免 console 泄漏。不修改原 dict。"""
    out = deepcopy(settings)
    try:
        web = out.get("web")
        if not isinstance(web, dict):
            return out
        # web.providers.bocha.api_key
        providers = web.get("providers")
        if isinstance(providers, dict):
            bocha = providers.get("bocha")
            if isinstance(bocha, dict) and bocha.get("api_key"):
                web = dict(web)
                web["providers"] = dict(providers)
                web["providers"]["bocha"] = {**bocha, "api_key": "********"}
                out["web"] = web
        # web.search.searxng.api_key
        search = web.get("search")
        if isinstance(search, dict):
            searxng = search.get("searxng")
            if isinstance(searxng, dict) and searxng.get("api_key"):
                if not isinstance(out.get("web"), dict):
                    out["web"] = dict(out.get("web") or {})
                out["web"]["search"] = {**search, "searxng": {**searxng, "api_key": "********"}}
    except (KeyError, TypeError):
        pass
    return out


class SettingsUpdateBody(BaseModel):
    """PUT 请求体（白名单字段）"""
    version: str | None = None
    web: Dict[str, Any] | None = None
    sandbox: Dict[str, Any] | None = None


@router.get("", response_model=Dict[str, Any])
def get_settings(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """返回当前生效设置（DB > env > defaults）；api_key 等脱敏为 ********。"""
    return _redact_secrets_for_display(get_current_settings(db))


@router.put("", response_model=Dict[str, Any])
def put_settings(
    body: SettingsUpdateBody,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """更新设置（仅允许白名单字段），写入 DB 后返回完整 GET 结果。"""
    current = get_current_settings(db)
    # 只合并允许的键
    if body.version is not None:
        current["version"] = body.version
    if body.web is not None:
        current["web"] = _deep_merge(
            current.get("web") or {},
            body.web,
        )
    if body.sandbox is not None:
        current["sandbox"] = _deep_merge(
            current.get("sandbox") or {},
            body.sandbox,
        )
    # 持久化：只存用户可编辑部分（可选：存完整 current，便于一致）
    row = db.query(SettingsModel).filter(SettingsModel.key == SETTINGS_KEY).first()
    if row is None:
        db.add(SettingsModel(key=SETTINGS_KEY, value=current))
    else:
        row.value = current
    db.commit()
    return get_current_settings(db)
