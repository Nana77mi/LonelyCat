from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from memory.db import AuditEventModel, SessionLocal
from memory.schemas import (
    AuditActor,
    AuditEvent,
    AuditEventDiff,
    AuditEventType,
    AuditTarget,
)


class AuditLogger:
    """审计日志记录器"""

    def __init__(self, db: Optional[Session] = None):
        """初始化审计日志记录器
        
        Args:
            db: 数据库会话。如果为 None，则每次操作时创建新会话
        """
        self._db = db
        self._use_external_db = db is not None

    def _get_db(self) -> Session:
        """获取数据库会话"""
        if self._use_external_db:
            return self._db
        return SessionLocal()

    def _close_db(self, db: Session) -> None:
        """关闭数据库会话（如果不是外部提供的）"""
        if not self._use_external_db:
            db.close()

    async def log_event(
        self,
        event_type: AuditEventType,
        actor: AuditActor,
        target: AuditTarget,
        request_id: Optional[str] = None,
        diff: Optional[AuditEventDiff] = None,
    ) -> AuditEvent:
        """记录审计事件
        
        Args:
            event_type: 事件类型
            actor: 执行者
            target: 目标对象
            request_id: 请求 ID（可选）
            diff: 变更差异（可选）
            
        Returns:
            创建的审计事件
        """
        db = self._get_db()
        try:
            event_id = uuid.uuid4().hex
            event_model = AuditEventModel(
                id=event_id,
                type=event_type,
                actor_kind=actor.kind,
                actor_id=actor.id,
                target_type=target.type,
                target_id=target.id,
                request_id=request_id,
                diff_before=diff.before if diff else None,
                diff_after=diff.after if diff else None,
                created_at=datetime.utcnow(),
            )
            db.add(event_model)
            if not self._use_external_db:
                db.commit()
            
            return AuditEvent(
                id=event_id,
                type=event_type,
                actor=actor,
                target=target,
                request_id=request_id,
                diff=diff,
                created_at=event_model.created_at,
            )
        finally:
            self._close_db(db)

    def get_events(
        self,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[AuditEvent]:
        """查询审计事件
        
        Args:
            target_type: 目标类型过滤（可选）
            target_id: 目标 ID 过滤（可选）
            event_type: 事件类型过滤（可选）
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            审计事件列表
        """
        db = self._get_db()
        try:
            query = db.query(AuditEventModel)
            
            if target_type:
                query = query.filter(AuditEventModel.target_type == target_type)
            if target_id:
                query = query.filter(AuditEventModel.target_id == target_id)
            if event_type:
                query = query.filter(AuditEventModel.type == event_type)
            
            query = query.order_by(AuditEventModel.created_at.desc())
            query = query.limit(limit).offset(offset)
            
            events = query.all()
            
            result = []
            for event_model in events:
                diff = None
                if event_model.diff_before is not None or event_model.diff_after is not None:
                    diff = AuditEventDiff(
                        before=event_model.diff_before,
                        after=event_model.diff_after,
                    )
                
                result.append(AuditEvent(
                    id=event_model.id,
                    type=event_model.type,
                    actor=AuditActor(
                        kind=event_model.actor_kind,
                        id=event_model.actor_id,
                    ),
                    target=AuditTarget(
                        type=event_model.target_type,
                        id=event_model.target_id,
                    ),
                    request_id=event_model.request_id,
                    diff=diff,
                    created_at=event_model.created_at,
                ))
            
            return result
        finally:
            self._close_db(db)
