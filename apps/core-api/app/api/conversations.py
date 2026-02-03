from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.agent_loop_config import AGENT_LOOP_ENABLED
from app.api.runs import RunCreateRequest, _create_run, _list_conversation_runs
from app.db import ConversationModel, MessageModel, MessageRole, SessionLocal

router = APIRouter()

# Try to import agent_worker, but make it optional for testing
try:
    from agent_worker.chat_flow import chat_flow
    AGENT_WORKER_AVAILABLE = True
except ImportError:
    AGENT_WORKER_AVAILABLE = False
    chat_flow = None  # type: ignore

# Try to import Agent Decision service
try:
    from app.services.agent_decision import AgentDecision
    AGENT_DECISION_AVAILABLE = True
except ImportError:
    AGENT_DECISION_AVAILABLE = False
    AgentDecision = None  # type: ignore

logger = logging.getLogger(__name__)


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


class ConversationUpdateRequest(BaseModel):
    """更新 Conversation 请求"""
    title: Optional[str] = None


class MessageCreateRequest(BaseModel):
    """创建 Message 请求"""
    content: str
    role: Optional[str] = None  # 如果提供，直接创建消息；如果不提供，会调用 worker
    source_ref: Optional[Dict[str, Any]] = None
    meta_json: Optional[Dict[str, Any]] = None
    client_msg_id: Optional[str] = None  # 客户端消息 ID，用于幂等性去重


class ConversationResponse(BaseModel):
    """Conversation 响应"""
    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    has_unread: bool = False
    last_read_at: Optional[datetime] = None
    meta_json: Optional[Dict[str, Any]] = None


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
    """序列化 Conversation 为字典
    
    注意：has_unread 是动态计算的，不存储。计算规则：
    - 如果 last_read_at is None：has_unread = (updated_at > created_at)
    - 如果 last_read_at is not None：has_unread = (updated_at > last_read_at)
    """
    from app.services.run_messages import _compute_has_unread
    
    # 确保时间包含时区信息（Z 表示 UTC）
    created_at_str = conv.created_at.isoformat()
    if not created_at_str.endswith('Z') and '+' not in created_at_str:
        created_at_str += 'Z'
    updated_at_str = conv.updated_at.isoformat()
    if not updated_at_str.endswith('Z') and '+' not in updated_at_str:
        updated_at_str += 'Z'
    
    last_read_at_str = None
    if conv.last_read_at:
        last_read_at_str = conv.last_read_at.isoformat()
        if not last_read_at_str.endswith('Z') and '+' not in last_read_at_str:
            last_read_at_str += 'Z'
    
    # 动态计算 has_unread（不存储，避免不一致）
    # 注意：在序列化时重新查询 conversation 确保获取最新的 updated_at
    has_unread = _compute_has_unread(conv)
    
    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": created_at_str,
        "updated_at": updated_at_str,
        "has_unread": has_unread,  # 动态计算
        "last_read_at": last_read_at_str,
        "meta_json": conv.meta_json,
    }


def _serialize_message(msg: MessageModel) -> Dict[str, Any]:
    """序列化 Message 为字典"""
    # 确保时间包含时区信息（Z 表示 UTC）
    created_at_str = msg.created_at.isoformat()
    if not created_at_str.endswith('Z') and '+' not in created_at_str:
        created_at_str += 'Z'
    
    return {
        "id": msg.id,
        "conversation_id": msg.conversation_id,
        "role": msg.role.value,
        "content": msg.content,
        "created_at": created_at_str,
        "source_ref": msg.source_ref,
        "meta_json": msg.meta_json,
        "client_msg_id": msg.client_msg_id,
    }


