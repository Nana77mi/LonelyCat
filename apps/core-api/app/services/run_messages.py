"""Service for emitting run completion messages to conversations.

This module handles sending messages when runs complete, ensuring idempotency
and proper unread status management.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import ConversationModel, MessageModel, MessageRole, RunModel, RunStatus
from app.services.conversation_orchestrator import _extract_reply


# 写入 parent input 的 previous_output_json 最大字节数，避免 input_json 越滚越大
_PREVIOUS_OUTPUT_CAP_BYTES = 4096


def _cap_previous_output_for_input(output_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """将子 run 的 output_json 做成可写入 parent input 的预览（observation 等），避免整份 artifacts 塞入导致 input 膨胀。"""
    if not output_json or not isinstance(output_json, dict):
        return output_json
    import json
    preview: Dict[str, Any] = {}
    result = output_json.get("result") or {}
    if isinstance(result, dict) and result.get("observation") is not None:
        obs = result["observation"]
        if isinstance(obs, dict):
            preview["observation"] = dict(list(obs.items())[:5])
        else:
            preview["observation"] = obs
    if not preview and result:
        preview["result"] = result if isinstance(result, dict) else {"value": str(result)[:500]}
    if not preview:
        preview = dict(list(output_json.items())[:3])
    raw = json.dumps(preview, ensure_ascii=False)
    if len(raw.encode("utf-8")) <= _PREVIOUS_OUTPUT_CAP_BYTES:
        return preview
    return {"_truncated": True, "preview_bytes": len(raw.encode("utf-8"))}


def _extract_exec_id(output_json: Optional[Dict[str, Any]]) -> Optional[str]:
    """Resolve exec_id from output_json (result/observation/meta/artifacts). Aligns with frontend resolveExecId."""
    if not output_json or not isinstance(output_json, dict):
        return None
    result = output_json.get("result") or {}
    artifacts = output_json.get("artifacts") or {}
    candidates = [
        result.get("exec_id"),
        (result.get("observation") or {}).get("exec_id") if isinstance(result.get("observation"), dict) else None,
        (result.get("meta") or {}).get("exec_id") if isinstance(result.get("meta"), dict) else None,
        (artifacts.get("exec") or {}).get("exec_id") if isinstance(artifacts.get("exec"), dict) else None,
    ]
    for c in candidates:
        if isinstance(c, str) and c.strip() and c.startswith("e_") and len(c) == 18:
            return c
    return None


def _format_run_output_summary(output_json: Optional[Dict[str, Any]], run_type: Optional[str] = None) -> str:
    """格式化 run 输出摘要
    
    Args:
        output_json: Run 输出 JSON
        run_type: Run 类型（用于特殊格式化）
    """
    if not output_json:
        return "任务已完成。"
    
    # 尝试提取摘要信息
    if isinstance(output_json, dict):
        # 特殊处理：summarize_conversation 任务
        if run_type == "summarize_conversation" and "summary" in output_json:
            message_count = output_json.get("message_count", 0)
            summary = str(output_json["summary"])
            return f"📝 对话总结已完成（最近 {message_count} 条）：\n\n{summary}"
        
        # 特殊处理：research_report 任务，使用 artifacts.report.text 作为总结
        if (run_type or "").strip().replace(" ", "_") == "research_report":
            artifacts = output_json.get("artifacts") or {}
            report = artifacts.get("report")
            if isinstance(report, dict) and report.get("text"):
                text = str(report["text"]).strip()
                if text:
                    return f"📋 调研报告：\n\n{text}"
            result = output_json.get("result") or {}
            query = result.get("query", "")
            source_count = result.get("source_count", 0)
            return f"调研完成：{query or '（无 query）'}，共 {source_count} 个来源。"
        
        # 特殊处理：run_code_snippet，用 reply 摘要而非 str(result)，避免聊天里一坨 dict
        if (run_type or "").strip().replace(" ", "_") == "run_code_snippet":
            reply = _extract_reply(output_json)
            if reply:
                return reply
            exec_id = _extract_exec_id(output_json)
            return f"代码执行完成（exec_id={exec_id or 'unknown'}）。请在任务详情查看输出。"
        
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


def _wake_parent_run_if_waiting(db: Session, run: RunModel) -> None:
    """子 run 完成时若父 run 处于 WAIT_CHILD，则更新父 run 的 input 并重新入队。幂等：仅当 waiting_child_run_id==run.id 且 state 为 WAIT_CHILD 时推进并清空 waiting。"""
    parent_run_id = getattr(run, "parent_run_id", None) or (run.input_json or {}).get("parent_run_id")
    if not parent_run_id:
        return
    parent = db.query(RunModel).filter(RunModel.id == parent_run_id).first()
    if parent is None:
        return
    out = parent.output_json or {}
    if out.get("state") != "WAIT_CHILD":
        return
    waiting_run_id = out.get("waiting_child_run_id") or out.get("child_run_id")
    if waiting_run_id != run.id:
        return
    step_index = out.get("waiting_step_index", out.get("step_index", 0))
    run_ids = out.get("run_ids") or []
    merged_input = dict(parent.input_json or {})
    merged_input["step_index"] = step_index + 1
    merged_input["previous_output_json"] = _cap_previous_output_for_input(run.output_json)
    merged_input["run_ids"] = run_ids
    now = datetime.now(UTC)
    parent.input_json = merged_input
    # 只清空等待相关字段，保留 output_json 其余 debug 信息
    _wait_keys = ("state", "child_run_id", "waiting_child_run_id", "waiting_step_index", "run_ids")
    parent.output_json = {k: v for k, v in (parent.output_json or {}).items() if k not in _wait_keys}
    if not parent.output_json:
        parent.output_json = None
    parent.status = RunStatus.QUEUED
    parent.worker_id = None
    parent.lease_expires_at = None
    parent.updated_at = now
    try:
        db.commit()
    except Exception:
        db.rollback()


def emit_run_message(db: Session, run: RunModel) -> None:
    """在 run 完成时发送消息到对应的 conversation（幂等）
    
    根据 run.conversation_id 是否存在：
    - 如果存在：将消息发送到现有 conversation
    - 如果不存在：创建新 conversation
    
    同一轮已回复则跳过：run_code_snippet 若已在本对话的某条 agent_decision 消息的 meta.run_id/run_ids 中，
    说明 create_message 已在该轮返回了最终回答，不再插入第二条“任务完成”消息，避免重复展示。
    
    幂等性保证：检查是否已存在相同 source_ref.kind="run" 且 source_ref.ref_id=run.id 的消息，
    如果存在则跳过，避免重复通知。
    
    Unread 状态：基于 last_read_at 计算，如果用户正在查看对话（last_read_at >= updated_at），
    则不会标记为未读。
    
    Args:
        db: 数据库会话
        run: 已完成的 Run 对象（必须包含 status, conversation_id, title, type, output_json, error）
    """
    now = datetime.now(UTC)
    run_type_norm = (run.type or "").strip().replace(" ", "_")
    input_json = run.input_json or {}

    # run_code_snippet 若带 parent_run_id 表示由 agent_loop_turn 编排创建，由编排的 task_done 统一写总结，此处不写；并唤醒父 run
    if run_type_norm == "run_code_snippet" and input_json.get("parent_run_id"):
        _wake_parent_run_if_waiting(db, run)
        return

    # 幂等性检查：是否已存在相同 run 的完成消息（kind=run 或 kind=run_done）
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
    # 检查是否已存在该 run 的完成消息（source_ref.kind 为 "run" 或 "run_done"）
    try:
        existing_message = (
            db.query(MessageModel)
            .filter(
                MessageModel.source_ref.isnot(None),
                MessageModel.source_ref["ref_id"].astext == run.id,
                or_(
                    MessageModel.source_ref["kind"].astext == "run",
                    MessageModel.source_ref["kind"].astext == "run_done",
                ),
            )
            .first()
        )
    except Exception:
        all_messages_with_source_ref = (
            db.query(MessageModel)
            .filter(MessageModel.source_ref.isnot(None))
            .all()
        )
        existing_message = None
        for msg in all_messages_with_source_ref:
            if not isinstance(msg.source_ref, dict):
                continue
            ref_id = msg.source_ref.get("ref_id")
            kind = msg.source_ref.get("kind")
            if ref_id == run.id and kind in ("run", "run_done"):
                existing_message = msg
                break

    if existing_message:
        # 已存在，跳过（幂等）
        return
    
    # 生成消息内容与 source_ref
    if run_type_norm == "agent_loop_turn":
        # task_done：仅由编排完成时写入，content 取自 output_json.final_reply
        output_json = run.output_json or {}
        if run.status == RunStatus.SUCCEEDED:
            content = output_json.get("final_reply") or "任务已完成"
        elif run.status == RunStatus.FAILED:
            content = f"任务执行失败：{run.error or '未知错误'}"
        elif run.status == RunStatus.CANCELED:
            content = "任务已取消"
        else:
            content = f"任务状态：{run.status.value}"
        source_ref = {"kind": "run_done", "ref_id": run.id, "excerpt": None}
    else:
        if run.status == RunStatus.SUCCEEDED:
            if run.type == "summarize_conversation":
                content = _format_run_output_summary(run.output_json, run_type=run.type)
            elif run_type_norm == "research_report":
                content = _format_run_output_summary(run.output_json, run_type=run.type)
            else:
                content = f"任务已完成：{run.title or run.type}\n\n{_format_run_output_summary(run.output_json, run_type=run.type)}"
        elif run.status == RunStatus.FAILED:
            error_msg = run.error or "未知错误"
            content = f"任务执行失败：{run.title or run.type}\n\n错误：{error_msg}"
        elif run.status == RunStatus.CANCELED:
            content = f"任务已取消：{run.title or run.type}"
        else:
            content = f"任务状态：{run.status.value} - {run.title or run.type}"
        source_ref = {"kind": "run", "ref_id": run.id, "excerpt": None}

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
            source_ref=source_ref,
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
        # 使用 now + 1ms 作为 updated_at，避免时钟分辨率导致 updated_at == created_at（Windows 等）
        message_time = now + timedelta(milliseconds=1)
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
            source_ref=source_ref,
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
