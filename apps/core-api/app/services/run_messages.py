"""Service for emitting run completion messages to conversations.

This module handles sending messages when runs complete, ensuring idempotency
and proper unread status management.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.db import ConversationModel, MessageModel, MessageRole, RunModel, RunStatus


def _format_run_output_summary(output_json: Optional[Dict[str, Any]]) -> str:
    """格式化 run 输出摘要"""
    if not output_json:
        return "任务已完成。"
    
    # 尝试提取摘要信息
    if isinstance(output_json, dict):
        # 如果有 summary 字段，使用它
        if "summary" in output_json:
            return str(output_json["summary"])
        # 如果有 message 字段，使用它
        if "message" in output_json:
            return str(output_json["message"])
        # 如果有 result 字段，使用它
        if "result" in output_json:
            return str(output_json["result"])
        # 否则，尝试格式化整个输出（限制长度）
        output_str = str(output_json)
        if len(output_str) > 500:
            return output_str[:500] + "..."
        return output_str
    
    # 如果不是字典，直接转换为字符串
    output_str = str(output_json)
    if len(output_str) > 500:
        return output_str[:500] + "..."
    return output_str


def _compute_has_unread(conversation: ConversationModel) -> bool:
    """计算 conversation 是否有未读消息
    
    规则：
    - 如果 last_read_at is None：
      - 如果 updated_at > created_at（有新消息），返回 True
      - 否则（刚创建，无消息），返回 False
    - 如果 last_read_at is not None：
      - 如果 updated_at > last_read_at（有新消息），返回 True
      - 否则返回 False
    """
    # 确保时间都是 timezone-aware 的
    updated_at = conversation.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    
    if conversation.last_read_at is None:
        # 从未读过：只有当有新消息（updated_at > created_at）时才有未读
        created_at = conversation.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return updated_at > created_at
    
    # 已读过：比较 updated_at 和 last_read_at
    last_read_at = conversation.last_read_at
    if last_read_at.tzinfo is None:
        last_read_at = last_read_at.replace(tzinfo=UTC)
    
    return updated_at > last_read_at


def emit_run_message(db: Session, run: RunModel) -> None:
    """在 run 完成时发送消息到对应的 conversation（幂等）
    
    根据 run.conversation_id 是否存在：
    - 如果存在：将消息发送到现有 conversation
    - 如果不存在：创建新 conversation
    
    幂等性保证：检查是否已存在相同 source_ref.kind="run" 且 source_ref.ref_id=run.id 的消息，
    如果存在则跳过，避免重复通知。
    
    Unread 状态：基于 last_read_at 计算，如果用户正在查看对话（last_read_at >= updated_at），
    则不会标记为未读。
    
    Args:
        db: 数据库会话
        run: 已完成的 Run 对象（必须包含 status, conversation_id, title, type, output_json, error）
    """
    now = datetime.now(UTC)
    
    # 幂等性检查：是否已存在相同 run 的消息
    # 
    # 性能说明：
    # - 当前实现：使用 JSON 字段查询（source_ref JSON）
    # - SQLite 下可接受，但消息量大时可能较慢
    # - 未来优化方向（PR-Run-6 级别）：
    #   1. 在 MessageModel 添加冗余列：source_kind (String), source_id (String)
    #   2. 对 (source_kind, source_id) 建复合索引
    #   3. source_ref JSON 字段保留完整信息，冗余列用于快速查询
    #   4. 这样可以将 O(n) 的 JSON 查询优化为 O(log n) 的索引查询
    #
    # 使用 SQLAlchemy 的 JSON 操作符（兼容 SQLite 3.38+ 和 PostgreSQL）
    # 如果数据库不支持，会回退到 Python 层面的过滤
    try:
        # 尝试使用 JSON 操作符（SQLite 3.38+ 和 PostgreSQL 支持）
        existing_message = (
            db.query(MessageModel)
            .filter(
                MessageModel.source_ref.isnot(None),
                MessageModel.source_ref["kind"].astext == "run",
                MessageModel.source_ref["ref_id"].astext == run.id,
            )
            .first()
        )
    except Exception:
        # 回退：查询所有 source_ref 不为空的消息，然后在 Python 中过滤
        # 注意：如果消息量很大，这个回退路径会很慢，建议尽快实现冗余列优化
        all_messages_with_source_ref = (
            db.query(MessageModel)
            .filter(MessageModel.source_ref.isnot(None))
            .all()
        )
        
        existing_message = None
        for msg in all_messages_with_source_ref:
            if (
                isinstance(msg.source_ref, dict)
                and msg.source_ref.get("kind") == "run"
                and msg.source_ref.get("ref_id") == run.id
            ):
                existing_message = msg
                break
    
    if existing_message:
        # 已存在，跳过（幂等）
        return
    
    # 生成消息内容
    if run.status == RunStatus.SUCCEEDED:
        content = f"任务已完成：{run.title or run.type}\n\n{_format_run_output_summary(run.output_json)}"
    elif run.status == RunStatus.FAILED:
        error_msg = run.error or "未知错误"
        content = f"任务执行失败：{run.title or run.type}\n\n错误：{error_msg}"
    elif run.status == RunStatus.CANCELED:
        content = f"任务已取消：{run.title or run.type}"
    else:
        # 不应该到达这里，但为了安全起见
        content = f"任务状态：{run.status.value} - {run.title or run.type}"
    
    # 情况 1：run.conversation_id != null - 发送到现有 conversation
    if run.conversation_id:
        conversation = db.query(ConversationModel).filter(ConversationModel.id == run.conversation_id).first()
        if conversation is None:
            # conversation 不存在，记录警告但不抛出异常
            print(f"Warning: Conversation {run.conversation_id} not found for run {run.id}")
            return
        
        # 创建 assistant 消息
        message_id = str(uuid.uuid4())
        message = MessageModel(
            id=message_id,
            conversation_id=run.conversation_id,
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=now,
            source_ref={"kind": "run", "ref_id": run.id, "excerpt": None},
            meta_json=None,
            client_msg_id=None,
        )
        db.add(message)
        
        # 更新 updated_at（消息创建时间）
        # 注意：has_unread 不再存储，改为序列化时动态计算
        conversation.updated_at = now
        
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Error: Failed to emit run message for run {run.id}: {e}")
            # 不抛出异常，避免影响 run 的完成状态
    
    # 情况 2：run.conversation_id == null - 创建新 conversation
    else:
        # 创建新 conversation
        conversation_id = str(uuid.uuid4())
        conversation_title = f"Task completed: {run.title or run.type}"
        # 使用稍后的时间作为 updated_at，确保 updated_at > created_at（有新消息）
        message_time = datetime.now(UTC)
        conversation = ConversationModel(
            id=conversation_id,
            title=conversation_title,
            created_at=now,
            updated_at=message_time,  # 设置为消息时间，确保 updated_at > created_at
            last_read_at=None,  # 新创建的 conversation 未读（has_unread 动态计算）
            meta_json={
                "kind": "system_run",
                "run_id": run.id,
                "origin": "run",  # 来源：run 完成
                "channel_hint": "web",  # 渠道提示：web（未来可扩展为 wechat/qq/slack）
            },
        )
        db.add(conversation)
        
        # 创建 assistant 消息
        message_id = str(uuid.uuid4())
        message = MessageModel(
            id=message_id,
            conversation_id=conversation_id,
            role=MessageRole.ASSISTANT,
            content=content,
            created_at=message_time,
            source_ref={"kind": "run", "ref_id": run.id, "excerpt": None},
            meta_json=None,
            client_msg_id=None,
        )
        db.add(message)
        
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"Error: Failed to create conversation and emit run message for run {run.id}: {e}")
            # 不抛出异常，避免影响 run 的完成状态
