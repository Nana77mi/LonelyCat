from __future__ import annotations

import time
from typing import Any, Callable, Dict

from worker.db import RunModel


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
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """执行任务
        
        Args:
            run: Run 模型
            heartbeat_callback: 心跳回调函数，返回 True 表示续租成功，False 表示失败
            
        Returns:
            任务执行结果
            
        Raises:
            ValueError: 未知的任务类型
            Exception: 任务执行过程中的异常
        """
        if run.type == "sleep":
            return self._handle_sleep(run, heartbeat_callback)
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
