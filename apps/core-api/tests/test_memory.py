import asyncio
import os
import tempfile

import pytest
from fastapi import HTTPException

from app.api import memory
from memory.db import Base
from memory.facts import MemoryStore
from memory.schemas import ProposalPayload, Scope, SourceKind, SourceRef
from sqlalchemy.orm import sessionmaker


def _commit_db(db):
    """辅助函数：提交数据库事务"""
    db.commit()


@pytest.fixture
def temp_db():
    """创建临时数据库用于测试"""
    import tempfile
    from sqlalchemy import create_engine
    from memory.db import Base
    
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
    os.unlink(db_path)


def assert_fact_schema(record: dict, status: str) -> None:
    """验证 Fact schema"""
    expected = {
        "id",
        "key",
        "value",
        "status",
        "scope",
        "project_id",
        "session_id",
        "source_ref",
        "confidence",
        "version",
        "created_at",
        "updated_at",
    }
    assert set(record.keys()) == expected
    assert record["status"] == status


def assert_proposal_schema(proposal: dict) -> None:
    """验证 Proposal schema"""
    expected = {
        "id",
        "payload",
        "status",
        "reason",
        "confidence",
        "scope_hint",
        "source_ref",
        "created_at",
        "updated_at",
    }
    assert set(proposal.keys()) == expected


