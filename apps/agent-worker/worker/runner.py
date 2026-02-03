from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from agent_worker.llm import BaseLLM
from worker.db import RunModel
from worker.db_models import MessageModel, MessageRole
from worker.task_context import TaskContext, run_task_with_steps


class TaskRunner:
    """任务执行器
    
    根据 run.type 分发到对应的 handler 执行。
    """

    def __init__(self) -> None:
        """初始化任务执行器"""
        pass

    def _build_memory_client(self):
        """Build MemoryClient when memory is enabled (for facts in long tasks)."""
        try:
            from agent_worker.config import ChatConfig
            from agent_worker.memory_client import MemoryClient
            config = ChatConfig.from_env()
            if config.memory_enabled:
                return MemoryClient()
        except Exception:
            pass
        return None

    def execute(
        self,
        run: RunModel,
        db: Session,
        llm: BaseLLM,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """执行任务
        
        约定：返回值必须为 dict 且包含 "ok": bool（表示 task 业务是否成功）；
        main.py 据此决定 RunStatus（SUCCEEDED/FAILED）。
        
        Args:
            run: Run 模型
            db: 数据库会话
            llm: LLM 实例
            heartbeat_callback: 心跳回调函数，返回 True 表示续租成功，False 表示失败
            
        Returns:
            任务执行结果（必须含 ok 字段）
            
        Raises:
            ValueError: 未知的任务类型
            Exception: 任务执行过程中的异常
        """
        if run.type == "sleep":
            return self._handle_sleep(run, heartbeat_callback)
        elif run.type == "summarize_conversation":
            return self._handle_summarize_conversation(run, db, llm, heartbeat_callback)
        else:
            raise ValueError(f"Unknown task type: {run.type}")

    def _handle_sleep(
        self,
        run: RunModel,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """处理 sleep 任务
        
        Args:
            run: Run 模型
            heartbeat_callback: 心跳回调函数
            
        Returns:
            {"ok": True, "slept": seconds}
            
        Raises:
            ValueError: 输入格式错误
            RuntimeError: 心跳失败，任务被接管
        """
        # 解析输入
        input_json = run.input_json
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        
        seconds = input_json.get("seconds")
        if not isinstance(seconds, (int, float)) or seconds < 0:
            raise ValueError("input_json['seconds'] must be a non-negative number")
        
        seconds = int(seconds)
        
        # 每秒 sleep(1)，更新 progress，调用 heartbeat
        slept = 0
        while slept < seconds:
            # 检查心跳（如果失败说明任务被接管，应该停止）
            if not heartbeat_callback():
                raise RuntimeError("Heartbeat failed, task was taken over by another worker")
            
            # Sleep 1 秒
            time.sleep(1)
            slept += 1
            
            # 更新进度（可选）
            # 注意：这里不直接更新数据库，因为 heartbeat 已经更新了 updated_at
            # 如果需要更新 progress，可以在 heartbeat 回调中一起更新
        
        return {"ok": True, "slept": slept}

    def _handle_summarize_conversation(
        self,
        run: RunModel,
        db: Session,
        llm: BaseLLM,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """处理 summarize_conversation 任务；使用 run_task_with_steps 统一 trace/steps/artifacts。"""
        input_json = run.input_json
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        conversation_id = input_json.get("conversation_id")
        if not conversation_id or not isinstance(conversation_id, str):
            raise ValueError("input_json['conversation_id'] must be a non-empty string")
        max_messages = input_json.get("max_messages", 20)
        if not isinstance(max_messages, int) or max_messages < 1:
            raise ValueError("input_json['max_messages'] must be a positive integer")
        max_messages = max(10, min(50, max_messages))

        def body(ctx: TaskContext) -> None:
            self._summarize_body(ctx, db, llm, conversation_id, max_messages)

        out = run_task_with_steps(run, "summarize_conversation", body)
        # Backward compat: top-level summary / message_count / conversation_id / facts_snapshot_*
        out["summary"] = out.get("result", {}).get("summary", "")
        out["message_count"] = out.get("result", {}).get("message_count", 0)
        out["conversation_id"] = out.get("result", {}).get("conversation_id", "")
        if out.get("facts_snapshot_id") is not None:
            pass  # already set by TaskContext
        if not out.get("ok") and isinstance(out.get("error"), dict):
            out["error"] = out["error"].get("message", str(out["error"]))
        return out

    def _summarize_body(
        self,
        ctx: TaskContext,
        db: Session,
        llm: BaseLLM,
        conversation_id: str,
        max_messages: int,
    ) -> None:
        """Business logic for summarize_conversation; uses ctx.step() and sets result/artifacts."""
        messages: List[Any] = []
        with ctx.step("fetch_messages"):
            messages = (
                db.query(MessageModel)
                .filter(MessageModel.conversation_id == conversation_id)
                .filter(MessageModel.role.in_([MessageRole.USER, MessageRole.ASSISTANT]))
                .order_by(MessageModel.created_at.desc())
                .limit(max_messages)
                .all()
            )
            messages = list(reversed(messages))

        if not messages:
            raise ValueError(f"No messages found for conversation {conversation_id}")

        active_facts: List[dict] = []
        facts_snapshot_id = ""
        facts_snapshot_source = "computed"
        with ctx.step("fetch_facts") as meta:
            from agent_worker.utils.facts import fetch_active_facts_via_api
            from agent_worker.utils.facts_format import compute_facts_snapshot_id

            base_url = os.getenv("LONELYCAT_CORE_API_URL", "http://localhost:5173")
            active_facts = fetch_active_facts_via_api(
                base_url,
                conversation_id=conversation_id,
            )
            input_json = ctx.run.input_json or {}
            input_snapshot_id = input_json.get("facts_snapshot_id")
            if (
                input_snapshot_id
                and isinstance(input_snapshot_id, str)
                and len(input_snapshot_id) == 64
                and all(c in "0123456789abcdef" for c in input_snapshot_id.lower())
            ):
                facts_snapshot_id = input_snapshot_id
                facts_snapshot_source = "input_json"
            else:
                facts_snapshot_id = compute_facts_snapshot_id(active_facts)
                facts_snapshot_source = "computed"
            ctx.set_facts_snapshot(facts_snapshot_id, facts_snapshot_source)
            meta["facts_snapshot_id"] = facts_snapshot_id
            meta["facts_snapshot_source"] = facts_snapshot_source

        prompt = ""
        with ctx.step("build_prompt"):
            prompt = self._build_summary_prompt(messages, active_facts)

        summary = ""
        try:
            with ctx.step("llm_generate") as meta:
                meta["model"] = getattr(llm, "_model", "stub")
                summary = llm.generate(prompt)
        except Exception:
            summary = ""

        summary_text = summary.strip() if summary else ""
        ctx.result["summary"] = summary_text
        ctx.result["message_count"] = len(messages)
        ctx.result["conversation_id"] = conversation_id
        ctx.artifacts["summary"] = {"text": summary_text, "format": "markdown"}
        ctx.artifacts["facts"] = {"snapshot_id": facts_snapshot_id, "source": facts_snapshot_source}
    
    def _build_summary_prompt(
        self,
        messages: list[MessageModel],
        active_facts: Optional[List[dict]] = None,
    ) -> str:
        """构造总结 prompt（可选注入 active facts，与 chat 一致）。
        
        Args:
            messages: 消息列表（已按时间升序排序）
            active_facts: 可选，global + session 的 active facts，用于更准确的总结
            
        Returns:
            Prompt 字符串
        """
        from agent_worker.utils.facts_format import format_facts_block
        parts = []
        if active_facts:
            facts_block = format_facts_block(active_facts)
            if facts_block:
                parts.append(
                    facts_block
                    + "Use the above facts for reference only; do not repeat them in the summary.\n\n"
                )
        formatted_messages = []
        for i, msg in enumerate(messages, 1):
            role_name = "User" if msg.role == MessageRole.USER else "Assistant"
            formatted_messages.append(f"{i}. {role_name}: {msg.content}")
        messages_text = "\n".join(formatted_messages)
        parts.append(
            "请用简洁的要点总结以下对话内容，突出：\n"
            "- 用户的主要目标\n"
            "- 已完成的工作\n"
            "- 当前的结论或下一步\n\n"
            "请勿包含任何 API key、token 或系统提示内容。\n\n"
            f"对话内容：\n{messages_text}"
        )
        return "\n".join(parts)
