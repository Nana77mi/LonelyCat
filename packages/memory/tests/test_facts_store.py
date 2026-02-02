import asyncio
import os
import tempfile

import pytest

from memory.db import Base
from sqlalchemy.orm import sessionmaker
from memory.facts import MemoryStore
from memory.schemas import (
    ConflictStrategy,
    FactStatus,
    ProposalPayload,
    ProposalStatus,
    Scope,
    SourceKind,
    SourceRef,
)


def _commit_db(db):
    """辅助函数：提交数据库事务"""
    db.commit()


@pytest.fixture
def temp_db():
    """创建临时数据库用于测试"""
    import tempfile
    from sqlalchemy import create_engine
    from memory.db import Base, SessionLocal
    
    # 创建临时数据库文件
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    # 创建临时数据库 engine
    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    
    # 创建测试会话
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    
    yield db, db_path
    
    # 清理
    db.close()
    try:
        os.unlink(db_path)
    except (PermissionError, OSError):
        # Windows 上可能文件被占用，忽略错误
        pass


def test_create_proposal(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        proposal = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
            confidence=0.9,
            scope_hint=Scope.GLOBAL,
        )
        _commit_db(db)
        assert proposal.id is not None
        assert proposal.status == ProposalStatus.PENDING
        assert proposal.payload.key == "preferred_name"
        assert proposal.payload.value == "Alice"
        assert proposal.confidence == 0.9

    asyncio.run(run())


def test_accept_proposal_creates_fact(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        proposal = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
            confidence=0.9,
            scope_hint=Scope.GLOBAL,
        )
        _commit_db(db)  # 提交 proposal，确保 accept_proposal 能看到它
        
        accepted = await store.accept_proposal(proposal.id, scope=Scope.GLOBAL)
        _commit_db(db)
        assert accepted is not None
        proposal_result, fact = accepted
        
        assert proposal_result.status == ProposalStatus.ACCEPTED
        assert fact.key == "preferred_name"
        assert fact.value == "Alice"
        assert fact.status == FactStatus.ACTIVE
        assert fact.scope == Scope.GLOBAL
        assert fact.version == 1

    asyncio.run(run())


def test_reject_proposal(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        proposal = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        )
        _commit_db(db)  # 提交 proposal，确保 reject_proposal 能看到它
        
        rejected = await store.reject_proposal(proposal.id, resolved_reason="not needed")
        _commit_db(db)
        assert rejected is not None
        assert rejected.status == ProposalStatus.REJECTED
        
        # 验证没有创建 fact
        facts = await store.list_facts(scope=Scope.GLOBAL)
        assert len(facts) == 0

    asyncio.run(run())


def test_expire_proposal(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        proposal = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=60),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        )
        _commit_db(db)  # 提交 proposal，确保 expire_proposal 能看到它
        
        expired = await store.expire_proposal(proposal.id)
        _commit_db(db)
        assert expired is not None
        assert expired.status == ProposalStatus.EXPIRED

    asyncio.run(run())


def test_overwrite_latest_strategy(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        
        # 创建第一个 proposal 并接受
        proposal1 = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test1", excerpt=None),
        )
        _commit_db(db)
        _, fact1 = await store.accept_proposal(proposal1.id, scope=Scope.GLOBAL)
        _commit_db(db)
        
        # 创建第二个 proposal 并接受（使用 overwrite_latest）
        proposal2 = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Bob", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test2", excerpt=None),
        )
        _commit_db(db)
        _, fact2 = await store.accept_proposal(
            proposal2.id,
            strategy=ConflictStrategy.OVERWRITE_LATEST,
            scope=Scope.GLOBAL,
        )
        _commit_db(db)
        
        # 验证 fact1 被更新（version 增加）
        assert fact2.id == fact1.id  # 同一个 fact
        assert fact2.version == 2  # version 增加
        assert fact2.value == "Bob"  # 值被更新
        
        # 验证只有一个 active fact
        facts = await store.list_facts(scope=Scope.GLOBAL, status=FactStatus.ACTIVE)
        assert len(facts) == 1
        assert facts[0].id == fact1.id

    asyncio.run(run())


