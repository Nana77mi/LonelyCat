from __future__ import annotations

import os
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    Integer,
    JSON,
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


class MessageRole(str, Enum):
    """消息角色枚举"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class RunStatus(str, Enum):
    """Run 状态枚举"""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


# 数据库配置
# 默认与 memory 包共享数据库（可通过 LONELYCAT_CORE_API_DB_URL 使用独立数据库）
# 这样可以复用同一个 SQLite 文件，但模型定义独立，避免耦合
DATABASE_URL = os.getenv(
    "LONELYCAT_CORE_API_DB_URL",
    os.getenv("LONELYCAT_MEMORY_DB_URL", "sqlite:///./lonelycat_memory.db")
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    echo=os.getenv("LONELYCAT_CORE_API_DB_ECHO", "").lower() == "true",
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class ConversationModel(Base):
    """Conversation 数据库模型"""
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # 关系
    messages = relationship("MessageModel", back_populates="conversation", cascade="all, delete-orphan")

    # 索引：用于按 updated_at 排序查询对话列表
    __table_args__ = (
        Index("idx_conversations_updated_at", "updated_at"),
    )


class MessageModel(Base):
    """Message 数据库模型"""
    __tablename__ = "messages"

    id = Column(String, primary_key=True, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(SQLEnum(MessageRole), nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    source_ref = Column(JSON, nullable=True)  # 格式：{"kind": "chat|run|connector|manual", "ref_id": "...", "excerpt": "..."}
    meta_json = Column(JSON, nullable=True)
    client_msg_id = Column(String, nullable=True, index=True)  # 客户端消息 ID，用于幂等性去重

    # 关系
    conversation = relationship("ConversationModel", back_populates="messages")

    # 复合索引：用于查询某个对话的消息并按 created_at 排序
    __table_args__ = (
        Index("idx_messages_conversation_created", "conversation_id", "created_at"),
    )


class RunModel(Base):
    """Run 数据库模型"""
    __tablename__ = "runs"

    id = Column(String, primary_key=True, index=True)
    type = Column(String, nullable=False)  # 任务类型，例如 "sleep", "summarize", "index_repo"
    status = Column(SQLEnum(RunStatus), nullable=False, index=True)
    conversation_id = Column(String, ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True)
    input_json = Column(JSON, nullable=False)  # 任务输入
    output_json = Column(JSON, nullable=True)  # 任务输出
    error = Column(Text, nullable=True)  # 失败信息
    worker_id = Column(String, nullable=True)  # worker ID（用于抢占/恢复）
    lease_expires_at = Column(DateTime, nullable=True)  # 租约过期时间
    attempt = Column(Integer, nullable=False, default=0)  # 重试次数
    progress = Column(Integer, nullable=True)  # 进度 0~100
    title = Column(String, nullable=True)  # UI 显示用
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    # 复合索引：用于 worker 查询 queued 任务
    # 索引：用于会话页查询
    __table_args__ = (
        Index("idx_runs_status_updated", "status", "updated_at"),
    )


def init_db() -> None:
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)
    # 迁移：添加 client_msg_id 列（如果不存在）
    _migrate_add_client_msg_id()


def _migrate_add_client_msg_id() -> None:
    """迁移：为 messages 表添加 client_msg_id 列（如果不存在）"""
    try:
        inspector = inspect(engine)
        # 检查表是否存在
        if "messages" not in inspector.get_table_names():
            return
        
        columns = [col["name"] for col in inspector.get_columns("messages")]
        
        if "client_msg_id" not in columns:
            # 添加 client_msg_id 列
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE messages ADD COLUMN client_msg_id VARCHAR"))
                conn.commit()
    except Exception as e:
        # 迁移失败不影响启动，只记录错误
        print(f"Warning: Failed to migrate client_msg_id column: {e}")


def get_db():
    """获取数据库会话（生成器函数，用于依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