def test_list_empty(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    response = asyncio.run(memory.list_facts(store=store))
    assert response == {"items": []}


def test_create_proposal_then_accept(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Alice", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        confidence=0.9,
        scope_hint=Scope.GLOBAL,
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    assert proposal_response["status"] == "pending"
    assert_proposal_schema(proposal_response["proposal"])
    proposal_id = proposal_response["proposal"]["id"]
    
    # 接受 proposal
    accept_request = memory.ProposalAcceptRequest(scope=Scope.GLOBAL)
    accepted = asyncio.run(memory.accept_proposal(proposal_id, accept_request, store=store))
    _commit_db(db)
    assert accepted["proposal"]["status"] == "accepted"
    assert accepted["fact"]["status"] == "active"
    assert_fact_schema(accepted["fact"], "active")
    assert accepted["fact"]["key"] == "preferred_name"
    assert accepted["fact"]["value"] == "Alice"
    
    # 验证 fact 出现在列表中
    response = asyncio.run(memory.list_facts(store=store))
    assert len(response["items"]) == 1
    assert response["items"][0]["id"] == accepted["fact"]["id"]
    assert_fact_schema(response["items"][0], "active")


def test_get_fact_by_id(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Bob", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        confidence=0.75,
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    accept_request = memory.ProposalAcceptRequest(scope=Scope.GLOBAL)
    accepted = asyncio.run(memory.accept_proposal(proposal_response["proposal"]["id"], accept_request, store=store))
    _commit_db(db)
    fact_id = accepted["fact"]["id"]
    
    fetched = asyncio.run(memory.get_fact(fact_id, store=store))
    assert fetched["id"] == fact_id
    assert fetched["value"] == "Bob"
    assert_fact_schema(fetched, "active")


def test_revoke_fact(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Charlie", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        confidence=0.5,
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    accept_request = memory.ProposalAcceptRequest(scope=Scope.GLOBAL)
    accepted = asyncio.run(memory.accept_proposal(proposal_response["proposal"]["id"], accept_request, store=store))
    _commit_db(db)
    fact_id = accepted["fact"]["id"]
    
    revoked = asyncio.run(memory.revoke_fact(fact_id, store=store))
    _commit_db(db)
    assert revoked["status"] == "revoked"
    assert_fact_schema(revoked, "revoked")
    
    fetched = asyncio.run(memory.get_fact(fact_id, store=store))
    assert fetched["status"] == "revoked"
    assert_fact_schema(fetched, "revoked")


def test_revoke_missing_raises(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(memory.revoke_fact("missing", store=store))
    assert excinfo.value.status_code == 404


def test_revoke_already_revoked_raises(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="David", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    accept_request = memory.ProposalAcceptRequest(scope=Scope.GLOBAL)
    accepted = asyncio.run(memory.accept_proposal(proposal_response["proposal"]["id"], accept_request, store=store))
    _commit_db(db)
    fact_id = accepted["fact"]["id"]
    
    asyncio.run(memory.revoke_fact(fact_id, store=store))
    _commit_db(db)
    
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(memory.revoke_fact(fact_id, store=store))
    assert excinfo.value.status_code == 400


def test_archive_fact(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Eve", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    accept_request = memory.ProposalAcceptRequest(scope=Scope.GLOBAL)
    accepted = asyncio.run(memory.accept_proposal(proposal_response["proposal"]["id"], accept_request, store=store))
    _commit_db(db)
    fact_id = accepted["fact"]["id"]
    
    archived = asyncio.run(memory.archive_fact(fact_id, store=store))
    _commit_db(db)
    assert archived["status"] == "archived"
    assert_fact_schema(archived, "archived")


def test_reactivate_fact(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Frank", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    accept_request = memory.ProposalAcceptRequest(scope=Scope.GLOBAL)
    accepted = asyncio.run(memory.accept_proposal(proposal_response["proposal"]["id"], accept_request, store=store))
    _commit_db(db)
    fact_id = accepted["fact"]["id"]
    
    # 先撤销
    asyncio.run(memory.revoke_fact(fact_id, store=store))
    _commit_db(db)
    
    # 再重新激活
    reactivated = asyncio.run(memory.reactivate_fact(fact_id, store=store))
    _commit_db(db)
    assert reactivated["status"] == "active"
    assert_fact_schema(reactivated, "active")


def test_list_proposals(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Grace", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    proposal_id = proposal_response["proposal"]["id"]
    
    proposals = asyncio.run(memory.list_proposals(status="pending", store=store))
    assert len(proposals["items"]) == 1
    assert proposals["items"][0]["id"] == proposal_id
    assert proposals["items"][0]["status"] == "pending"


def test_get_proposal_by_id(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Henry", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    proposal_id = proposal_response["proposal"]["id"]
    
    proposal = asyncio.run(memory.get_proposal(proposal_id, store=store))
    assert proposal["id"] == proposal_id
    assert proposal["status"] == "pending"
    assert_proposal_schema(proposal)


def test_get_proposal_missing_raises(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(memory.get_proposal("missing", store=store))
    assert excinfo.value.status_code == 404


def test_reject_proposal(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Iris", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    proposal_id = proposal_response["proposal"]["id"]
    
    reject_request = memory.ProposalRejectRequest(reason="low confidence")
    proposal = asyncio.run(memory.reject_proposal(proposal_id, reject_request, store=store))
    _commit_db(db)
    assert proposal["status"] == "rejected"
    
    pending = asyncio.run(memory.list_proposals(status="pending", store=store))
    assert pending["items"] == []


def test_expire_proposal(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Jack", tags=[], ttl_seconds=60),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    proposal_id = proposal_response["proposal"]["id"]
    
    expired = asyncio.run(memory.expire_proposal(proposal_id, store=store))
    _commit_db(db)
    assert expired["status"] == "expired"


def test_get_fact_by_key(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Kate", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
    )
    
    proposal_response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    accept_request = memory.ProposalAcceptRequest(scope=Scope.GLOBAL)
    accepted = asyncio.run(memory.accept_proposal(proposal_response["proposal"]["id"], accept_request, store=store))
    _commit_db(db)
    
    found = asyncio.run(memory.get_fact_by_key("preferred_name", "global", store=store))
    assert found["id"] == accepted["fact"]["id"]
    assert found["value"] == "Kate"


def test_list_facts_with_scope_filter(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    
    # 创建 global scope fact
    request1 = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Global", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test1", excerpt=None),
    )
    proposal1 = asyncio.run(memory.create_proposal(request1, store=store))
    _commit_db(db)
    accept1 = memory.ProposalAcceptRequest(scope=Scope.GLOBAL)
    asyncio.run(memory.accept_proposal(proposal1["proposal"]["id"], accept1, store=store))
    _commit_db(db)
    
    # 创建 project scope fact
    request2 = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Project", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test2", excerpt=None),
    )
    proposal2 = asyncio.run(memory.create_proposal(request2, store=store))
    _commit_db(db)
    accept2 = memory.ProposalAcceptRequest(scope=Scope.PROJECT, project_id="project1")
    asyncio.run(memory.accept_proposal(proposal2["proposal"]["id"], accept2, store=store))
    _commit_db(db)
    
    # 验证 scope 过滤
    global_facts = asyncio.run(memory.list_facts(scope="global", store=store))
    assert len(global_facts["items"]) == 1
    assert global_facts["items"][0]["value"] == "Global"
    
    project_facts = asyncio.run(memory.list_facts(scope="project", project_id="project1", store=store))
    assert len(project_facts["items"]) == 1
    assert project_facts["items"][0]["value"] == "Project"


def test_auto_accept_creates_active_fact(temp_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MEMORY_AUTO_ACCEPT", "1")
    monkeypatch.setenv("MEMORY_AUTO_ACCEPT_MIN_CONF", "0.5")
    
    db, _ = temp_db
    store = MemoryStore(db=db)
    request = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Auto", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test", excerpt=None),
        confidence=0.9,
    )
    
    response = asyncio.run(memory.create_proposal(request, store=store))
    _commit_db(db)
    assert response["status"] == "accepted"
    assert response["fact"] is not None
    assert response["fact"]["status"] == "active"
    
    facts = asyncio.run(memory.list_facts(store=store))
    assert len(facts["items"]) == 1
    assert facts["items"][0]["status"] == "active"


def test_overwrite_latest_strategy(temp_db) -> None:
    db, _ = temp_db
    store = MemoryStore(db=db)
    
    # 创建第一个 proposal 并接受
    request1 = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="First", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test1", excerpt=None),
    )
    proposal1 = asyncio.run(memory.create_proposal(request1, store=store))
    _commit_db(db)
    accept1 = memory.ProposalAcceptRequest(scope=Scope.GLOBAL)
    accepted1 = asyncio.run(memory.accept_proposal(proposal1["proposal"]["id"], accept1, store=store))
    _commit_db(db)
    fact1_id = accepted1["fact"]["id"]
    
    # 创建第二个 proposal 并使用 overwrite_latest 策略
    request2 = memory.ProposalCreateRequest(
        payload=ProposalPayload(key="preferred_name", value="Second", tags=[], ttl_seconds=None),
        source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="test2", excerpt=None),
    )
    proposal2 = asyncio.run(memory.create_proposal(request2, store=store))
    _commit_db(db)
    accept2 = memory.ProposalAcceptRequest(scope=Scope.GLOBAL, strategy="overwrite_latest")
    accepted2 = asyncio.run(memory.accept_proposal(proposal2["proposal"]["id"], accept2, store=store))
    _commit_db(db)
    
    # 验证是同一个 fact，但值被更新，version 增加
    assert accepted2["fact"]["id"] == fact1_id
    assert accepted2["fact"]["value"] == "Second"
    assert accepted2["fact"]["version"] == 2
    
    # 验证只有一个 active fact
    facts = asyncio.run(memory.list_facts(scope="global", status="active", store=store))
    assert len(facts["items"]) == 1
