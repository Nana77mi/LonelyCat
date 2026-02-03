from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Optional

from sqlalchemy import and_, or_, update, func
from sqlalchemy.orm import Session

from worker.db import RunModel, RunStatus


def fetch_runnable_candidate(db: Session, now: datetime) -> Optional[str]:
    """获取可执行的候选 run ID
    
    候选包含两类：
    1. status = 'queued'
    2. status = 'running' AND lease_expires_at < now (租约过期，可接管)
    
    排序：先 queued，再过期 running，按 created_at ASC（公平）
    
    Args:
        db: 数据库会话
        now: 当前时间（UTC）
        
    Returns:
        第一个可执行的 run_id，如果没有则返回 None
    """
    # 查询 queued 的任务
    queued_run = (
        db.query(RunModel.id)
        .filter(RunModel.status == RunStatus.QUEUED)
        .order_by(RunModel.created_at.asc())
        .first()
    )
    
    if queued_run:
        return queued_run[0]
    
    # 查询租约过期的 running 任务
    expired_run = (
        db.query(RunModel.id)
        .filter(
            and_(
                RunModel.status == RunStatus.RUNNING,
                RunModel.lease_expires_at < now,
            )
        )
        .order_by(RunModel.created_at.asc())
        .first()
    )
    
    if expired_run:
        return expired_run[0]
    
    return None


def claim_run(
    db: Session,
    run_id: str,
    worker_id: str,
    lease_seconds: int,
) -> Optional[RunModel]:
    """原子性抢占 run
    
    只有当 run 仍然处于可抢占状态时才更新成功。
    更新字段：
    - status = 'running'
    - worker_id = worker_id
    - lease_expires_at = now + lease_seconds
    - attempt = attempt + 1
    - updated_at = now
    
    Args:
        db: 数据库会话
        run_id: Run ID
        worker_id: Worker ID
        lease_seconds: 租约时长（秒）
        
    Returns:
        如果抢占成功返回 RunModel，否则返回 None
    """
    now = datetime.now(UTC)
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    
    # 原子性 conditional update
    # 只有当 run 仍然处于可抢占状态时才更新
    # 使用 SQLAlchemy 的 update() 函数来处理 attempt + 1
    # 注意：使用 synchronize_session=False 避免 Python 层面的 datetime 比较问题
    stmt = (
        update(RunModel)
        .where(
            and_(
                RunModel.id == run_id,
                or_(
                    RunModel.status == RunStatus.QUEUED,
                    and_(
                        RunModel.status == RunStatus.RUNNING,
                        RunModel.lease_expires_at < now,
                    ),
                ),
            )
        )
        .values(
            status=RunStatus.RUNNING,
            worker_id=worker_id,
            lease_expires_at=lease_expires_at,
            attempt=RunModel.attempt + 1,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    
    db.commit()
    
    # 如果影响行数 = 1，说明抢占成功
    if result.rowcount == 1:
        # 重新查询以获取更新后的模型
        run = db.query(RunModel).filter(RunModel.id == run_id).first()
        return run
    
    return None


def fetch_and_claim_run(
    db: Session,
    worker_id: str,
    lease_seconds: int,
) -> Optional[RunModel]:
    """获取并抢占一个可执行的 run
    
    这是 fetch_runnable_candidate 和 claim_run 的包装函数。
    
    Args:
        db: 数据库会话
        worker_id: Worker ID
        lease_seconds: 租约时长（秒）
        
    Returns:
        如果抢占成功返回 RunModel，否则返回 None
    """
    now = datetime.now(UTC)
    run_id = fetch_runnable_candidate(db, now)
    
    if not run_id:
        return None
    
    return claim_run(db, run_id, worker_id, lease_seconds)


def heartbeat(
    db: Session,
    run_id: str,
    worker_id: str,
    lease_seconds: int,
) -> bool:
    """续租（心跳）
    
    续租时必须校验 worker_id 匹配，防止续租别人的任务。
    
    Args:
        db: 数据库会话
        run_id: Run ID
        worker_id: Worker ID（必须匹配）
        lease_seconds: 租约时长（秒）
        
    Returns:
        如果续租成功返回 True，否则返回 False
    """
    now = datetime.now(UTC)
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    
    # 续租：只有 owner 才能续租
    stmt = (
        update(RunModel)
        .where(
            and_(
                RunModel.id == run_id,
                RunModel.worker_id == worker_id,
                RunModel.status == RunStatus.RUNNING,
            )
        )
        .values(
            lease_expires_at=lease_expires_at,
            updated_at=now,
        )
    )
    result = db.execute(stmt)
    db.commit()
    
    # 影响行数 = 1 才算成功
    return result.rowcount == 1


def complete_success(
    db: Session,
    run_id: str,
    output_json: dict[str, Any],
) -> None:
    """完成任务（成功）
    
    更新字段：
    - status = 'succeeded'
    - output_json = output_json
    - progress = 100
    - error = NULL
    - lease_expires_at = NULL
    - updated_at = now
    
    Args:
        db: 数据库会话
        run_id: Run ID
        output_json: 任务输出
    """
    now = datetime.now(UTC)
    
    stmt = (
        update(RunModel)
        .where(RunModel.id == run_id)
        .values(
            status=RunStatus.SUCCEEDED,
            output_json=output_json,
            progress=100,
            error=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    db.execute(stmt)
    db.commit()


def complete_failed(
    db: Session,
    run_id: str,
    error_str: str,
) -> None:
    """完成任务（失败）
    
    更新字段：
    - status = 'failed'
    - error = error_str
    - lease_expires_at = NULL
    - updated_at = now
    
    Args:
        db: 数据库会话
        run_id: Run ID
        error_str: 错误信息
    """
    now = datetime.now(UTC)
    
    stmt = (
        update(RunModel)
        .where(RunModel.id == run_id)
        .values(
            status=RunStatus.FAILED,
            error=error_str,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    db.execute(stmt)
    db.commit()
