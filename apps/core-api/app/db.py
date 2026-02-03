from __future__ import annotations

import os
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
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
    last_read_at = Column(DateTime, nullable=True)  # 最后阅读时间，用于计算 has_unread（动态计算，不存储 bool）
    meta_json = Column(JSON, nullable=True)  # 元数据，用于系统创建的对话（如 {"kind": "system_run", "run_id": "...", "origin": "...", "channel_hint": "..."}）

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
    parent_run_id = Column(String, ForeignKey("runs.id", ondelete="SET NULL"), nullable=True, index=True)  # 父 run ID（用于追踪重试关系）
    canceled_at = Column(DateTime, nullable=True)  # 取消时间
    canceled_by = Column(String, nullable=True)  # 取消者（"user"/"system"）
    cancel_reason = Column(Text, nullable=True)  # 取消原因（可选）
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
    # 迁移：添加取消相关字段（如果不存在）
    _migrate_add_cancel_fields()
    # 迁移：添加 conversation 相关字段（如果不存在）
    _migrate_add_conversation_fields()


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


def _migrate_add_cancel_fields() -> None:
    """迁移：为 runs 表添加取消相关字段（如果不存在）"""
    try:
        inspector = inspect(engine)
        # 检查表是否存在
        if "runs" not in inspector.get_table_names():
            return
        
        columns = [col["name"] for col in inspector.get_columns("runs")]
        
        with engine.connect() as conn:
            # 添加 parent_run_id 列
            if "parent_run_id" not in columns:
                conn.execute(text("ALTER TABLE runs ADD COLUMN parent_run_id VARCHAR"))
                # 添加外键约束（SQLite 需要先添加列，再添加外键）
                # 注意：SQLite 的 ALTER TABLE 不支持直接添加外键，这里只添加列
                # 外键约束会在新表创建时自动添加
            
            # 添加 canceled_at 列
            if "canceled_at" not in columns:
                conn.execute(text("ALTER TABLE runs ADD COLUMN canceled_at DATETIME"))
            
            # 添加 canceled_by 列
            if "canceled_by" not in columns:
                conn.execute(text("ALTER TABLE runs ADD COLUMN canceled_by VARCHAR"))
            
            # 添加 cancel_reason 列
            if "cancel_reason" not in columns:
                conn.execute(text("ALTER TABLE runs ADD COLUMN cancel_reason TEXT"))
            
            conn.commit()
    except Exception as e:
        # 迁移失败不影响启动，只记录错误
        print(f"Warning: Failed to migrate cancel fields: {e}")


def _migrate_add_conversation_fields() -> None:
    """迁移：为 conversations 表添加 last_read_at 和 meta_json 字段（如果不存在）
    
    注意：has_unread 不再存储为字段，改为序列化时动态计算。
    如果数据库中已有 has_unread 列，保留但不使用（向后兼容）。
    """
    try:
        inspector = inspect(engine)
        # 检查表是否存在
        if "conversations" not in inspector.get_table_names():
            return
        
        columns = [col["name"] for col in inspector.get_columns("conversations")]
        
        with engine.connect() as conn:
            # 添加 last_read_at 列
            if "last_read_at" not in columns:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN last_read_at DATETIME"))
            
            # 添加 meta_json 列
            if "meta_json" not in columns:
                conn.execute(text("ALTER TABLE conversations ADD COLUMN meta_json JSON"))
            
            # 注意：has_unread 列如果存在则保留（向后兼容），但不再使用
            # 新代码中 has_unread 是动态计算的，不存储
            
            conn.commit()
    except Exception as e:
        # 迁移失败不影响启动，只记录错误
        print(f"Warning: Failed to migrate conversation fields: {e}")


def get_db():
    """获取数据库会话（生成器函数，用于依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
