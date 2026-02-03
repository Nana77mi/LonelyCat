"""Utility functions for fetching and managing facts (core-api version).

Active facts 定义（与 HTTP GET /memory/facts 一致）：
- scope: global + session(conversation_id)，仅 status=ACTIVE，按 key 去重，session 覆盖 global。
- 序列化与 memory API _serialize_fact 结构一致，便于 HTTP 与 store 结果可互换。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from agent_worker.memory_client import MemoryClient

# Optional: for in-process fetch (no HTTP self-call)
try:
    from memory.facts import MemoryStore
    from memory.schemas import Fact, FactStatus, Scope
    import memory.db as _memory_db_module
    _MEMORY_STORE_AVAILABLE = True
except ImportError:
    MemoryStore = None  # type: ignore
    Fact = None
    FactStatus = None
    Scope = None
    _memory_db_module = None  # type: ignore
    _MEMORY_STORE_AVAILABLE = False


def _get_db_path() -> str:
    """用于日志：当前 memory DB 路径"""
    if _memory_db_module is not None:
        return getattr(_memory_db_module, "DATABASE_URL", "") or os.getenv("LONELYCAT_MEMORY_DB_URL", "(default)")
    return os.getenv("LONELYCAT_MEMORY_DB_URL", "(default)")

logger = logging.getLogger(__name__)

# 与 worker 约定：透传 facts 的 schema 版本，便于契约稳定性排查
ACTIVE_FACTS_SCHEMA_VERSION = 1

# 默认最大透传条数，避免 global 积压导致 payload/上下文膨胀
DEFAULT_ACTIVE_FACTS_LIMIT = 100


def _ensure_json_safe(value: Any) -> Any:
    """与 memory API 一致：确保 value 可 JSON 序列化"""
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def fact_to_dict(fact: "Fact") -> Dict[str, Any]:
    """
    序列化 memory.schemas.Fact 为 dict，与 HTTP API _serialize_fact 结构一致。
    保证 store 取到的 facts 与 GET /memory/facts 返回可互换（结构等价 + 可序列化）。
    """
    return {
        "id": fact.id,
        "key": fact.key,
        "value": _ensure_json_safe(fact.value),
        "status": fact.status.value,
        "scope": fact.scope.value,
        "project_id": fact.project_id,
        "session_id": fact.session_id,
        "source_ref": {
            "kind": fact.source_ref.kind.value if hasattr(fact.source_ref.kind, "value") else str(fact.source_ref.kind),
            "ref_id": fact.source_ref.ref_id,
            "excerpt": fact.source_ref.excerpt,
        },
        "confidence": fact.confidence,
        "version": fact.version,
        "created_at": fact.created_at.isoformat() if hasattr(fact.created_at, "isoformat") else str(fact.created_at),
        "updated_at": fact.updated_at.isoformat() if hasattr(fact.updated_at, "isoformat") else str(fact.updated_at),
    }


def _classify_exception(exc: BaseException) -> str:
    """异常分级：DB/schema/反序列化 vs 单条解析等"""
    name = type(exc).__name__
    if name in ("OperationalError", "ProgrammingError", "InterfaceError", "DatabaseError"):
        return "db"
    if "schema" in str(exc).lower() or "migration" in str(exc).lower():
        return "schema"
    if "serialize" in str(exc).lower() or "json" in str(exc).lower() or "encode" in str(exc).lower():
        return "serialization"
    return "unknown"


async def fetch_active_facts_from_store(
    store: "MemoryStore",
    *,
    conversation_id: Optional[str] = None,
    project_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    从 MemoryStore 直接获取 active facts（不经过 HTTP，避免同进程自调用阻塞/超时）。

    过滤逻辑与 HTTP GET /memory/facts 一致：仅 ACTIVE，global + session(conversation_id)，
    按 key 去重，session 覆盖 global；可选 limit 控制条数。

    Returns:
        (facts_list, source_literal)
        - source_literal: "store" 表示正常返回（含 count=0）；"fallback_zero" 表示异常降级为空。
    """
    limit = limit if limit is not None else DEFAULT_ACTIVE_FACTS_LIMIT
    db_path = _get_db_path()

    # Debug: fetch 前
    logger.info(
        "[FACTS_DEBUG] memory.list_facts.start conversation_id=%s scope_query=global+session(conversation_id) db_path=%s limit=%s",
        conversation_id,
        db_path,
        limit,
    )

    if not _MEMORY_STORE_AVAILABLE or store is None:
        logger.warning("[FACTS_DEBUG] memory.list_facts.skip store_unavailable")
        return [], "fallback_zero"

    facts_by_key: Dict[str, Dict[str, Any]] = {}
    count_by_scope: Dict[str, int] = {"global": 0, "session": 0}
    count_by_status: Dict[str, int] = {}

    try:
        # 1. Global scope（与 HTTP 一致：只取 ACTIVE）
        global_facts = await store.list_facts(scope=Scope.GLOBAL, status=FactStatus.ACTIVE)
        count_by_scope["global"] = len(global_facts)
        for f in global_facts:
            c = getattr(f.status, "value", str(f.status))
            count_by_status[c] = count_by_status.get(c, 0) + 1
        for fact in global_facts:
            if fact.key:
                try:
                    facts_by_key[fact.key] = fact_to_dict(fact)
                except Exception as parse_exc:
                    logger.warning(
                        "[FACTS_DEBUG] memory.list_facts.parse_fail fact_id=%s key=%s error=%s",
                        getattr(fact, "id", ""),
                        getattr(fact, "key", ""),
                        parse_exc,
                    )

        # 2. Session scope（conversation_id 即 session_id，与 HTTP 一致）
        if conversation_id:
            session_facts = await store.list_facts(
                scope=Scope.SESSION,
                session_id=conversation_id,
                status=FactStatus.ACTIVE,
            )
            count_by_scope["session"] = len(session_facts)
            for f in session_facts:
                c = getattr(f.status, "value", str(f.status))
                count_by_status[c] = count_by_status.get(c, 0) + 1
            for fact in session_facts:
                if fact.key:
                    try:
                        facts_by_key[fact.key] = fact_to_dict(fact)
                    except Exception as parse_exc:
                        logger.warning(
                            "[FACTS_DEBUG] memory.list_facts.parse_fail fact_id=%s key=%s error=%s",
                            getattr(fact, "id", ""),
                            getattr(fact, "key", ""),
                            parse_exc,
                        )

        # 3. 稳定排序 + limit（按 key 排序便于回归测试 byte-level 等价）
        ordered = sorted(facts_by_key.values(), key=lambda x: (x.get("key") or "", x.get("id") or ""))
        if len(ordered) > limit:
            ordered = ordered[:limit]
            logger.info("[FACTS_DEBUG] memory.list_facts.limited total=%s limit=%s", len(facts_by_key), limit)

        # Debug: fetch 后
        logger.info(
            "[FACTS_DEBUG] memory.list_facts.finish count=%s source=store count_by_scope=%s count_by_status=%s",
            len(ordered),
            count_by_scope,
            count_by_status,
        )
        return ordered, "store"

    except Exception as exc:
        error_type = _classify_exception(exc)
        logger.error(
            "[FACTS_DEBUG] memory.list_facts.error conversation_id=%s db_path=%s error_type=%s exception=%s",
            conversation_id,
            db_path,
            error_type,
            f"{type(exc).__name__}: {exc}",
            exc_info=True,
        )
        logger.info(
            "[FACTS_DEBUG] memory.list_facts.finish count=0 source=fallback_zero error_type=%s",
            error_type,
        )
        return [], "fallback_zero"


