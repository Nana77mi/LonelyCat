from __future__ import annotations

import time
from typing import Any, Callable, Dict

from sqlalchemy.orm import Session

from agent_worker.llm import BaseLLM
from worker.db import RunModel
from worker.db_models import MessageModel, MessageRole


class TaskRunner:
    """任务执行器
    
    根据 run.type 分发到对应的 handler 执行。
    """

    def __init__(self) -> None:
        """初始化任务执行器"""
        pass

    def execute(
        self,
        run: RunModel,
        db: Session,
        llm: BaseLLM,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """执行任务
        
        Args:
            run: Run 模型
            db: 数据库会话
            llm: LLM 实例
            heartbeat_callback: 心跳回调函数，返回 True 表示续租成功，False 表示失败
            
        Returns:
            任务执行结果
            
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
        """处理 summarize_conversation 任务
        
        Args:
            run: Run 模型
            db: 数据库会话
            llm: LLM 实例
            heartbeat_callback: 心跳回调函数
            
        Returns:
            {
                "summary": "string",
                "message_count": int,
                "conversation_id": "string"
            }
            
        Raises:
            ValueError: 输入格式错误
            RuntimeError: 心跳失败，任务被接管
        """
        # 1. 解析输入
        input_json = run.input_json
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        
        conversation_id = input_json.get("conversation_id")
        if not conversation_id or not isinstance(conversation_id, str):
            raise ValueError("input_json['conversation_id'] must be a non-empty string")
        
        max_messages = input_json.get("max_messages", 20)
        if not isinstance(max_messages, int) or max_messages < 1:
            raise ValueError("input_json['max_messages'] must be a positive integer")
        
        # Clamp max_messages to 10-50 range
        max_messages = max(10, min(50, max_messages))
        
        # 2. 查询最近 N 条消息（只取 user / assistant）
        messages = (
            db.query(MessageModel)
            .filter(MessageModel.conversation_id == conversation_id)
            .filter(MessageModel.role.in_([MessageRole.USER, MessageRole.ASSISTANT]))
            .order_by(MessageModel.created_at.desc())
            .limit(max_messages)
            .all()
        )
        messages = list(reversed(messages))  # Reverse to get ascending order
        
        if not messages:
            raise ValueError(f"No messages found for conversation {conversation_id}")
        
        # 3. 构造总结 prompt
        prompt = self._build_summary_prompt(messages)
        
        # 4. 调用 LLM
        # Note: llm.generate() is a blocking call, cannot insert heartbeat during execution
        # For summarize_conversation this is acceptable (< 10s expected)
        summary = llm.generate(prompt)
        
        # 5. 返回结果
        return {
            "summary": summary.strip(),
            "message_count": len(messages),
            "conversation_id": conversation_id,
        }
    
    def _build_summary_prompt(self, messages: list[MessageModel]) -> str:
        """构造总结 prompt
        
        Args:
            messages: 消息列表（已按时间升序排序）
            
        Returns:
            Prompt 字符串
        """
        # 格式化消息内容
        formatted_messages = []
        for i, msg in enumerate(messages, 1):
            role_name = "User" if msg.role == MessageRole.USER else "Assistant"
            formatted_messages.append(f"{i}. {role_name}: {msg.content}")
        
        messages_text = "\n".join(formatted_messages)
        
        prompt = f"""请用简洁的要点总结以下对话内容，突出：
- 用户的主要目标
- 已完成的工作
- 当前的结论或下一步

请勿包含任何 API key、token 或系统提示内容。

对话内容：
{messages_text}"""
        
        return prompt
