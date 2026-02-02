from __future__ import annotations

import json
import os
from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel, Field

from memory.audit import AuditLogger
from memory.db import init_db, SessionLocal
from memory.facts import MemoryStore
from memory.schemas import (
    AuditEvent,
    ConflictStrategy,
    Fact,
    FactStatus,
    Proposal,
    ProposalPayload,
    ProposalStatus,
    Scope,
    SourceKind,
    SourceRef,
)

# 初始化数据库
init_db()

router = APIRouter()


class ProposalCreateRequest(BaseModel):
    """创建 Proposal 请求"""
    payload: ProposalPayload
    source_ref: SourceRef
    reason: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    scope_hint: Optional[Scope] = None


class ProposalAcceptRequest(BaseModel):
    """接受 Proposal 请求"""
    strategy: Optional[ConflictStrategy] = None
    scope: Optional[Scope] = None
    project_id: Optional[str] = None
    session_id: Optional[str] = None


class ProposalRejectRequest(BaseModel):
    """拒绝 Proposal 请求"""
    reason: Optional[str] = None


class FactStatusFilter(str):
    """Fact 状态过滤"""
    ACTIVE = "active"
    REVOKED = "revoked"
    ARCHIVED = "archived"
    ALL = "all"


class ProposalStatusFilter(str):
    """Proposal 状态过滤"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ALL = "all"


def _get_memory_store() -> MemoryStore:
    """获取 MemoryStore 实例（依赖注入）"""
    return MemoryStore()


def _ensure_json_safe(value: Any) -> Any:
    """确保值可以 JSON 序列化"""
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def _serialize_proposal(proposal: Proposal) -> Dict[str, Any]:
    """序列化 Proposal 为字典"""
    return {
        "id": proposal.id,
        "payload": {
            "key": proposal.payload.key,
            "value": _ensure_json_safe(proposal.payload.value),
            "tags": proposal.payload.tags,
            "ttl_seconds": proposal.payload.ttl_seconds,
        },
        "status": proposal.status.value,
        "reason": proposal.reason,
        "confidence": proposal.confidence,
        "scope_hint": proposal.scope_hint.value if proposal.scope_hint else None,
        "source_ref": {
            "kind": proposal.source_ref.kind.value,
            "ref_id": proposal.source_ref.ref_id,
            "excerpt": proposal.source_ref.excerpt,
        },
        "created_at": proposal.created_at.isoformat(),
        "updated_at": proposal.updated_at.isoformat(),
    }


def _serialize_fact(fact: Fact) -> Dict[str, Any]:
    """序列化 Fact 为字典"""
    return {
        "id": fact.id,
        "key": fact.key,
        "value": _ensure_json_safe(fact.value),
        "status": fact.status.value,
        "scope": fact.scope.value,
        "project_id": fact.project_id,
        "session_id": fact.session_id,
        "source_ref": {
            "kind": fact.source_ref.kind.value,
            "ref_id": fact.source_ref.ref_id,
            "excerpt": fact.source_ref.excerpt,
        },
        "confidence": fact.confidence,
        "version": fact.version,
        "created_at": fact.created_at.isoformat(),
        "updated_at": fact.updated_at.isoformat(),
    }


def _serialize_audit_event(event: AuditEvent) -> Dict[str, Any]:
    """序列化 AuditEvent 为字典"""
    result = {
        "id": event.id,
        "type": event.type.value,
        "actor": {
            "kind": event.actor.kind,
            "id": event.actor.id,
        },
        "target": {
            "type": event.target.type,
            "id": event.target.id,
        },
        "request_id": event.request_id,
        "created_at": event.created_at.isoformat(),
    }
    if event.diff:
        result["diff"] = {
            "before": event.diff.before,
            "after": event.diff.after,
        }
    return result


def _auto_accept_enabled() -> bool:
    """检查是否启用自动接受"""
    return os.getenv("MEMORY_AUTO_ACCEPT", "").strip() == "1"


def _auto_accept_min_confidence() -> float:
    """获取自动接受的最小置信度"""
    value = os.getenv("MEMORY_AUTO_ACCEPT_MIN_CONF", "").strip()
    if not value:
        return 0.85
    try:
        return float(value)
    except ValueError:
        return 0.85


def _should_auto_accept(payload: ProposalPayload, confidence: Optional[float]) -> bool:
    """判断是否应该自动接受 Proposal"""
    if not _auto_accept_enabled():
        return False
    if confidence is None or confidence < _auto_accept_min_confidence():
        return False
    return True


# Proposal 端点

@router.post("/proposals", response_model=Dict[str, Any])
async def create_proposal(
    request: ProposalCreateRequest,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """创建 Proposal"""
    proposal = await store.create_proposal(
        payload=request.payload,
        source_ref=request.source_ref,
        reason=request.reason,
        confidence=request.confidence,
        scope_hint=request.scope_hint,
    )
    
    # 检查是否应该自动接受
    if _should_auto_accept(request.payload, request.confidence):
        accepted = await store.accept_proposal(
            proposal.id,
            strategy=None,  # 使用默认策略
            scope=request.scope_hint,
            project_id=None,
            session_id=None,
        )
        if accepted is None:
            raise HTTPException(status_code=409, detail="Proposal already resolved")
        accepted_proposal, fact = accepted
        return {
            "status": accepted_proposal.status.value,
            "proposal": _serialize_proposal(accepted_proposal),
            "fact": _serialize_fact(fact),
        }
    
    return {
        "status": proposal.status.value,
        "proposal": _serialize_proposal(proposal),
        "fact": None,
    }


@router.get("/proposals", response_model=Dict[str, Any])
async def list_proposals(
    status: Optional[str] = None,
    scope_hint: Optional[str] = None,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """列出 Proposal"""
    status_filter = None
    if status and status != ProposalStatusFilter.ALL:
        try:
            status_filter = ProposalStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    scope_filter = None
    if scope_hint:
        try:
            scope_filter = Scope(scope_hint)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid scope_hint: {scope_hint}")
    
    proposals = await store.list_proposals(status=status_filter, scope_hint=scope_filter)
    return {"items": [_serialize_proposal(p) for p in proposals]}


@router.get("/proposals/{proposal_id}", response_model=Dict[str, Any])
async def get_proposal(
    proposal_id: str,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """获取 Proposal"""
    proposal = await store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return _serialize_proposal(proposal)


@router.post("/proposals/{proposal_id}/accept", response_model=Dict[str, Any])
async def accept_proposal(
    proposal_id: str,
    request: Optional[ProposalAcceptRequest] = None,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """接受 Proposal"""
    strategy = request.strategy if request else None
    scope = request.scope if request else None
    project_id = request.project_id if request else None
    session_id = request.session_id if request else None
    
    accepted = await store.accept_proposal(
        proposal_id,
        strategy=strategy,
        scope=scope,
        project_id=project_id,
        session_id=session_id,
    )
    if accepted is None:
        proposal = await store.get_proposal(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=400, detail="Proposal already resolved")
    
    proposal, fact = accepted
    return {
        "proposal": _serialize_proposal(proposal),
        "fact": _serialize_fact(fact),
    }


@router.post("/proposals/{proposal_id}/reject", response_model=Dict[str, Any])
async def reject_proposal(
    proposal_id: str,
    request: Optional[ProposalRejectRequest] = None,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """拒绝 Proposal"""
    proposal = await store.reject_proposal(
        proposal_id,
        resolved_reason=request.reason if request else None,
    )
    if proposal is None:
        existing = await store.get_proposal(proposal_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=400, detail="Proposal already resolved")
    return _serialize_proposal(proposal)


@router.post("/proposals/{proposal_id}/expire", response_model=Dict[str, Any])
async def expire_proposal(
    proposal_id: str,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """过期 Proposal"""
    proposal = await store.expire_proposal(proposal_id)
    if proposal is None:
        existing = await store.get_proposal(proposal_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=400, detail="Proposal cannot be expired")
    return _serialize_proposal(proposal)


# Fact 端点

@router.get("/facts", response_model=Dict[str, Any])
async def list_facts(
    scope: Optional[str] = None,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """列出 Fact"""
    scope_filter = None
    if scope:
        try:
            scope_filter = Scope(scope)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid scope: {scope}")
    
    status_filter = None
    if status and status != FactStatusFilter.ALL:
        try:
            status_filter = FactStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    facts = await store.list_facts(
        scope=scope_filter,
        project_id=project_id,
        session_id=session_id,
        status=status_filter,
    )
    return {"items": [_serialize_fact(f) for f in facts]}


@router.get("/facts/{fact_id}", response_model=Dict[str, Any])
async def get_fact(
    fact_id: str,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """获取 Fact"""
    fact = await store.get_fact(fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return _serialize_fact(fact)


@router.get("/facts/key/{key}", response_model=Dict[str, Any])
async def get_fact_by_key(
    key: str,
    scope: str,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """根据 key 获取 Fact"""
    try:
        scope_enum = Scope(scope)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid scope: {scope}")
    
    fact = await store.get_fact_by_key(key, scope_enum, project_id, session_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return _serialize_fact(fact)


@router.post("/facts/{fact_id}/revoke", response_model=Dict[str, Any])
async def revoke_fact(
    fact_id: str,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """撤销 Fact"""
    fact = await store.revoke_fact(fact_id)
    if fact is None:
        existing = await store.get_fact(fact_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Fact not found")
        raise HTTPException(status_code=400, detail="Fact cannot be revoked")
    return _serialize_fact(fact)


@router.post("/facts/{fact_id}/archive", response_model=Dict[str, Any])
async def archive_fact(
    fact_id: str,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """归档 Fact"""
    fact = await store.archive_fact(fact_id)
    if fact is None:
        existing = await store.get_fact(fact_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Fact not found")
        raise HTTPException(status_code=400, detail="Fact cannot be archived")
    return _serialize_fact(fact)


@router.post("/facts/{fact_id}/reactivate", response_model=Dict[str, Any])
async def reactivate_fact(
    fact_id: str,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """重新激活 Fact"""
    fact = await store.reactivate_fact(fact_id)
    if fact is None:
        existing = await store.get_fact(fact_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Fact not found")
        raise HTTPException(status_code=400, detail="Fact cannot be reactivated")
    return _serialize_fact(fact)


# Audit 端点

@router.get("/audit", response_model=Dict[str, Any])
async def list_audit_events(
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    event_type: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """查询审计事件"""
    from memory.schemas import AuditEventType
    
    event_type_enum = None
    if event_type:
        try:
            event_type_enum = AuditEventType(event_type)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")
    
    audit_logger = AuditLogger()
    events = audit_logger.get_events(
        target_type=target_type,
        target_id=target_id,
        event_type=event_type_enum,
        limit=limit,
        offset=offset,
    )
    return {"items": [_serialize_audit_event(e) for e in events]}


# 维护端点

@router.post("/maintenance/check-expired", response_model=Dict[str, Any])
async def check_expired_proposals(
    store: MemoryStore = Depends(_get_memory_store),
) -> Dict[str, Any]:
    """检查并过期过期的 Proposal"""
    expired_ids = await store.check_expired_proposals()
    return {"expired_ids": expired_ids}
