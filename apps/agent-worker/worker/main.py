from __future__ import annotations

import json
import logging
import os
import random
import socket
import string
import time
from typing import Any, Dict

from worker.config import (
    RUN_HEARTBEAT_SECONDS,
    RUN_LEASE_SECONDS,
    RUN_MAX_ATTEMPTS,
    RUN_POLL_SECONDS,
)
from worker.db import get_db_session
from worker.queue import (
    complete_canceled,
    complete_failed,
    complete_success,
    fetch_and_claim_run,
    heartbeat,
)
from worker.db import RunStatus
from worker.runner import TaskRunner

logger = logging.getLogger(__name__)


def generate_worker_id() -> str:
    """生成 Worker ID
    
    Returns:
        Worker ID 格式：hostname-pid-random_str
    """
    hostname = socket.gethostname()
    pid = os.getpid()
    random_str = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"{hostname}-{pid}-{random_str}"


def execute_with_heartbeat(
    run_id: str,
    worker_id: str,
    runner: TaskRunner,
    db_session_factory,
    lease_seconds: int,
    heartbeat_seconds: int,
) -> Dict[str, Any]:
    """执行任务并定期发送心跳
    
    Args:
        run_id: Run ID
        worker_id: Worker ID
        runner: 任务执行器
        db_session_factory: 数据库会话工厂函数
        lease_seconds: 租约时长（秒）
        heartbeat_seconds: 心跳间隔（秒）
        
    Returns:
        任务执行结果
        
    Raises:
        RuntimeError: 心跳失败，任务被接管
        Exception: 任务执行过程中的异常
    """
    # 获取 run 对象（需要在执行过程中定期刷新）
    db = db_session_factory()
    try:
        from worker.db import RunModel
        
        run = db.query(RunModel).filter(RunModel.id == run_id).first()
        if not run:
            raise RuntimeError(f"Run {run_id} not found")
        
        # 创建心跳回调函数
        last_heartbeat_time = time.time()
        
        def heartbeat_callback() -> bool:
            """心跳回调函数"""
            nonlocal last_heartbeat_time
            
            current_time = time.time()
            # 如果距离上次心跳时间超过 heartbeat_seconds，执行心跳
            if current_time - last_heartbeat_time >= heartbeat_seconds:
                # 使用新的数据库会话
                heartbeat_db = db_session_factory()
                try:
                    # 检查 run 是否已被取消
                    current_run = heartbeat_db.query(RunModel).filter(RunModel.id == run_id).first()
                    if current_run and current_run.status == RunStatus.CANCELED:
                        raise RuntimeError("Task was canceled")
                    
                    success = heartbeat(heartbeat_db, run_id, worker_id, lease_seconds)
                    if success:
                        last_heartbeat_time = current_time
                    return success
                finally:
                    heartbeat_db.close()
            
            return True
        
        # 构建 LLM 实例
        from agent_worker.llm.factory import build_llm_from_env
        llm = build_llm_from_env()
        
        # 执行任务（agent_loop_turn 需要 worker_id/lease_seconds 以便在进程内执行子 run）
        result = runner.execute(
            run, db, llm, heartbeat_callback,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        return result
    finally:
        db.close()


def run_worker() -> None:
    """运行 Worker 主循环"""
    # 生成 Worker ID
    worker_id = generate_worker_id()
    print(f"Starting worker: {worker_id}")
    
    # 读取配置
    lease_seconds = RUN_LEASE_SECONDS
    heartbeat_seconds = RUN_HEARTBEAT_SECONDS
    poll_seconds = RUN_POLL_SECONDS
    max_attempts = RUN_MAX_ATTEMPTS
    
    print(f"Configuration: lease={lease_seconds}s, heartbeat={heartbeat_seconds}s, poll={poll_seconds}s")
    
    # 创建任务执行器
    runner = TaskRunner()
    
    # 主循环
    while True:
        db = get_db_session()
        try:
            # 尝试获取并抢占一个 run
            run = fetch_and_claim_run(db, worker_id, lease_seconds)
            
            if not run:
                # 没有可执行的任务，等待后继续
                db.close()
                time.sleep(poll_seconds)
                continue
            
            print(f"Claimed run {run.id} (type={run.type}, attempt={run.attempt})")
            
            # 执行前检查：如果 run 已被取消，直接 finalize
            if run.status == RunStatus.CANCELED:
                print(f"Run {run.id} was canceled before execution")
                complete_canceled(db, run.id, "Canceled before execution")
                db.close()
                continue
            
            # 检查最大重试次数
            if run.attempt > max_attempts:
                print(f"Run {run.id} exceeded max attempts ({max_attempts}), marking as failed")
                complete_failed(
                    db,
                    run.id,
                    f"Exceeded max attempts ({max_attempts})",
                )
                db.close()
                continue
            
            # 执行任务
            try:
                result = execute_with_heartbeat(
                    run.id,
                    worker_id,
                    runner,
                    get_db_session,
                    lease_seconds,
                    heartbeat_seconds,
                )
                
                # Handler 必须返回 dict 且包含 ok: bool；RunStatus 由 main 根据 ok 决定
                # DB runs.error 列为 Text，必须传字符串；result["error"] 可能为 dict（如 step 失败时的结构化错误）
                def _error_to_str(err: Any) -> str:
                    if err is None:
                        return "Task reported failure"
                    if isinstance(err, dict):
                        return err.get("message", json.dumps(err, default=str, ensure_ascii=False))
                    return str(err)

                if "ok" not in result:
                    logger.warning(
                        "Run %s handler returned output without 'ok' field; treating as failure",
                        run.id,
                    )
                    complete_failed(
                        db,
                        run.id,
                        _error_to_str(result.get("error")),
                        output_json=result,
                    )
                elif not result["ok"]:
                    print(f"Run {run.id} completed with failure (ok=False)")
                    complete_failed(
                        db,
                        run.id,
                        _error_to_str(result.get("error")),
                        output_json=result,
                    )
                elif result.get("yielded"):
                    # agent_loop_turn 已通过 yield-waiting-child 将父 run 置为 QUEUED，不调用 complete_success
                    print(f"Run {run.id} yielded (waiting for child), parent re-queued")
                else:
                    print(f"Run {run.id} completed successfully")
                    complete_success(db, run.id, result)
                
            except RuntimeError as e:
                error_msg = str(e)
                # 检查是否是取消异常
                if "canceled" in error_msg.lower() or "Task was canceled" in error_msg:
                    print(f"Run {run.id} was canceled during execution")
                    complete_canceled(db, run.id, "Canceled by user")
                else:
                    # 心跳失败，任务被接管
                    print(f"Run {run.id} heartbeat failed: {e}")
                    # 不需要调用 complete_failed，因为任务已经被其他 worker 接管
                db.close()
                continue
                
            except Exception as e:
                # 任务执行失败
                error_msg = str(e)
                print(f"Run {run.id} failed: {error_msg}")
                complete_failed(db, run.id, error_msg)
                
        except Exception as e:
            # 数据库操作异常
            print(f"Database error: {e}")
            db.rollback()
        finally:
            db.close()


def run() -> None:
    """入口函数（保持向后兼容）"""
    run_worker()


if __name__ == "__main__":
    run_worker()
