from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from memory.audit import AuditLogger
from memory.db import FactModel, KeyPolicyModel, ProposalModel, SessionLocal
from memory.schemas import (
    AuditActor,
    AuditEventDiff,
    AuditEventType,
    AuditTarget,
    ConflictStrategy,
    Fact,
    FactStatus,
    Proposal,
    ProposalPayload,
    ProposalStatus,
    Scope,
    SourceKind,
    SourceRef,
)


class MemoryStore:
    """Memory 存储实现，使用 SQLite 数据库"""

    def __init__(self, db: Optional[Session] = None):
        """初始化 MemoryStore
        
        Args:
            db: 数据库会话。如果为 None，则每次操作时创建新会话
        """
        self._db = db
        self._use_external_db = db is not None
        self._audit_logger = AuditLogger(db) if db else AuditLogger()

    def _get_db(self) -> Session:
        """获取数据库会话"""
        if self._use_external_db:
            return self._db
        return SessionLocal()

    def _close_db(self, db: Session) -> None:
        """关闭数据库会话（如果不是外部提供的）"""
        if not self._use_external_db:
            db.commit()
            db.close()

    def _model_to_proposal(self, model: ProposalModel) -> Proposal:
        """将数据库模型转换为 Proposal schema"""
        return Proposal(
            id=model.id,
            payload=ProposalPayload(
                key=model.payload_key,
                value=model.payload_value,
                tags=model.payload_tags or [],
                ttl_seconds=model.ttl_seconds,
            ),
            status=model.status,
            reason=model.reason,
            confidence=model.confidence,
            scope_hint=model.scope_hint,
            source_ref=SourceRef(
                kind=model.source_ref_kind,
                ref_id=model.source_ref_ref_id,
                excerpt=model.source_ref_excerpt,
            ),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _model_to_fact(self, model: FactModel) -> Fact:
        """将数据库模型转换为 Fact schema"""
        return Fact(
            id=model.id,
            key=model.key,
            value=model.value,
            status=model.status,
            scope=model.scope,
            project_id=model.project_id,
            session_id=model.session_id,
            source_ref=SourceRef(
                kind=model.source_ref_kind,
                ref_id=model.source_ref_ref_id,
                excerpt=model.source_ref_excerpt,
            ),
            confidence=model.confidence,
            version=model.version,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _get_key_policy(self, key: str, db: Session) -> ConflictStrategy:
        """获取 key 的冲突解决策略
        
        Args:
            key: 要查询的 key
            db: 数据库会话
            
        Returns:
            冲突解决策略
        """
        # 先查询数据库中的策略配置
        policy = db.query(KeyPolicyModel).filter(KeyPolicyModel.key == key).first()
        if policy:
            return ConflictStrategy(policy.strategy)
        
        # 默认策略：根据 key 的特征判断
        # 单值 key（常见模式）
        single_valued_keys = {
            "preferred_name", "timezone", "language", "email", "phone",
            "project_lonelycat_goal", "project_*_goal",  # 项目目标通常是单值
        }
        
        # 检查是否匹配单值 key 模式
        for pattern in single_valued_keys:
            if pattern.endswith("*") and key.startswith(pattern[:-1]):
                return ConflictStrategy.OVERWRITE_LATEST
            if key == pattern:
                return ConflictStrategy.OVERWRITE_LATEST
        
        # 多值 key（常见模式）
        multi_valued_keys = {
            "favorite_tools", "projects", "constraints", "skills", "tags",
        }
        
        if key in multi_valued_keys or key.endswith("[]") or key.endswith("_list"):
            return ConflictStrategy.KEEP_BOTH
        
        # 默认使用 overwrite_latest
        return ConflictStrategy.OVERWRITE_LATEST

    def _detect_conflict(
        self,
        key: str,
        scope: Scope,
        project_id: Optional[str],
        session_id: Optional[str],
        db: Session,
    ) -> Optional[FactModel]:
        """检测 key 冲突
        
        Args:
            key: 要检查的 key
            scope: scope
            project_id: project_id（scope=project 时必需）
            session_id: session_id（scope=session 时必需）
            db: 数据库会话
            
        Returns:
            如果存在冲突的 active fact，返回该 fact 模型，否则返回 None
        """
        query = db.query(FactModel).filter(
            FactModel.key == key,
            FactModel.scope == scope,
            FactModel.status == FactStatus.ACTIVE,
        )
        
        if scope == Scope.PROJECT:
            if project_id is None:
                raise ValueError("project_id is required when scope=project")
            query = query.filter(FactModel.project_id == project_id)
        elif scope == Scope.SESSION:
            if session_id is None:
                raise ValueError("session_id is required when scope=session")
            query = query.filter(FactModel.session_id == session_id)
        elif scope == Scope.GLOBAL:
            query = query.filter(FactModel.project_id.is_(None), FactModel.session_id.is_(None))
        
        return query.first()

    async def create_proposal(
        self,
        payload: ProposalPayload,
        source_ref: SourceRef,
        reason: Optional[str] = None,
        confidence: Optional[float] = None,
        scope_hint: Optional[Scope] = None,
    ) -> Proposal:
        """创建 Proposal
        
        Args:
            payload: Proposal payload
            source_ref: Source 引用
            reason: 原因（可选）
            confidence: 置信度（可选，0-1）
            scope_hint: Scope 提示（可选）
            
        Returns:
            创建的 Proposal
        """
        if confidence is not None and not (0 <= confidence <= 1):
            raise ValueError("confidence must be between 0 and 1")
        
        db = self._get_db()
        try:
            proposal_id = uuid.uuid4().hex
            now = datetime.utcnow()
            
            proposal_model = ProposalModel(
                id=proposal_id,
                payload_key=payload.key,
                payload_value=payload.value,
                payload_tags=payload.tags,
                ttl_seconds=payload.ttl_seconds,
                status=ProposalStatus.PENDING,
                reason=reason,
                confidence=confidence,
                scope_hint=scope_hint,
                source_ref_kind=source_ref.kind,
                source_ref_ref_id=source_ref.ref_id,
                source_ref_excerpt=source_ref.excerpt,
                created_at=now,
                updated_at=now,
            )
            
            db.add(proposal_model)
            if not self._use_external_db:
                db.commit()
            else:
                # 使用外部数据库时，刷新会话以确保 proposal 对后续操作可见
                db.flush()
            
            # 记录审计事件
            await self._audit_logger.log_event(
                event_type=AuditEventType.PROPOSAL_CREATED,
                actor=AuditActor(kind="system", id="system"),
                target=AuditTarget(type="proposal", id=proposal_id),
            )
            
            return self._model_to_proposal(proposal_model)
        finally:
            self._close_db(db)

    async def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        """获取 Proposal
        
        Args:
            proposal_id: Proposal ID
            
        Returns:
            Proposal 或 None
        """
        db = self._get_db()
        try:
            model = db.query(ProposalModel).filter(ProposalModel.id == proposal_id).first()
            if model is None:
                return None
            return self._model_to_proposal(model)
        finally:
            self._close_db(db)

    async def list_proposals(
        self,
        status: Optional[ProposalStatus] = None,
        scope_hint: Optional[Scope] = None,
    ) -> List[Proposal]:
        """列出 Proposal
        
        Args:
            status: 状态过滤（可选）
            scope_hint: Scope 过滤（可选）
            
        Returns:
            Proposal 列表
        """
        db = self._get_db()
        try:
            query = db.query(ProposalModel)
            
            if status:
                query = query.filter(ProposalModel.status == status)
            if scope_hint:
                query = query.filter(ProposalModel.scope_hint == scope_hint)
            
            query = query.order_by(ProposalModel.created_at.desc())
            models = query.all()
            
            return [self._model_to_proposal(model) for model in models]
        finally:
            self._close_db(db)

    async def reject_proposal(
        self,
        proposal_id: str,
        resolved_reason: Optional[str] = None,
        actor: Optional[AuditActor] = None,
    ) -> Optional[Proposal]:
        """拒绝 Proposal
        
        Args:
            proposal_id: Proposal ID
            resolved_reason: 拒绝原因（可选）
            actor: 执行者（可选，默认为 system）
            
        Returns:
            更新后的 Proposal 或 None
        """
        db = self._get_db()
        try:
            model = db.query(ProposalModel).filter(ProposalModel.id == proposal_id).first()
            if model is None:
                return None
            if model.status != ProposalStatus.PENDING:
                return None
            
            model.status = ProposalStatus.REJECTED
            model.updated_at = datetime.utcnow()
            
            if not self._use_external_db:
                db.commit()
            else:
                db.flush()
            
            # 记录审计事件
            await self._audit_logger.log_event(
                event_type=AuditEventType.PROPOSAL_REJECTED,
                actor=actor or AuditActor(kind="system", id="system"),
                target=AuditTarget(type="proposal", id=proposal_id),
            )
            
            return self._model_to_proposal(model)
        finally:
            self._close_db(db)

    async def expire_proposal(
        self,
        proposal_id: str,
        actor: Optional[AuditActor] = None,
    ) -> Optional[Proposal]:
        """过期 Proposal
        
        Args:
            proposal_id: Proposal ID
            actor: 执行者（可选，默认为 system）
            
        Returns:
            更新后的 Proposal 或 None
        """
        db = self._get_db()
        try:
            model = db.query(ProposalModel).filter(ProposalModel.id == proposal_id).first()
            if model is None:
                return None
            if model.status != ProposalStatus.PENDING:
                return None
            
            model.status = ProposalStatus.EXPIRED
            model.updated_at = datetime.utcnow()
            
            if not self._use_external_db:
                db.commit()
            else:
                db.flush()
            
            # 记录审计事件
            await self._audit_logger.log_event(
                event_type=AuditEventType.PROPOSAL_EXPIRED,
                actor=actor or AuditActor(kind="system", id="system"),
                target=AuditTarget(type="proposal", id=proposal_id),
            )
            
            return self._model_to_proposal(model)
        finally:
            self._close_db(db)

    async def accept_proposal(
        self,
        proposal_id: str,
        strategy: Optional[ConflictStrategy] = None,
        scope: Optional[Scope] = None,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        actor: Optional[AuditActor] = None,
    ) -> Optional[Tuple[Proposal, Fact]]:
        """接受 Proposal，创建或更新 Fact
        
        Args:
            proposal_id: Proposal ID
            strategy: 冲突解决策略（可选，如果不提供则根据 key policy 决定）
            scope: 目标 scope（可选，如果不提供则使用 proposal 的 scope_hint 或 global）
            project_id: project_id（scope=project 时必需）
            session_id: session_id（scope=session 时必需）
            actor: 执行者（可选，默认为 system）
            
        Returns:
            (Proposal, Fact) 元组或 None
        """
        db = self._get_db()
        try:
            proposal_model = db.query(ProposalModel).filter(ProposalModel.id == proposal_id).first()
            if proposal_model is None:
                return None
            if proposal_model.status != ProposalStatus.PENDING:
                return None
            
            # 确定 scope
            final_scope = scope or proposal_model.scope_hint or Scope.GLOBAL
            
            # 验证 scope 约束
            if final_scope == Scope.PROJECT and project_id is None:
                raise ValueError("project_id is required when scope=project")
            if final_scope == Scope.SESSION and session_id is None:
                raise ValueError("session_id is required when session=session")
            
            # 确定冲突解决策略
            if strategy is None:
                strategy = self._get_key_policy(proposal_model.payload_key, db)
            
            # 检测冲突
            existing_fact = self._detect_conflict(
                proposal_model.payload_key,
                final_scope,
                project_id,
                session_id,
                db,
            )
            
            # 解决冲突
            if strategy == ConflictStrategy.OVERWRITE_LATEST:
                if existing_fact:
                    # 更新现有 fact
                    fact = await self._update_fact_internal(
                        existing_fact.id,
                        proposal_model.payload_value,
                        proposal_model.source_ref_kind,
                        proposal_model.source_ref_ref_id,
                        proposal_model.source_ref_excerpt,
                        proposal_model.confidence,
                        db,
                    )
                else:
                    # 创建新 fact
                    fact = await self._create_fact_internal(
                        proposal_model.payload_key,
                        proposal_model.payload_value,
                        final_scope,
                        project_id,
                        session_id,
                        proposal_model.source_ref_kind,
                        proposal_model.source_ref_ref_id,
                        proposal_model.source_ref_excerpt,
                        proposal_model.confidence,
                        db,
                    )
            else:  # KEEP_BOTH
                # 总是创建新 fact
                fact = await self._create_fact_internal(
                    proposal_model.payload_key,
                    proposal_model.payload_value,
                    final_scope,
                    project_id,
                    session_id,
                    proposal_model.source_ref_kind,
                    proposal_model.source_ref_ref_id,
                    proposal_model.source_ref_excerpt,
                    proposal_model.confidence,
                    db,
                )
            
            # 更新 proposal 状态
            proposal_model.status = ProposalStatus.ACCEPTED
            proposal_model.updated_at = datetime.utcnow()
            
            if not self._use_external_db:
                db.commit()
            
            # 记录审计事件
            await self._audit_logger.log_event(
                event_type=AuditEventType.PROPOSAL_ACCEPTED,
                actor=actor or AuditActor(kind="system", id="system"),
                target=AuditTarget(type="proposal", id=proposal_id),
            )
            
            proposal = self._model_to_proposal(proposal_model)
            return proposal, fact
        finally:
            self._close_db(db)

    async def _create_fact_internal(
        self,
        key: str,
        value: Any,
        scope: Scope,
        project_id: Optional[str],
        session_id: Optional[str],
        source_kind: SourceKind,
        source_ref_id: str,
        source_excerpt: Optional[str],
        confidence: Optional[float],
        db: Session,
    ) -> Fact:
        """内部方法：创建 Fact"""
        fact_id = uuid.uuid4().hex
        now = datetime.utcnow()
        
        fact_model = FactModel(
            id=fact_id,
            key=key,
            value=value,
            status=FactStatus.ACTIVE,
            scope=scope,
            project_id=project_id,
            session_id=session_id,
            source_ref_kind=source_kind,
            source_ref_ref_id=source_ref_id,
            source_ref_excerpt=source_excerpt,
            confidence=confidence,
            version=1,
            created_at=now,
            updated_at=now,
        )
        
        db.add(fact_model)
        
        # 记录审计事件
        await self._audit_logger.log_event(
            event_type=AuditEventType.FACT_CREATED,
            actor=AuditActor(kind="system", id="system"),
            target=AuditTarget(type="fact", id=fact_id),
        )
        
        return self._model_to_fact(fact_model)

    async def _update_fact_internal(
        self,
        fact_id: str,
        new_value: Any,
        source_kind: SourceKind,
        source_ref_id: str,
        source_excerpt: Optional[str],
        confidence: Optional[float],
        db: Session,
    ) -> Fact:
        """内部方法：更新 Fact"""
        fact_model = db.query(FactModel).filter(FactModel.id == fact_id).first()
        if fact_model is None:
            raise ValueError(f"Fact {fact_id} not found")
        
        # 记录变更差异
        old_value = fact_model.value
        old_version = fact_model.version
        
        fact_model.value = new_value
        fact_model.version += 1
        fact_model.source_ref_kind = source_kind
        fact_model.source_ref_ref_id = source_ref_id
        fact_model.source_ref_excerpt = source_excerpt
        if confidence is not None:
            fact_model.confidence = confidence
        fact_model.updated_at = datetime.utcnow()
        
        # 记录审计事件（包含 diff）
        diff = AuditEventDiff(
            before={"value": old_value, "version": old_version},
            after={"value": new_value, "version": fact_model.version},
        )
        await self._audit_logger.log_event(
            event_type=AuditEventType.FACT_UPDATED,
            actor=AuditActor(kind="system", id="system"),
            target=AuditTarget(type="fact", id=fact_id),
            diff=diff,
        )
        
        return self._model_to_fact(fact_model)

    async def get_fact(self, fact_id: str) -> Optional[Fact]:
        """获取 Fact
        
        Args:
            fact_id: Fact ID
            
        Returns:
            Fact 或 None
        """
        db = self._get_db()
        try:
            model = db.query(FactModel).filter(FactModel.id == fact_id).first()
            if model is None:
                return None
            return self._model_to_fact(model)
        finally:
            self._close_db(db)

    async def get_fact_by_key(
        self,
        key: str,
        scope: Scope,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Fact]:
        """根据 key 获取 Fact
        
        Args:
            key: Fact key
            scope: Scope
            project_id: project_id（scope=project 时必需）
            session_id: session_id（scope=session 时必需）
            
        Returns:
            Fact 或 None
        """
        db = self._get_db()
        try:
            model = self._detect_conflict(key, scope, project_id, session_id, db)
            if model is None:
                return None
            return self._model_to_fact(model)
        finally:
            self._close_db(db)

    async def list_facts(
        self,
        scope: Optional[Scope] = None,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: Optional[FactStatus] = None,
    ) -> List[Fact]:
        """列出 Fact
        
        Args:
            scope: Scope 过滤（可选）
            project_id: project_id 过滤（可选）
            session_id: session_id 过滤（可选）
            status: 状态过滤（可选）
            
        Returns:
            Fact 列表
        """
        db = self._get_db()
        try:
            query = db.query(FactModel)
            
            if scope:
                query = query.filter(FactModel.scope == scope)
            if project_id is not None:
                query = query.filter(FactModel.project_id == project_id)
            if session_id is not None:
                query = query.filter(FactModel.session_id == session_id)
            if status:
                query = query.filter(FactModel.status == status)
            
            query = query.order_by(FactModel.created_at.desc())
            models = query.all()
            
            return [self._model_to_fact(model) for model in models]
        finally:
            self._close_db(db)

    async def revoke_fact(
        self,
        fact_id: str,
        actor: Optional[AuditActor] = None,
    ) -> Optional[Fact]:
        """撤销 Fact
        
        Args:
            fact_id: Fact ID
            actor: 执行者（可选，默认为 system）
            
        Returns:
            更新后的 Fact 或 None
        """
        db = self._get_db()
        try:
            model = db.query(FactModel).filter(FactModel.id == fact_id).first()
            if model is None:
                return None
            if model.status != FactStatus.ACTIVE:
                return None
            
            model.status = FactStatus.REVOKED
            model.updated_at = datetime.utcnow()
            
            if not self._use_external_db:
                db.commit()
            
            # 记录审计事件
            await self._audit_logger.log_event(
                event_type=AuditEventType.FACT_REVOKED,
                actor=actor or AuditActor(kind="system", id="system"),
                target=AuditTarget(type="fact", id=fact_id),
            )
            
            return self._model_to_fact(model)
        finally:
            self._close_db(db)

    async def archive_fact(
        self,
        fact_id: str,
        actor: Optional[AuditActor] = None,
    ) -> Optional[Fact]:
        """归档 Fact
        
        Args:
            fact_id: Fact ID
            actor: 执行者（可选，默认为 system）
            
        Returns:
            更新后的 Fact 或 None
        """
        db = self._get_db()
        try:
            model = db.query(FactModel).filter(FactModel.id == fact_id).first()
            if model is None:
                return None
            if model.status != FactStatus.ACTIVE:
                return None
            
            model.status = FactStatus.ARCHIVED
            model.updated_at = datetime.utcnow()
            
            if not self._use_external_db:
                db.commit()
            
            # 记录审计事件
            await self._audit_logger.log_event(
                event_type=AuditEventType.FACT_ARCHIVED,
                actor=actor or AuditActor(kind="system", id="system"),
                target=AuditTarget(type="fact", id=fact_id),
            )
            
            return self._model_to_fact(model)
        finally:
            self._close_db(db)

    async def reactivate_fact(
        self,
        fact_id: str,
        actor: Optional[AuditActor] = None,
    ) -> Optional[Fact]:
        """重新激活 Fact
        
        Args:
            fact_id: Fact ID
            actor: 执行者（可选，默认为 system）
            
        Returns:
            更新后的 Fact 或 None
        """
        db = self._get_db()
        try:
            model = db.query(FactModel).filter(FactModel.id == fact_id).first()
            if model is None:
                return None
            if model.status not in (FactStatus.REVOKED, FactStatus.ARCHIVED):
                return None
            
            model.status = FactStatus.ACTIVE
            model.updated_at = datetime.utcnow()
            
            if not self._use_external_db:
                db.commit()
            
            # 记录审计事件
            await self._audit_logger.log_event(
                event_type=AuditEventType.FACT_REACTIVATED,
                actor=actor or AuditActor(kind="system", id="system"),
                target=AuditTarget(type="fact", id=fact_id),
            )
            
            return self._model_to_fact(model)
        finally:
            self._close_db(db)

    async def check_expired_proposals(self) -> List[str]:
        """检查并过期过期的 Proposal（基于 TTL）
        
        Returns:
            已过期的 Proposal ID 列表
        """
        db = self._get_db()
        try:
            now = datetime.utcnow()
            expired_ids = []
            
            # 查询所有 pending 状态的 proposal
            proposals = db.query(ProposalModel).filter(
                ProposalModel.status == ProposalStatus.PENDING,
                ProposalModel.ttl_seconds.isnot(None),
            ).all()
            
            for proposal in proposals:
                if proposal.ttl_seconds:
                    expires_at = proposal.created_at + timedelta(seconds=proposal.ttl_seconds)
                    if now >= expires_at:
                        await self.expire_proposal(proposal.id)
                        expired_ids.append(proposal.id)
            
            if not self._use_external_db:
                db.commit()
            
            return expired_ids
        finally:
            self._close_db(db)


# 向后兼容：保留 FactsStore 作为别名（已废弃）
FactsStore = MemoryStore
