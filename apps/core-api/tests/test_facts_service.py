"""Tests for facts service functions (core-api version)."""

import asyncio
import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.facts import fetch_active_facts, fetch_active_facts_from_store, fact_to_dict

try:
    from memory.db import Base
    from memory.facts import MemoryStore
    from memory.schemas import FactStatus, Scope
    _MEMORY_AVAILABLE = True
except ImportError:
    Base = None
    MemoryStore = None
    FactStatus = None
    Scope = None
    _MEMORY_AVAILABLE = False


class MockMemoryClient:
    """Mock Memory Client for testing."""
    
    def __init__(self, global_facts=None, session_facts=None, project_facts=None):
        self.global_facts = global_facts or []
        self.session_facts = session_facts or {}
        self.project_facts = project_facts or {}
    
    def list_facts(self, scope: str = "global", status: str = "active", 
                   session_id: str = None, project_id: str = None) -> list[dict]:
        if scope == "global":
            return self.global_facts
        elif scope == "session":
            if session_id:
                return self.session_facts.get(session_id, [])
            return []
        elif scope == "project":
            if project_id:
                return self.project_facts.get(project_id, [])
            return []
        return []


def test_fetch_active_facts_global_only():
    """Test fetching global scope facts only."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "language", "value": "zh-CN", "status": "active"},
    ]
    client = MockMemoryClient(global_facts=global_facts)
    
    result = fetch_active_facts(client)
    
    assert len(result) == 2
    assert result[0]["key"] == "likes"
    assert result[1]["key"] == "language"


def test_fetch_active_facts_with_session():
    """Test fetching global + session scope facts."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    session_facts = {
        "conv1": [
            {"key": "current_topic", "value": "python", "status": "active"},
        ]
    }
    client = MockMemoryClient(global_facts=global_facts, session_facts=session_facts)
    
    result = fetch_active_facts(client, conversation_id="conv1")
    
    assert len(result) == 2
    # Check that both global and session facts are present
    keys = {f["key"] for f in result}
    assert "likes" in keys
    assert "current_topic" in keys


def test_fetch_active_facts_session_overrides_global():
    """Test that session scope facts override global scope facts with same key."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    session_facts = {
        "conv1": [
            {"key": "likes", "value": "dogs", "status": "active"},  # Override
        ]
    }
    client = MockMemoryClient(global_facts=global_facts, session_facts=session_facts)
    
    result = fetch_active_facts(client, conversation_id="conv1")
    
    assert len(result) == 1
    assert result[0]["key"] == "likes"
    assert result[0]["value"] == "dogs"  # Session value overrides global


def test_fetch_active_facts_filters_inactive():
    """Test that inactive facts are filtered out."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
        {"key": "old_fact", "value": "old_value", "status": "revoked"},
    ]
    client = MockMemoryClient(global_facts=global_facts)
    
    result = fetch_active_facts(client)
    
    assert len(result) == 1
    assert result[0]["key"] == "likes"


def test_fetch_active_facts_empty():
    """Test fetching facts when none exist."""
    client = MockMemoryClient()
    
    result = fetch_active_facts(client)
    
    assert result == []


def test_fetch_active_facts_no_conversation_id():
    """Test that session facts are not fetched when conversation_id is None."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    session_facts = {
        "conv1": [
            {"key": "current_topic", "value": "python", "status": "active"},
        ]
    }
    client = MockMemoryClient(global_facts=global_facts, session_facts=session_facts)
    
    result = fetch_active_facts(client, conversation_id=None)
    
    assert len(result) == 1
    assert result[0]["key"] == "likes"


def test_fetch_active_facts_session_error_handling():
    """Test that session fetch errors don't break the function."""
    global_facts = [
        {"key": "likes", "value": "cats", "status": "active"},
    ]
    
    class FailingMemoryClient:
        def list_facts(self, scope: str = "global", status: str = "active", 
                      session_id: str = None, project_id: str = None) -> list[dict]:
            if scope == "global":
                return global_facts
            elif scope == "session":
                raise Exception("Session fetch failed")
            return []
    
    client = FailingMemoryClient()
    
    result = fetch_active_facts(client, conversation_id="conv1")
    
    # Should still return global facts even if session fetch fails
    assert len(result) == 1
    assert result[0]["key"] == "likes"


def test_fetch_active_facts_global_error_handling():
    """Test that global fetch errors return empty list."""
    class FailingMemoryClient:
        def list_facts(self, scope: str = "global", status: str = "active", 
                      session_id: str = None, project_id: str = None) -> list[dict]:
            raise Exception("Global fetch failed")
    
    client = FailingMemoryClient()
    
    result = fetch_active_facts(client)
    
    assert result == []