async def _list_conversations(
    db: Session,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Dict[str, Any]:
    """列出所有对话，按 updated_at 降序排列（内部函数，便于测试）
    
    支持分页参数 limit 和 offset。
    """
    query = db.query(ConversationModel).order_by(desc(ConversationModel.updated_at))
    
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    
    conversations = query.all()
    return {"items": [_serialize_conversation(conv) for conv in conversations]}


async def _create_conversation(request: ConversationCreateRequest, db: Session) -> Dict[str, Any]:
    """创建新对话（内部函数，便于测试）"""
    conversation_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    
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


async def _update_conversation(
    conversation_id: str,
    request: ConversationUpdateRequest,
    db: Session,
) -> Dict[str, Any]:
    """更新对话（内部函数，便于测试）"""
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    if request.title is not None:
        conversation.title = request.title
        conversation.updated_at = datetime.now(UTC)
    
    db.commit()
    db.refresh(conversation)
    
    return _serialize_conversation(conversation)


async def _mark_conversation_read(
    conversation_id: str,
    db: Session,
) -> Dict[str, Any]:
    """标记对话为已读（设置 last_read_at = now）（内部函数，便于测试）
    
    注意：has_unread 不再存储，改为序列化时动态计算。
    设置 last_read_at = max(now, updated_at)，确保 last_read_at >= updated_at。
    """
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # 刷新 conversation 确保获取最新的 updated_at
    db.refresh(conversation)
    
    # 设置 last_read_at = now，但确保它 > updated_at
    # 如果 now <= updated_at，则设置为 updated_at + 1微秒，确保 last_read_at > updated_at
    from datetime import timedelta
    
    now = datetime.now(UTC)
    if conversation.updated_at.tzinfo is None:
        updated_at_aware = conversation.updated_at.replace(tzinfo=UTC)
    else:
        updated_at_aware = conversation.updated_at
    
    # 确保 last_read_at > updated_at（严格大于）
    # 总是设置为 max(now, updated_at) + 至少1微秒，确保严格大于 updated_at
    # 注意：updated_at 有 onupdate 触发器，在 commit 时可能会自动更新
    # 所以我们先设置一个足够大的值，然后在 commit 后检查并调整
    conversation.last_read_at = max(now, updated_at_aware) + timedelta(microseconds=1000)  # 使用1毫秒而不是1微秒，更安全
    
    db.commit()
    
    # 重新查询 conversation 确保获取最新的状态（updated_at 可能有 onupdate 触发器）
    db.refresh(conversation)
    
    # 如果 updated_at 在 commit 后被更新（由于 onupdate 触发器），再次确保 last_read_at > updated_at
    if conversation.updated_at.tzinfo is None:
        current_updated_at = conversation.updated_at.replace(tzinfo=UTC)
    else:
        current_updated_at = conversation.updated_at
    
    # 确保 last_read_at 也是 timezone-aware
    if conversation.last_read_at.tzinfo is None:
        last_read_at_aware = conversation.last_read_at.replace(tzinfo=UTC)
    else:
        last_read_at_aware = conversation.last_read_at
    
    if last_read_at_aware <= current_updated_at:
        # 如果 last_read_at <= updated_at（由于 onupdate 触发器），设置为 updated_at + 1毫秒
        conversation.last_read_at = current_updated_at + timedelta(milliseconds=1)
        db.commit()
        db.refresh(conversation)
    
    return _serialize_conversation(conversation)


async def _delete_conversation(conversation_id: str, db: Session) -> None:
    """删除对话（内部函数，便于测试）
    
    注意：由于设置了 cascade="all, delete-orphan"，删除对话会自动删除所有关联的消息。
    """
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    db.delete(conversation)
    db.commit()


async def _get_conversation_messages(
    conversation_id: str,
    db: Session,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Dict[str, Any]:
    """获取指定对话的所有消息，按 created_at 升序排列（内部函数，便于测试）
    
    支持分页参数 limit 和 offset。
    """
    # 检查对话是否存在
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    query = (
        db.query(MessageModel)
        .filter(MessageModel.conversation_id == conversation_id)
        .order_by(MessageModel.created_at)
    )
    
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    
    messages = query.all()
    
    return {"items": [_serialize_message(msg) for msg in messages]}




async def _create_message(
    conversation_id: str,
    request: MessageCreateRequest,
    db: Session,
    persona_id: Optional[str] = None,
) -> Dict[str, Any]:
    """创建消息（内部函数，便于测试）
    
    如果 request.role 已提供，直接创建消息。
    如果 request.role 未提供，创建 user 消息，调用 worker，然后创建 assistant/system 消息。
    
    幂等性：如果提供了 client_msg_id，会检查是否已存在相同 client_msg_id 的消息。
    """
    # 检查对话是否存在
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    # 幂等性检查：如果提供了 client_msg_id，检查是否已存在
    if request.client_msg_id:
        existing_message = (
            db.query(MessageModel)
            .filter(
                MessageModel.conversation_id == conversation_id,
                MessageModel.client_msg_id == request.client_msg_id,
            )
            .first()
        )
        if existing_message:
            # 返回已存在的消息
            return {
                "user_message": _serialize_message(existing_message) if existing_message.role == MessageRole.USER else None,
                "assistant_message": _serialize_message(existing_message) if existing_message.role == MessageRole.ASSISTANT else None,
                "duplicate": True,
            }
    
    now = datetime.now(UTC)
    
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
            client_msg_id=request.client_msg_id,
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
        client_msg_id=request.client_msg_id,
    )
    db.add(user_message)
    # 更新 conversation 的 updated_at（每次创建 message 时都更新）
    conversation.updated_at = now
    try:
        db.commit()
        db.refresh(user_message)
    except Exception as e:
        # 数据库操作失败：回滚事务
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save user message: {str(e)}"
        )
    
    # 2. 查询历史消息并转换为 LLM 消息格式
    history_messages: list[dict[str, str]] = []
    try:
        # Query with limit to reduce DB load (MAX_MESSAGES + buffer for filtering)
        # Default MAX_MESSAGES is 40 (from chat_flow), so query 60 messages to account for filtering
        # Order by created_at DESC, then reverse to get ascending order
        # This is more efficient than .all() for conversations with many messages
        MAX_MESSAGES_LIMIT = 60  # MAX_MESSAGES (40) + buffer (20)
        history_messages_query = (
            db.query(MessageModel)
            .filter(MessageModel.conversation_id == conversation_id)
            .order_by(MessageModel.created_at.desc())
            .limit(MAX_MESSAGES_LIMIT)
            .all()
        )
        # Reverse to get ascending order (oldest first)
        history_messages_query.reverse()
        
        # 转换为 LLM 消息格式（只包含 USER 和 ASSISTANT 角色，跳过 SYSTEM）
        # 排除刚插入的最后一条 user message（避免重复，它会在 responder 中作为 current_user_message 添加）
        for msg in history_messages_query:
            # Skip the last user message that was just inserted (to avoid duplication)
            if msg.id == user_message_id:
                continue
            if msg.role == MessageRole.USER:
                history_messages.append({"role": "user", "content": msg.content})
            elif msg.role == MessageRole.ASSISTANT:
                history_messages.append({"role": "assistant", "content": msg.content})
            # 跳过 SYSTEM 角色的消息（错误消息等）
    except Exception as e:
        # 历史消息查询失败不影响主流程，只记录错误
        logger.warning(f"Failed to query history messages: {e}")
        history_messages = []
    
    # 3. Agent Decision Layer (if enabled)
    decision_used = False
    decision_run_id = None
    worker_error = None
    assistant_content = None
    
    if AGENT_LOOP_ENABLED and AGENT_DECISION_AVAILABLE and AgentDecision is not None:
        try:
            # Initialize Agent Decision service
            agent_decision = AgentDecision()
            
            # Gather context for decision
            active_facts = agent_decision.get_active_facts()
            
            # Get recent runs (optional, for avoiding duplicates)
            recent_runs = []
            try:
                runs_result = await _list_conversation_runs(conversation_id, db, limit=5, offset=0)
                recent_runs = runs_result.get("items", [])
            except Exception as e:
                logger.warning(f"Failed to query recent runs: {e}")
                recent_runs = []
            
            # Make decision
            logger.info(f"Making Agent Decision for conversation {conversation_id}")
            decision = agent_decision.decide(
                user_message=request.content,
                conversation_id=conversation_id,
                history_messages=history_messages,
                active_facts=active_facts,
                recent_runs=recent_runs,
            )
            
            decision_used = True
            logger.info(
                f"Decision made: decision={decision.decision}, "
                f"confidence={decision.confidence}, conversation_id={conversation_id}"
            )
            
            # Execute decision
            if decision.decision == "reply":
                # Only reply, no run
                assistant_content = decision.reply.content if decision.reply else ""
                logger.info(f"Decision: reply-only, conversation_id={conversation_id}")
            
            elif decision.decision == "run":
                # Create run only, no immediate reply (or optional hint message)
                if decision.run:
                    try:
                        run_request = RunCreateRequest(
                            type=decision.run.type,
                            title=decision.run.title,
                            conversation_id=decision.run.conversation_id,
                            input=decision.run.input,
                        )
                        run_result = await _create_run(run_request, db)
                        decision_run_id = run_result.get("id")
                        logger.info(
                            f"Run created: run_id={decision_run_id}, type={decision.run.type}, "
                            f"conversation_id={conversation_id}"
                        )
                        
                        # Optional: Create hint message
                        if decision.run.title:
                            assistant_content = f"我已开始后台任务：{decision.run.title}，完成后会通知你。"
                        else:
                            assistant_content = f"我已开始后台任务：{decision.run.type}，完成后会通知你。"
                    except Exception as e:
                        logger.error(
                            f"Failed to create run: {e}, conversation_id={conversation_id}",
                            exc_info=True
                        )
                        # Fallback: create error message
                        assistant_content = f"抱歉，任务创建失败：{str(e)}"
            
            elif decision.decision == "reply_and_run":
                # Reply AND create run
                assistant_content = decision.reply.content if decision.reply else ""
                
                if decision.run:
                    try:
                        run_request = RunCreateRequest(
                            type=decision.run.type,
                            title=decision.run.title,
                            conversation_id=decision.run.conversation_id,
                            input=decision.run.input,
                        )
                        run_result = await _create_run(run_request, db)
                        decision_run_id = run_result.get("id")
                        logger.info(
                            f"Run created: run_id={decision_run_id}, type={decision.run.type}, "
                            f"conversation_id={conversation_id}"
                        )
                    except Exception as e:
                        logger.error(
                            f"Failed to create run: {e}, conversation_id={conversation_id}",
                            exc_info=True
                        )
                        # Still send reply, but add error note
                        if assistant_content:
                            assistant_content += f"\n\n（注：任务创建失败：{str(e)}）"
                        else:
                            assistant_content = f"抱歉，任务创建失败：{str(e)}"
        
        except Exception as e:
            # Decision failed: fallback to chat_flow
            import traceback
            error_traceback = traceback.format_exc()
            logger.warning(
                f"Agent Decision failed, falling back to chat_flow: {e}, "
                f"conversation_id={conversation_id}"
            )
            logger.debug(f"Decision error traceback:\n{error_traceback}")
            decision_used = False
    
    # 4. Fallback to chat_flow if Decision was not used or failed
    if not decision_used:
        if not AGENT_WORKER_AVAILABLE or chat_flow is None:
            # 如果 worker 不可用，创建 system 错误消息
            worker_error = "Agent worker is not available"
            assistant_content = None
        else:
            try:
                result = chat_flow(
                    user_message=request.content,
                    persona_id=persona_id,
                    llm=None,
                    memory_client=None,
                    config=None,
                    history_messages=history_messages if history_messages else None,
                )
                assistant_content = result.assistant_reply
            except Exception as e:
                # Worker 失败：记录错误，创建 system 错误消息
                import traceback
                error_traceback = traceback.format_exc()
                logger.error(f"Worker failed: {e}, conversation_id={conversation_id}")
                logger.debug(f"Worker error traceback:\n{error_traceback}")
                worker_error = str(e)
                assistant_content = None
    
    # 5. 创建 assistant/system 消息
    assistant_now = datetime.now(UTC)
    
    if worker_error:
        # Worker 失败：创建 system 错误消息，确保对话不中断
        assistant_message_id = str(uuid.uuid4())
        assistant_message = MessageModel(
            id=assistant_message_id,
            conversation_id=conversation_id,
            role=MessageRole.SYSTEM,
            content=f"执行失败：{worker_error}",
            created_at=assistant_now,
            source_ref={"kind": "manual", "ref_id": f"worker_error_{conversation_id}", "excerpt": None},
            meta_json={"error": True, "error_type": "worker_failure", "error_message": worker_error},
            client_msg_id=None,
        )
    else:
        # Worker/Decision 成功：创建 assistant 消息
        assistant_message_id = str(uuid.uuid4())
        
        # Build source_ref and meta_json based on whether Decision was used
        if decision_used:
            source_ref = {
                "kind": "agent_decision",
                "ref_id": conversation_id,
                "excerpt": None,
            }
            meta_json = {
                "agent_decision": True,
                "run_id": decision_run_id,
            }
        else:
            source_ref = {"kind": "chat", "ref_id": conversation_id, "excerpt": None}
            meta_json = None
        
        assistant_message = MessageModel(
            id=assistant_message_id,
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=assistant_content or "",
            created_at=assistant_now,
            source_ref=source_ref,
            meta_json=meta_json,
            client_msg_id=None,
        )
    
    db.add(assistant_message)
    
    # 6. 更新 conversation 的 updated_at（以 assistant/system 消息时间为准）
    conversation.updated_at = assistant_now
    try:
        db.commit()
        db.refresh(assistant_message)
    except Exception as e:
        # 数据库操作失败：回滚事务
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save assistant message: {str(e)}"
        )
    
    return {
        "user_message": _serialize_message(user_message),
        "assistant_message": _serialize_message(assistant_message),
    }


