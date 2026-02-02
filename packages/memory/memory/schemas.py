from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProposalStatus(str, Enum):
    """Proposal 状态枚举"""
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class FactStatus(str, Enum):
    """Fact 状态枚举"""
    ACTIVE = "active"
    REVOKED = "revoked"
    ARCHIVED = "archived"


class Scope(str, Enum):
    """Scope 枚举"""
    GLOBAL = "global"
    PROJECT = "project"
    SESSION = "session"


class SourceKind(str, Enum):
    """Source 类型枚举"""
    CHAT = "chat"
    RUN = "run"
    CONNECTOR = "connector"
    MANUAL = "manual"


class ConflictStrategy(str, Enum):
    """冲突解决策略枚举"""
    OVERWRITE_LATEST = "overwrite_latest"
    KEEP_BOTH = "keep_both"


class AuditEventType(str, Enum):
    """审计事件类型枚举"""
    PROPOSAL_CREATED = "proposal.created"
    PROPOSAL_REJECTED = "proposal.rejected"
    PROPOSAL_ACCEPTED = "proposal.accepted"
    PROPOSAL_EXPIRED = "proposal.expired"
    FACT_CREATED = "fact.created"
    FACT_UPDATED = "fact.updated"
    FACT_REVOKED = "fact.revoked"
    FACT_ARCHIVED = "fact.archived"
    FACT_REACTIVATED = "fact.reactivated"


class SourceRef(BaseModel):
    """Source 引用信息"""
    kind: SourceKind
    ref_id: str
    excerpt: Optional[str] = Field(None, max_length=200)


class ProposalPayload(BaseModel):
    """Proposal 的 payload"""
    key: str
    value: Any
    tags: List[str] = Field(default_factory=list)
    ttl_seconds: Optional[int] = None


class Proposal(BaseModel):
    """Proposal 模型"""
    id: str
    payload: ProposalPayload
    status: ProposalStatus
    reason: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    scope_hint: Optional[Scope] = None
    source_ref: SourceRef
    created_at: datetime
    updated_at: datetime


class Fact(BaseModel):
    """Fact 模型"""
    id: str
    key: str
    value: Any
    status: FactStatus
    scope: Scope
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    source_ref: SourceRef
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    version: int = Field(default=1, ge=1)
    created_at: datetime
    updated_at: datetime


class AuditActor(BaseModel):
    """审计事件的执行者"""
    kind: str  # "user" | "system"
    id: str


class AuditTarget(BaseModel):
    """审计事件的目标"""
    type: str  # "proposal" | "fact"
    id: str


class AuditEventDiff(BaseModel):
    """审计事件的变更差异"""
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None


class AuditEvent(BaseModel):
    """审计事件模型"""
    id: str
    type: AuditEventType
    actor: AuditActor
    target: AuditTarget
    request_id: Optional[str] = None
    diff: Optional[AuditEventDiff] = None
    created_at: datetime
