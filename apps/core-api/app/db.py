from __future__ import annotations

import os
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker


class MessageRole(str, Enum):
    """消息角色枚举"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    source_ref = Column(JSON, nullable=True)
    meta_json = Column(JSON, nullable=True)

    # 关系
    conversation = relationship("ConversationModel", back_populates="messages")

    # 复合索引：用于查询某个对话的消息并按 created_at 排序
    __table_args__ = (
        Index("idx_messages_conversation_created", "conversation_id", "created_at"),
    )


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