@router.get("", response_model=Dict[str, Any])
async def list_conversations(
    db: Session = Depends(get_db),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Maximum number of conversations to return"),
    offset: Optional[int] = Query(None, ge=0, description="Number of conversations to skip"),
) -> Dict[str, Any]:
    """列出所有对话，按 updated_at 降序排列
    
    支持分页参数 limit 和 offset，便于后续扩展。
    """
    return await _list_conversations(db, limit=limit, offset=offset)


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
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Maximum number of messages to return"),
    offset: Optional[int] = Query(None, ge=0, description="Number of messages to skip"),
) -> Dict[str, Any]:
    """获取指定对话的所有消息，按 created_at 升序排列
    
    支持分页参数 limit 和 offset，便于后续扩展。
    """
    return await _get_conversation_messages(conversation_id, db, limit=limit, offset=offset)


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


@router.patch("/{conversation_id}", response_model=Dict[str, Any])
async def update_conversation(
    conversation_id: str,
    request: ConversationUpdateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """更新对话
    
    目前支持更新标题。
    """
    return await _update_conversation(conversation_id, request, db)


@router.patch("/{conversation_id}/mark-read", response_model=Dict[str, Any])
async def mark_conversation_read(
    conversation_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """标记对话为已读
    
    清除 has_unread 标记。前端在打开对话时调用此端点。
    """
    return await _mark_conversation_read(conversation_id, db)


@router.get("/{conversation_id}/runs", response_model=Dict[str, Any])
async def get_conversation_runs(
    conversation_id: str,
    db: Session = Depends(get_db),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Maximum number of runs to return"),
    offset: Optional[int] = Query(None, ge=0, description="Number of runs to skip"),
) -> Dict[str, Any]:
    """获取指定会话的所有 Run，按 updated_at 降序排列
    
    支持分页参数 limit 和 offset，便于后续扩展。
    """
    return await _list_conversation_runs(conversation_id, db, limit=limit, offset=offset)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
) -> None:
    """删除对话
    
    删除对话及其所有关联的消息（级联删除）。
    """
    await _delete_conversation(conversation_id, db)