def fetch_active_facts(
    memory_client: MemoryClient,
    *,
    conversation_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    统一获取 active facts 的函数（经 HTTP 调用 memory 服务时使用）。

    去重规则：按 key 去重，优先级 session > project > global。
    过滤：仅 status=active（与 store 侧 ACTIVE 一致）。
    """
    facts_by_key: Dict[str, Dict[str, Any]] = {}

    try:
        global_facts = memory_client.list_facts(scope="global", status="active")
        for fact in global_facts:
            if fact.get("status") == "active":
                key = fact.get("key", "")
                if key:
                    facts_by_key[key] = fact

        if conversation_id:
            try:
                session_facts = memory_client.list_facts(
                    scope="session",
                    session_id=conversation_id,
                    status="active",
                )
                for fact in session_facts:
                    if fact.get("status") == "active":
                        key = fact.get("key", "")
                        if key:
                            facts_by_key[key] = fact
            except Exception:
                pass

        return list(facts_by_key.values())
    except Exception:
        return []


def _canonical_value_for_snapshot(value: Any) -> str:
    """Stable string for a fact value (for hashing). Must match agent_worker.utils.facts_format."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def compute_facts_snapshot_id(active_facts: List[Dict[str, Any]]) -> str:
    """
    Compute a stable, content-based snapshot ID for a set of active facts.
    Same fact set → same snapshot_id. Canonical rules must match agent_worker.utils.facts_format:
    - Only status=="active", non-empty key.
    - Sort by (id or ""), then key.
    - Canonical uses only stable fields: id, key, value. Do NOT include created_at,
      updated_at, source_ref, etc.
    Returns 64-char hex string (SHA-256).
    """
    active = [f for f in active_facts if f.get("status") == "active" and f.get("key")]
    ordered = sorted(
        active,
        key=lambda f: (f.get("id") or "", f.get("key") or ""),
    )
    canonical_list = [
        {
            "id": f.get("id"),
            "key": f.get("key"),
            "value": _canonical_value_for_snapshot(f.get("value")),
        }
        for f in ordered
    ]
    canonical_json = json.dumps(
        canonical_list,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
