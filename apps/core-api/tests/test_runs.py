import asyncio
import os
import tempfile
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from app.api import runs
from app.db import Base, ConversationModel, RunModel, RunStatus


def _commit_db(db):
    """辅助函数：提交数据库事务"""
    db.commit()


@pytest.fixture
def temp_db():
    """创建临时数据库用于测试"""
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


def assert_run_schema(run: dict) -> None:
    """验证 Run schema"""
    expected = {
        "id",
        "type",
        "title",
        "status",
        "conversation_id",
        "input",
        "output",
        "error",
        "progress",
        "attempt",
        "worker_id",
        "lease_expires_at",
        "created_at",
        "updated_at",
    }
    assert set(run.keys()) == expected
    assert isinstance(run["id"], str)
    assert isinstance(run["type"], str)
    assert run["status"] in ["queued", "running", "succeeded", "failed", "canceled"]
    assert isinstance(run["input"], dict)
    assert isinstance(run["attempt"], int)
    assert isinstance(run["created_at"], str)  # ISO format string
    assert isinstance(run["updated_at"], str)  # ISO format string
    # 可选字段可以为 None
    assert run["output"] is None or isinstance(run["output"], dict)
    assert run["error"] is None or isinstance(run["error"], str)
    assert run["progress"] is None or isinstance(run["progress"], int)
    assert run["worker_id"] is None or isinstance(run["worker_id"], str)
    assert run["lease_expires_at"] is None or isinstance(run["lease_expires_at"], str)
    assert run["conversation_id"] is None or isinstance(run["conversation_id"], str)
    assert run["title"] is None or isinstance(run["title"], str)


def test_create_run_returns_queued(temp_db) -> None:
    """测试创建任务后状态为 queued"""
    db, _ = temp_db
    request = runs.RunCreateRequest(
        type="sleep",
        title="Test Sleep Task",
        input={"seconds": 5},
    )
    response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    
    assert_run_schema(response)
    assert response["status"] == "queued"
    assert response["type"] == "sleep"
    assert response["title"] == "Test Sleep Task"
    assert response["input"] == {"seconds": 5}
    assert response["output"] is None
    assert response["error"] is None
    assert response["attempt"] == 0
    assert response["worker_id"] is None
    assert response["lease_expires_at"] is None


def test_get_run_not_found_404(temp_db) -> None:
    """测试查询不存在的任务返回 404"""
    db, _ = temp_db
    
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(runs._get_run("nonexistent-id", db))
    assert excinfo.value.status_code == 404
    assert "Run not found" in str(excinfo.value.detail)


def test_list_runs_filters_by_status(temp_db) -> None:
    """测试按状态过滤任务"""
    db, _ = temp_db
    
    # 创建多个不同状态的任务
    request1 = runs.RunCreateRequest(type="sleep", input={"seconds": 1})
    run1 = asyncio.run(runs._create_run(request1, db))
    _commit_db(db)
    
    # 手动更新状态为 succeeded
    run_model1 = db.query(RunModel).filter(RunModel.id == run1["id"]).first()
    run_model1.status = RunStatus.SUCCEEDED
    run_model1.output_json = {"result": "done"}
    _commit_db(db)
    
    import time
    time.sleep(0.01)
    
    request2 = runs.RunCreateRequest(type="sleep", input={"seconds": 2})
    run2 = asyncio.run(runs._create_run(request2, db))
    _commit_db(db)
    
    # 手动更新状态为 failed
    run_model2 = db.query(RunModel).filter(RunModel.id == run2["id"]).first()
    run_model2.status = RunStatus.FAILED
    run_model2.error = "Task failed"
    _commit_db(db)
    
    # 列出所有任务
    all_runs = asyncio.run(runs._list_runs(db))
    assert len(all_runs["items"]) == 2
    
    # 按 queued 状态过滤（应该没有，因为都更新了）
    queued_runs = asyncio.run(runs._list_runs(db, status="queued"))
    assert len(queued_runs["items"]) == 0
    
    # 按 succeeded 状态过滤
    succeeded_runs = asyncio.run(runs._list_runs(db, status="succeeded"))
    assert len(succeeded_runs["items"]) == 1
    assert succeeded_runs["items"][0]["id"] == run1["id"]
    assert succeeded_runs["items"][0]["status"] == "succeeded"
    
    # 按 failed 状态过滤
    failed_runs = asyncio.run(runs._list_runs(db, status="failed"))
    assert len(failed_runs["items"]) == 1
    assert failed_runs["items"][0]["id"] == run2["id"]
    assert failed_runs["items"][0]["status"] == "failed"