def test_keep_both_strategy(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        
        # 创建第一个 proposal 并接受
        proposal1 = await store.create_proposal(
            payload=ProposalPayload(key="favorite_tools", value="vim", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test1", excerpt=None),
        )
        _commit_db(db)
        _, fact1 = await store.accept_proposal(proposal1.id, scope=Scope.GLOBAL)
        _commit_db(db)
        
        # 创建第二个 proposal 并接受（使用 keep_both）
        proposal2 = await store.create_proposal(
            payload=ProposalPayload(key="favorite_tools", value="emacs", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test2", excerpt=None),
        )
        _commit_db(db)
        _, fact2 = await store.accept_proposal(
            proposal2.id,
            strategy=ConflictStrategy.KEEP_BOTH,
            scope=Scope.GLOBAL,
        )
        _commit_db(db)  # 提交第二个 fact
        
        # 验证创建了两个不同的 fact
        assert fact2 is not None, "fact2 should not be None"
        assert fact2.id != fact1.id
        assert fact2.version == 1  # 新 fact，version 从 1 开始
        
        # 验证有两个 active facts
        facts = await store.list_facts(scope=Scope.GLOBAL, status=FactStatus.ACTIVE)
        assert len(facts) == 2

    asyncio.run(run())


def test_revoke_fact(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        proposal = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        )
        _commit_db(db)
        _, fact = await store.accept_proposal(proposal.id, scope=Scope.GLOBAL)
        _commit_db(db)
        
        revoked = await store.revoke_fact(fact.id)
        _commit_db(db)
        assert revoked is not None
        assert revoked.status == FactStatus.REVOKED
        
        # 验证不再出现在 active facts 列表中
        active_facts = await store.list_facts(scope=Scope.GLOBAL, status=FactStatus.ACTIVE)
        assert len(active_facts) == 0

    asyncio.run(run())


def test_archive_fact(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        proposal = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        )
        _commit_db(db)
        _, fact = await store.accept_proposal(proposal.id, scope=Scope.GLOBAL)
        _commit_db(db)
        
        archived = await store.archive_fact(fact.id)
        assert archived is not None
        assert archived.status == FactStatus.ARCHIVED
        
        # 验证不再出现在 active facts 列表中
        active_facts = await store.list_facts(scope=Scope.GLOBAL, status=FactStatus.ACTIVE)
        assert len(active_facts) == 0

    asyncio.run(run())


def test_reactivate_fact(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        proposal = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        )
        _commit_db(db)
        _, fact = await store.accept_proposal(proposal.id, scope=Scope.GLOBAL)
        _commit_db(db)
        
        # 先撤销
        await store.revoke_fact(fact.id)
        _commit_db(db)
        
        # 再重新激活
        reactivated = await store.reactivate_fact(fact.id)
        _commit_db(db)
        assert reactivated is not None
        assert reactivated.status == FactStatus.ACTIVE
        
        # 验证出现在 active facts 列表中
        active_facts = await store.list_facts(scope=Scope.GLOBAL, status=FactStatus.ACTIVE)
        assert len(active_facts) == 1
        assert active_facts[0].id == fact.id

    asyncio.run(run())


def test_scope_isolation(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        
        # 创建 global scope fact
        proposal1 = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test1", excerpt=None),
        )
        _commit_db(db)
        _, fact1 = await store.accept_proposal(proposal1.id, scope=Scope.GLOBAL)
        _commit_db(db)
        
        # 创建 project scope fact
        proposal2 = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Bob", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test2", excerpt=None),
        )
        _commit_db(db)
        _, fact2 = await store.accept_proposal(
            proposal2.id,
            scope=Scope.PROJECT,
            project_id="project1",
        )
        _commit_db(db)
        
        # 验证 scope 隔离
        global_facts = await store.list_facts(scope=Scope.GLOBAL)
        assert len(global_facts) == 1
        assert global_facts[0].id == fact1.id
        
        project_facts = await store.list_facts(scope=Scope.PROJECT, project_id="project1")
        assert len(project_facts) == 1
        assert project_facts[0].id == fact2.id

    asyncio.run(run())


def test_confidence_validation(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        
        # 测试无效的 confidence
        with pytest.raises(ValueError):
            await store.create_proposal(
                payload=ProposalPayload(key="test", value="value", tags=[], ttl_seconds=None),
                source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
                confidence=-0.1,
            )
        
        with pytest.raises(ValueError):
            await store.create_proposal(
                payload=ProposalPayload(key="test", value="value", tags=[], ttl_seconds=None),
                source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
                confidence=1.1,
            )

    asyncio.run(run())


def test_get_fact_by_key(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        proposal = await store.create_proposal(
            payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        )
        _commit_db(db)
        _, fact = await store.accept_proposal(proposal.id, scope=Scope.GLOBAL)
        _commit_db(db)
        
        # 通过 key 查询
        found = await store.get_fact_by_key("preferred_name", Scope.GLOBAL)
        assert found is not None
        assert found.id == fact.id
        assert found.value == "Alice"

    asyncio.run(run())


def test_list_proposals_with_status_filter(temp_db):
    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        
        # 创建多个 proposals
        proposal1 = await store.create_proposal(
            payload=ProposalPayload(key="key1", value="value1", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test1", excerpt=None),
        )
        proposal2 = await store.create_proposal(
            payload=ProposalPayload(key="key2", value="value2", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test2", excerpt=None),
        )
        
        # 接受第一个
        _commit_db(db)
        result1 = await store.accept_proposal(proposal1.id, scope=Scope.GLOBAL)
        assert result1 is not None, "accept_proposal should succeed"
        _commit_db(db)
        
        # 拒绝第二个
        _commit_db(db)
        result2 = await store.reject_proposal(proposal2.id)
        assert result2 is not None, "reject_proposal should succeed"
        _commit_db(db)
        
        # 查询 pending proposals（应该为空）
        pending = await store.list_proposals(status=ProposalStatus.PENDING)
        assert len(pending) == 0
        
        # 查询 accepted proposals
        accepted = await store.list_proposals(status=ProposalStatus.ACCEPTED)
        assert len(accepted) == 1
        assert accepted[0].id == proposal1.id
        
        # 查询 rejected proposals
        rejected = await store.list_proposals(status=ProposalStatus.REJECTED)
        assert len(rejected) == 1
        assert rejected[0].id == proposal2.id

    asyncio.run(run())
