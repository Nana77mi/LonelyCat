"""Internal API endpoints for cross-service communication.

These endpoints are used by worker and other internal services.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import RunModel, RunStatus, SessionLocal
from app.services.run_messages import emit_run_message

router = APIRouter(prefix="/internal", tags=["internal"])


def get_db():
    """获取数据库会话（依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/runs/{run_id}/emit-message", status_code=204)
async def emit_run_completion_message(
    run_id: str,
    db: Session = Depends(get_db),
) -> None:
    """内部 API：为完成的 run 发送消息到对应的 conversation
    
    这个端点由 worker 在 run 完成时调用。
    幂等性由 emit_run_message 函数保证。
    
    Args:
        run_id: Run ID
        db: 数据库会话
    """
    # 查询 run
    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # 只处理终态（succeeded/failed/canceled）
    if run.status not in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED):
        raise HTTPException(
            status_code=400,
            detail=f"Run {run_id} is not in a final state (current: {run.status.value})"
        )
    
    # 调用服务函数发送消息
    try:
        emit_run_message(db, run)
    except Exception as e:
        # 记录错误但不抛出异常（避免影响 run 的完成状态）
        print(f"Error: Failed to emit run message for run {run_id}: {e}")
        # 返回 500 但记录错误（可选：也可以返回 200 表示"已尝试"）
        raise HTTPException(
            status_code=500,
            detail=f"Failed to emit run message: {str(e)}"
        )