def test_fetch_active_facts_deduplication_by_key():
    """Test that facts are deduplicated by key (session overrides global)."""
    global_facts = [
        {"key": "key1", "value": "global_value", "status": "active"},
        {"key": "key2", "value": "global_value2", "status": "active"},
    ]
    session_facts = {
        "conv1": [
            {"key": "key1", "value": "session_value", "status": "active"},  # Override
            {"key": "key3", "value": "session_value3", "status": "active"},  # New
        ]
    }
    client = MockMemoryClient(global_facts=global_facts, session_facts=session_facts)
    
    result = fetch_active_facts(client, conversation_id="conv1")
    
    assert len(result) == 3
    # Check that key1 has session value
    key1_fact = next(f for f in result if f["key"] == "key1")
    assert key1_fact["value"] == "session_value"
    # Check all keys are present
    keys = {f["key"] for f in result}
    assert keys == {"key1", "key2", "key3"}


@pytest.fixture
def temp_db():
    """临时 DB，用于 store 回归测试（与 test_memory 逻辑一致）"""
    if not _MEMORY_AVAILABLE:
        pytest.skip("memory package not available")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=test_engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    db = TestSessionLocal()
    yield db, db_path
    db.close()
    test_engine.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


def _commit_db(db):
    db.commit()


def test_fetch_active_facts_from_store_vs_http_equivalent_structure(temp_db):
    """
    回归：同一套 seed 数据，store fetch 与「HTTP 等价」结果结构等价、排序稳定。
    HTTP 等价 = GET global active + GET session(conv_id) active，按 key 去重（session 覆盖 global），
    序列化与 fact_to_dict 一致。
    """
    if not _MEMORY_AVAILABLE:
        pytest.skip("memory package not available")
    from app.api import memory as memory_api
    from memory.schemas import ProposalPayload, SourceRef, SourceKind

    async def run():
        db, _ = temp_db
        store = MemoryStore(db=db)
        conv_id = "conv-regression-test"

        # Seed: global fact + session fact（同 key 覆盖）
        req_global = memory_api.ProposalCreateRequest(
            payload=ProposalPayload(key="likes", value="cats", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="r1", excerpt=None),
        )
        prop_global = await memory_api.create_proposal(req_global, store=store)
        _commit_db(db)
        await memory_api.accept_proposal(prop_global["proposal"]["id"], memory_api.ProposalAcceptRequest(scope=Scope.GLOBAL), store=store)
        _commit_db(db)

        req_session = memory_api.ProposalCreateRequest(
            payload=ProposalPayload(key="likes", value="dogs", tags=[], ttl_seconds=None),
            source_ref=SourceRef(kind=SourceKind.MANUAL, ref_id="r2", excerpt=None),
        )
        prop_session = await memory_api.create_proposal(req_session, store=store)
        _commit_db(db)
        await memory_api.accept_proposal(prop_session["proposal"]["id"], memory_api.ProposalAcceptRequest(scope=Scope.SESSION, session_id=conv_id), store=store)
        _commit_db(db)

        # 1) Store fetch（当前实现）
        store_list, source = await fetch_active_facts_from_store(store, conversation_id=conv_id)
        assert source == "store"
        assert len(store_list) >= 1
        # session 覆盖 global，应为 dogs
        likes = next((f for f in store_list if f.get("key") == "likes"), None)
        assert likes is not None
        assert likes.get("value") == "dogs"

        # 2) HTTP 等价：list_facts global + list_facts session，按 key 去重，fact_to_dict
        global_facts = await store.list_facts(scope=Scope.GLOBAL, status=FactStatus.ACTIVE)
        session_facts = await store.list_facts(scope=Scope.SESSION, session_id=conv_id, status=FactStatus.ACTIVE)
        by_key = {}
        for f in global_facts:
            if f.key:
                by_key[f.key] = f
        for f in session_facts:
            if f.key:
                by_key[f.key] = f
        http_equivalent = sorted([fact_to_dict(f) for f in by_key.values()], key=lambda x: (x.get("key") or "", x.get("id") or ""))

        # 3) 结构等价：相同 key 集合、条数；每条字段一致（store 侧可能 limit 截断，只比较前 N 条）
        store_keys = {f.get("key") for f in store_list if f.get("key")}
        http_keys = {f.get("key") for f in http_equivalent if f.get("key")}
        assert store_keys == http_keys, "store vs HTTP equivalent key set mismatch"
        assert len(store_list) == len(http_equivalent), "store vs HTTP equivalent length mismatch"
        for i, (s, h) in enumerate(zip(store_list, http_equivalent)):
            assert set(s.keys()) == set(h.keys()), f"index {i} keys mismatch"
            for k in s:
                assert s.get(k) == h.get(k), f"index {i} key {k} value mismatch"

    asyncio.run(run())