def test_list_runs_sorted_by_updated_at_desc(temp_db) -> None:
    """测试任务列表按 updated_at 降序排列"""
    db, _ = temp_db
    
    # 创建第一个任务
    request1 = runs.RunCreateRequest(type="sleep", input={"seconds": 1})
    run1 = asyncio.run(runs._create_run(request1, db))
    _commit_db(db)
    
    import time
    time.sleep(0.01)
    
    # 创建第二个任务
    request2 = runs.RunCreateRequest(type="sleep", input={"seconds": 2})
    run2 = asyncio.run(runs._create_run(request2, db))
    _commit_db(db)
    
    # 列出任务，应该按 updated_at 降序排列（最新的在前）
    response = asyncio.run(runs._list_runs(db))
    assert len(response["items"]) == 2
    assert response["items"][0]["id"] == run2["id"]  # 最新的在前
    assert response["items"][1]["id"] == run1["id"]


def test_list_runs_pagination(temp_db) -> None:
    """测试任务列表分页"""
    db, _ = temp_db
    
    # 创建 5 个任务
    for i in range(5):
        request = runs.RunCreateRequest(type="sleep", input={"seconds": i})
        asyncio.run(runs._create_run(request, db))
        _commit_db(db)
        import time
        time.sleep(0.01)
    
    # 测试 limit
    response = asyncio.run(runs._list_runs(db, limit=3))
    assert len(response["items"]) == 3
    assert response["limit"] == 3
    
    # 测试 offset
    response = asyncio.run(runs._list_runs(db, limit=2, offset=2))
    assert len(response["items"]) == 2
    assert response["limit"] == 2
    assert response["offset"] == 2


def test_list_conversation_runs(temp_db) -> None:
    """测试列出会话任务"""
    db, _ = temp_db
    
    # 创建对话
    from app.api import conversations
    conv_request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(conv_request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 创建属于该对话的任务
    request1 = runs.RunCreateRequest(
        type="sleep",
        conversation_id=conversation_id,
        input={"seconds": 1},
    )
    run1 = asyncio.run(runs._create_run(request1, db))
    _commit_db(db)
    
    import time
    time.sleep(0.01)
    
    request2 = runs.RunCreateRequest(
        type="sleep",
        conversation_id=conversation_id,
        input={"seconds": 2},
    )
    run2 = asyncio.run(runs._create_run(request2, db))
    _commit_db(db)
    
    # 创建不属于该对话的任务
    request3 = runs.RunCreateRequest(type="sleep", input={"seconds": 3})
    run3 = asyncio.run(runs._create_run(request3, db))
    _commit_db(db)
    
    # 列出会话任务
    response = asyncio.run(runs._list_conversation_runs(conversation_id, db))
    assert len(response["items"]) == 2
    assert response["items"][0]["id"] == run2["id"]  # 最新的在前
    assert response["items"][1]["id"] == run1["id"]
    assert all(item["conversation_id"] == conversation_id for item in response["items"])
    
    # 验证不存在的会话返回 404
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(runs._list_conversation_runs("nonexistent-id", db))
    assert excinfo.value.status_code == 404
    assert "Conversation not found" in str(excinfo.value.detail)


def test_run_time_serialization(temp_db) -> None:
    """测试时间字段序列化带 Z 后缀"""
    db, _ = temp_db
    request = runs.RunCreateRequest(type="sleep", input={"seconds": 5})
    response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    
    # 验证时间字段带 Z 后缀
    assert response["created_at"].endswith("Z")
    assert response["updated_at"].endswith("Z")


def test_run_sleep_task_type(temp_db) -> None:
    """测试 sleep 任务类型的输入格式"""
    db, _ = temp_db
    
    # 创建 sleep 任务
    request = runs.RunCreateRequest(
        type="sleep",
        title="Sleep for 5 seconds",
        input={"seconds": 5},
    )
    response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    
    assert response["type"] == "sleep"
    assert response["input"]["seconds"] == 5
    assert isinstance(response["input"]["seconds"], int)


def test_create_run_with_conversation_id(temp_db) -> None:
    """测试创建任务时关联对话"""
    db, _ = temp_db
    
    # 创建对话
    from app.api import conversations
    conv_request = conversations.ConversationCreateRequest(title="Test Chat")
    conv = asyncio.run(conversations._create_conversation(conv_request, db))
    _commit_db(db)
    conversation_id = conv["id"]
    
    # 创建关联对话的任务
    request = runs.RunCreateRequest(
        type="sleep",
        conversation_id=conversation_id,
        input={"seconds": 5},
    )
    response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    
    assert response["conversation_id"] == conversation_id
    
    # 验证不存在的对话 ID 返回 404
    request_invalid = runs.RunCreateRequest(
        type="sleep",
        conversation_id="nonexistent-id",
        input={"seconds": 5},
    )
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(runs._create_run(request_invalid, db))
    assert excinfo.value.status_code == 404
    assert "Conversation not found" in str(excinfo.value.detail)


def test_list_runs_invalid_status(temp_db) -> None:
    """测试无效的状态过滤返回 400"""
    db, _ = temp_db
    
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(runs._list_runs(db, status="invalid_status"))
    assert excinfo.value.status_code == 400
    assert "Invalid status" in str(excinfo.value.detail)
