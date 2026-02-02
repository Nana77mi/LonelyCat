from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from memory.db import ConversationModel, MessageModel, SessionLocal, init_db
from memory.schemas import MessageRole

# 初始化数据库
init_db()

router = APIRouter()

# Try to import agent_worker, but make it optional for testing
try:
    from agent_worker.chat_flow import chat_flow
    AGENT_WORKER_AVAILABLE = True
except ImportError:
    AGENT_WORKER_AVAILABLE = False
    chat_flow = None  # type: ignore


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


class MessageCreateRequest(BaseModel):
    """创建 Message 请求"""
    content: str
    role: Optional[str] = None  # 如果提供，直接创建消息；如果不提供，会调用 worker
    source_ref: Optional[Dict[str, Any]] = None
    meta_json: Optional[Dict[str, Any]] = None


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


async def _create_message(
    conversation_id: str,
    request: MessageCreateRequest,
    db: Session,
    persona_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建消息（内部函数，便于测试）
    
    如果 request.role 已提供，直接创建消息。
    如果 request.role 未提供，创建 user 消息，调用 worker，然后创建 assistant 消息。
    """
    # 检查对话是否存在
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    now = datetime.utcnow()
    
    # 如果指定了 role，直接创建消息
    if request.role:
        message_id = str(uuid.uuid4())
        try:
            role_enum = MessageRole(request.role)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid role: {request.role}")
        
        message = MessageModel(
            id=message_id,
            conversation_id=conversation_id,
            role=role_enum,
            content=request.content,
            created_at=now,
            source_ref=request.source_ref,
            meta_json=request.meta_json,
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        
        # 更新 conversation 的 updated_at
        conversation.updated_at = now
        db.commit()
        
        return {
            "user_message": _serialize_message(message) if role_enum == MessageRole.USER else None,
            "assistant_message": _serialize_message(message) if role_enum == MessageRole.ASSISTANT else None,
        }
    
    # 否则，创建 user 消息，调用 worker，然后创建 assistant 消息
    # 1. 创建 user message
    user_message_id = str(uuid.uuid4())
    user_message = MessageModel(
        id=user_message_id,
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=request.content,
        created_at=now,
        source_ref=request.source_ref,
        meta_json=request.meta_json,
    )
    db.add(user_message)
    # 更新 conversation 的 updated_at（每次创建 message 时都更新）
    conversation.updated_at = now
    db.commit()
    db.refresh(user_message)
    
    # 2. 调用 worker 处理消息
    if not AGENT_WORKER_AVAILABLE or chat_flow is None:
        # 如果 worker 不可用，返回一个默认回复
        assistant_content = "I'm sorry, the agent worker is not available."
    else:
        try:
            result = chat_flow(
                user_message=request.content,
                persona_id=persona_id,
                llm=None,
                memory_client=None,
                config=None,
            )
            assistant_content = result.assistant_reply
        except Exception as e:
            # 如果 worker 调用失败，返回错误消息
            assistant_content = f"I encountered an error processing your message: {str(e)}"
    
    # 3. 创建 assistant message
    assistant_message_id = str(uuid.uuid4())
    assistant_now = datetime.utcnow()
    assistant_message = MessageModel(
        id=assistant_message_id,
        conversation_id=conversation_id,
        role=MessageRole.ASSISTANT,
        content=assistant_content,
        created_at=assistant_now,
        source_ref=None,
        meta_json=None,
    )
    db.add(assistant_message)
    
    # 4. 更新 conversation 的 updated_at
    conversation.updated_at = assistant_now
    db.commit()
    db.refresh(assistant_message)
    
    return {
        "user_message": _serialize_message(user_message),
        "assistant_message": _serialize_message(assistant_message),
    }


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


@router.post("/{conversation_id}/messages", response_model=Dict[str, Any])
async def create_message(
    conversation_id: str,
    request: MessageCreateRequest,
    db: Session = Depends(get_db),
    persona_id: Optional[str] = Query(None, description="Persona ID for the agent worker"),
) -> Dict[str, Any]:
    """创建消息
    
    如果 request.role 已提供，直接创建指定角色的消息。
    如果 request.role 未提供，创建 user 消息，调用 worker 处理，然后创建 assistant 消息。
    """
    return await _create_message(conversation_id, request, db, persona_id)
