from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from memory.db import ConversationModel, MessageModel, SessionLocal, init_db
from memory.schemas import MessageRole

# 初始化数据库
init_db()

router = APIRouter()


def get_db():
    """获取数据库会话（依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ConversationCreateRequest(BaseModel):
    """创建 Conversation 请求"""
    title: Optional[str] = "New chat"


class ConversationResponse(BaseModel):
    """Conversation 响应"""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    """Message 响应"""
    id: str
    conversation_id: str
    role: str
    content: str
    created_at: datetime
    source_ref: Optional[Dict[str, Any]] = None
    meta_json: Optional[Dict[str, Any]] = None


def _serialize_conversation(conv: ConversationModel) -> Dict[str, Any]:
    """序列化 Conversation 为字典"""
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
    }


def _serialize_message(msg: MessageModel) -> Dict[str, Any]:
    """序列化 Message 为字典"""
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "role": msg.role.value,
        "content": msg.content,
        "created_at": msg.created_at.isoformat(),
        "source_ref": msg.source_ref,
        "meta_json": msg.meta_json,
    }


async def _list_conversations(db: Session) -> Dict[str, Any]:
    """列出所有对话，按 updated_at 降序排列（内部函数，便于测试）"""
    conversations = db.query(ConversationModel).order_by(desc(ConversationModel.updated_at)).all()
    return {"items": [_serialize_conversation(conv) for conv in conversations]}


async def _create_conversation(request: ConversationCreateRequest, db: Session) -> Dict[str, Any]:
    """创建新对话（内部函数，便于测试）"""
    conversation_id = str(uuid.uuid4())
    now = datetime.utcnow()
    
    conversation = ConversationModel(
        id=conversation_id,
        title=request.title,
        created_at=now,
        updated_at=now,
    )
    
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    
    return _serialize_conversation(conversation)


async def _get_conversation_messages(conversation_id: str, db: Session) -> Dict[str, Any]:
    """获取指定对话的所有消息，按 created_at 升序排列（内部函数，便于测试）"""
    # 检查对话是否存在
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    messages = (
        db.query(MessageModel)
        .filter(MessageModel.conversation_id == conversation_id)
        .order_by(MessageModel.created_at)
        .all()
    )
    
    return {"items": [_serialize_message(msg) for msg in messages]}


@router.get("", response_model=Dict[str, Any])
async def list_conversations(
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """列出所有对话，按 updated_at 降序排列"""
    return await _list_conversations(db)


@router.post("", response_model=Dict[str, Any])
async def create_conversation(
    request: ConversationCreateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """创建新对话"""
    return await _create_conversation(request, db)


@router.get("/{conversation_id}/messages", response_model=Dict[str, Any])
async def get_conversation_messages(
    conversation_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """获取指定对话的所有消息，按 created_at 升序排列"""
    return await _get_conversation_messages(conversation_id, db)
