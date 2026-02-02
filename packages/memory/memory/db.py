from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum as SQLEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from memory.schemas import (
    AuditEventType,
    FactStatus,
    ProposalStatus,
    Scope,
    SourceKind,
)

# 数据库配置
DATABASE_URL = os.getenv(
    "LONELYCAT_MEMORY_DB_URL",
    "sqlite:///./lonelycat_memory.db"
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=os.getenv("LONELYCAT_MEMORY_DB_ECHO", "").lower() == "true",
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class ProposalModel(Base):
    """Proposal 数据库模型"""
    __tablename__ = "proposals"

    id = Column(String, primary_key=True, index=True)
    payload_key = Column(String, nullable=False, index=True)
    payload_value = Column(JSON, nullable=False)
    payload_tags = Column(JSON, default=[])
    ttl_seconds = Column(Integer, nullable=True)
    status = Column(SQLEnum(ProposalStatus), nullable=False, index=True)
    reason = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    scope_hint = Column(SQLEnum(Scope), nullable=True)
    source_ref_kind = Column(SQLEnum(SourceKind), nullable=False)
    source_ref_ref_id = Column(String, nullable=False)
    source_ref_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class FactModel(Base):
    """Fact 数据库模型"""
    __tablename__ = "facts"

    id = Column(String, primary_key=True, index=True)
    key = Column(String, nullable=False, index=True)
    value = Column(JSON, nullable=False)
    status = Column(SQLEnum(FactStatus), nullable=False, index=True)
    scope = Column(SQLEnum(Scope), nullable=False, index=True)
    project_id = Column(String, nullable=True, index=True)
    session_id = Column(String, nullable=True, index=True)
    source_ref_kind = Column(SQLEnum(SourceKind), nullable=False)
    source_ref_ref_id = Column(String, nullable=False)
    source_ref_excerpt = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 复合索引：用于查询同一 scope/key 的 active facts
    __table_args__ = (
        {"sqlite_autoincrement": True},
    )


class AuditEventModel(Base):
    """AuditEvent 数据库模型"""
    __tablename__ = "audit_events"

    id = Column(String, primary_key=True, index=True)
    type = Column(SQLEnum(AuditEventType), nullable=False, index=True)
    actor_kind = Column(String, nullable=False)  # "user" | "system"
    actor_id = Column(String, nullable=False)
    target_type = Column(String, nullable=False)  # "proposal" | "fact"
    target_id = Column(String, nullable=False, index=True)
    request_id = Column(String, nullable=True, index=True)
    diff_before = Column(JSON, nullable=True)
    diff_after = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class KeyPolicyModel(Base):
    """Key Policy 数据库模型（可选，用于存储 key 的冲突解决策略）"""
    __tablename__ = "key_policies"

    key = Column(String, primary_key=True, index=True)
    strategy = Column(String, nullable=False)  # "overwrite_latest" | "keep_both"
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db() -> None:
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)


def get_db():
    """获取数据库会话（生成器函数，用于依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
