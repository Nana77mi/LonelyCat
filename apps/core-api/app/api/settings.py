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


def _default_settings() -> Dict[str, Any]:
    """默认设置（stub、15000；fetch 含 timeout/max_bytes/user_agent）"""
    return {
        "version": "settings_v0",
        "web": {
            "search": {
                "backend": "stub",
                "timeout_ms": 15000,
            },
            "fetch": {
                "timeout_ms": 15000,
                "max_bytes": 5 * 1024 * 1024,
                "user_agent": "Mozilla/5.0 (compatible; LonelyCat/1.0; +https://github.com/lonelycat)",
            },
        },
    }


def _env_settings() -> Dict[str, Any]:
    """从环境变量读取的设置（用于合并，未设的键不出现）"""
    out: Dict[str, Any] = {}
    backend = (os.getenv("WEB_SEARCH_BACKEND") or "").strip().lower()
    if backend in ("stub", "ddg_html", "searxng"):
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
    ua = (os.getenv("WEB_FETCH_USER_AGENT") or "").strip()
    if ua:
        out.setdefault("web", {}).setdefault("fetch", {})["user_agent"] = ua
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


def get_current_settings(db: Session) -> Dict[str, Any]:
    """当前生效设置（合并：defaults <- env <- db）。用于 GET /settings 与创建 run 时写入 settings_snapshot。"""
    base = _default_settings()
    base = _deep_merge(base, _env_settings())
    base = _deep_merge(base, _db_settings(db))
    return base


class SettingsUpdateBody(BaseModel):
    """PUT 请求体（白名单字段）"""
    version: str | None = None
    web: Dict[str, Any] | None = None


@router.get("", response_model=Dict[str, Any])
def get_settings(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """返回当前生效设置（DB > env > defaults）。"""
    return get_current_settings(db)


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
    # 持久化：只存用户可编辑部分（可选：存完整 current，便于一致）
    row = db.query(SettingsModel).filter(SettingsModel.key == SETTINGS_KEY).first()
    if row is None:
        db.add(SettingsModel(key=SETTINGS_KEY, value=current))
    else:
        row.value = current
    db.commit()
    return get_current_settings(db)
