from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import ConversationModel, RunModel, RunStatus, SessionLocal

router = APIRouter()


def get_db():
    """获取数据库会话（依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class RunCreateRequest(BaseModel):
    """创建 Run 请求"""
    type: str
    title: Optional[str] = None
    conversation_id: Optional[str] = None
    input: Dict[str, Any]  # 任务输入
    metadata: Optional[Dict[str, Any]] = None  # 元数据（可选）


class RunResponse(BaseModel):
    """Run 响应"""
    id: str
    type: str
    title: Optional[str] = None
    status: str
    conversation_id: Optional[str] = None
    input: Dict[str, Any]
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    progress: Optional[int] = None
    attempt: int
    worker_id: Optional[str] = None
    lease_expires_at: Optional[str] = None
    created_at: str
    updated_at: str


class RunListResponse(BaseModel):
    """Run 列表响应"""
    items: list[Dict[str, Any]]
    limit: Optional[int] = None
    offset: Optional[int] = None


def _serialize_run(run: RunModel) -> Dict[str, Any]:
    """序列化 Run 为字典"""
    # 确保时间包含时区信息（Z 表示 UTC）
    created_at_str = run.created_at.isoformat()
    if not created_at_str.endswith('Z') and '+' not in created_at_str:
        created_at_str += 'Z'
    updated_at_str = run.updated_at.isoformat()
    if not updated_at_str.endswith('Z') and '+' not in updated_at_str:
        updated_at_str += 'Z'
    
    lease_expires_at_str = None
    if run.lease_expires_at:
        lease_expires_at_str = run.lease_expires_at.isoformat()
        if not lease_expires_at_str.endswith('Z') and '+' not in lease_expires_at_str:
            lease_expires_at_str += 'Z'
    
    return {
        "id": run.id,
        "type": run.type,
        "title": run.title,
        "status": run.status.value,
        "conversation_id": run.conversation_id,
        "input": run.input_json,
        "output": run.output_json,
        "error": run.error,
        "progress": run.progress,
        "attempt": run.attempt,
        "worker_id": run.worker_id,
        "lease_expires_at": lease_expires_at_str,
        "created_at": created_at_str,
        "updated_at": updated_at_str,
    }


async def _create_run(request: RunCreateRequest, db: Session) -> Dict[str, Any]:
    """创建新 Run（内部函数，便于测试）"""
    run_id = str(uuid.uuid4())
    now = datetime.now(UTC)
    
    # 验证 conversation_id 是否存在（如果提供）
    if request.conversation_id:
        conversation = db.query(ConversationModel).filter(ConversationModel.id == request.conversation_id).first()
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
    
    run = RunModel(
        id=run_id,
        type=request.type,
        title=request.title,
        status=RunStatus.QUEUED,
        conversation_id=request.conversation_id,
        input_json=request.input,
        output_json=None,
        error=None,
        worker_id=None,
        lease_expires_at=None,
        attempt=0,
        progress=None,
        created_at=now,
        updated_at=now,
    )
    
    db.add(run)
    db.commit()
    db.refresh(run)
    
    return _serialize_run(run)


async def _get_run(run_id: str, db: Session) -> Dict[str, Any]:
    """获取单个 Run（内部函数，便于测试）"""
    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    
    return _serialize_run(run)


async def _list_runs(
    db: Session,
    status: Optional[str] = None,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Dict[str, Any]:
    """列出所有 Run，按 updated_at 降序排列（内部函数，便于测试）
    
    支持按 status 过滤和分页参数 limit 和 offset。
    """
    query = db.query(RunModel)
    
    # 按 status 过滤
    if status:
        try:
            status_enum = RunStatus(status)
            query = query.filter(RunModel.status == status_enum)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    
    # 按 updated_at 降序排序
    query = query.order_by(desc(RunModel.updated_at))
    
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    
    runs = query.all()
    return {
        "items": [_serialize_run(run) for run in runs],
        "limit": limit,
        "offset": offset,
    }


async def _list_conversation_runs(
    conversation_id: str,
    db: Session,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
) -> Dict[str, Any]:
    """获取指定会话的所有 Run，按 updated_at 降序排列（内部函数，便于测试）
    
    支持分页参数 limit 和 offset。
    """
    # 检查对话是否存在
    conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    query = (
        db.query(RunModel)
        .filter(RunModel.conversation_id == conversation_id)
        .order_by(desc(RunModel.updated_at))
    )
    
    if offset is not None:
        query = query.offset(offset)
    if limit is not None:
        query = query.limit(limit)
    
    runs = query.all()
    return {
        "items": [_serialize_run(run) for run in runs],
        "limit": limit,
        "offset": offset,
    }


@router.post("", response_model=Dict[str, Any])
async def create_run(
    request: RunCreateRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """创建新 Run
    
    创建后状态为 queued，等待 worker 处理。
    """
    run = await _create_run(request, db)
    return {"run": run}


@router.get("/{run_id}", response_model=Dict[str, Any])
async def get_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """获取单个 Run
    
    如果 Run 不存在，返回 404。
    """
    run = await _get_run(run_id, db)
    return {"run": run}


@router.get("", response_model=Dict[str, Any])
async def list_runs(
    db: Session = Depends(get_db),
    status: Optional[str] = Query(None, description="Filter by status (queued/running/succeeded/failed/canceled)"),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Maximum number of runs to return"),
    offset: Optional[int] = Query(None, ge=0, description="Number of runs to skip"),
) -> Dict[str, Any]:
    """列出所有 Run，按 updated_at 降序排列
    
    支持按 status 过滤和分页参数 limit 和 offset。
    """
    return await _list_runs(db, status=status, limit=limit, offset=offset)


async def _delete_run(run_id: str, db: Session) -> None:
    """删除 Run（内部函数，便于测试）"""
    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    
    db.delete(run)
    db.commit()


@router.delete("/{run_id}", status_code=204)
async def delete_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> None:
    """删除 Run
    
    如果 Run 不存在，返回 404。
    """
    await _delete_run(run_id, db)
