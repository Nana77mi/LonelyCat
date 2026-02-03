import asyncio
import os
import sys
import tempfile
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine

from app.api import runs
from app.db import Base, ConversationModel, RunModel, RunStatus

# 添加 agent-worker 路径以便导入 worker 模块
agent_worker_path = Path(__file__).parent.parent.parent / "agent-worker"
if str(agent_worker_path) not in sys.path:
    sys.path.insert(0, str(agent_worker_path))

from worker.queue import (
    claim_run,
    complete_failed,
    complete_success,
    fetch_and_claim_run,
    fetch_runnable_candidate,
    heartbeat,
)


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


# ========== PR-Run-2 测试：抢占、心跳、互斥 ==========


def test_claim_queued_run_single_worker(temp_db) -> None:
    """测试单个 worker 抢占 queued run"""
    db, _ = temp_db
    
    # 创建 queued run
    request = runs.RunCreateRequest(type="sleep", input={"seconds": 5})
    run_response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    run_id = run_response["id"]
    
    # Worker A 抢占
    worker_a = "worker-a"
    lease_seconds = 60
    claimed_run = claim_run(db, run_id, worker_a, lease_seconds)
    _commit_db(db)
    
    # 验证抢占成功
    assert claimed_run is not None
    assert claimed_run.id == run_id
    assert claimed_run.status == RunStatus.RUNNING
    assert claimed_run.worker_id == worker_a
    assert claimed_run.lease_expires_at is not None
    assert claimed_run.attempt == 1
    
    # 验证数据库中的状态
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    assert db_run.status == RunStatus.RUNNING
    assert db_run.worker_id == worker_a
    assert db_run.attempt == 1


def test_claim_is_exclusive_two_workers(temp_db) -> None:
    """测试两个 worker 抢占互斥"""
    db, _ = temp_db
    
    # 创建 queued run
    request = runs.RunCreateRequest(type="sleep", input={"seconds": 5})
    run_response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    run_id = run_response["id"]
    
    # Worker A 抢占成功
    worker_a = "worker-a"
    worker_b = "worker-b"
    lease_seconds = 60
    
    claimed_run_a = claim_run(db, run_id, worker_a, lease_seconds)
    _commit_db(db)
    assert claimed_run_a is not None
    assert claimed_run_a.worker_id == worker_a
    
    # Worker B 尝试抢占同一个 run（应该失败）
    claimed_run_b = claim_run(db, run_id, worker_b, lease_seconds)
    _commit_db(db)
    assert claimed_run_b is None  # 抢占失败
    
    # 验证 run 仍然属于 Worker A
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    assert db_run.worker_id == worker_a
    assert db_run.attempt == 1  # 只有 Worker A 抢占了一次


def test_reclaim_expired_run(temp_db) -> None:
    """测试抢占过期的 running run"""
    db, _ = temp_db
    
    # 创建 queued run
    request = runs.RunCreateRequest(type="sleep", input={"seconds": 5})
    run_response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    run_id = run_response["id"]
    
    # Worker A 抢占
    worker_a = "worker-a"
    lease_seconds = 60
    claimed_run_a = claim_run(db, run_id, worker_a, lease_seconds)
    _commit_db(db)
    assert claimed_run_a is not None
    
    # 手动设置 lease_expires_at 为过去（模拟过期）
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    db_run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    db_run.status = RunStatus.RUNNING  # 确保状态是 running
    _commit_db(db)
    
    # Worker B 应该能够接管过期的 run
    worker_b = "worker-b"
    claimed_run_b = claim_run(db, run_id, worker_b, lease_seconds)
    _commit_db(db)
    
    # 验证 Worker B 接管成功
    assert claimed_run_b is not None
    assert claimed_run_b.worker_id == worker_b
    assert claimed_run_b.attempt == 2  # Worker A 一次，Worker B 一次
    
    # 验证数据库中的状态
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    assert db_run.worker_id == worker_b
    assert db_run.attempt == 2


def test_heartbeat_requires_owner(temp_db) -> None:
    """测试心跳必须由 owner 执行"""
    db, _ = temp_db
    
    # 创建 queued run
    request = runs.RunCreateRequest(type="sleep", input={"seconds": 5})
    run_response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    run_id = run_response["id"]
    
    # Worker A 抢占
    worker_a = "worker-a"
    worker_b = "worker-b"
    lease_seconds = 60
    
    claimed_run = claim_run(db, run_id, worker_a, lease_seconds)
    _commit_db(db)
    assert claimed_run is not None
    
    # 记录原始的 lease_expires_at
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    original_lease = db_run.lease_expires_at
    
    # Worker B 尝试心跳（应该失败）
    success_b = heartbeat(db, run_id, worker_b, lease_seconds)
    _commit_db(db)
    assert success_b is False
    
    # 验证 lease_expires_at 没有改变
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    assert db_run.lease_expires_at == original_lease


def test_heartbeat_updates_lease(temp_db) -> None:
    """测试 owner 心跳成功更新租约"""
    db, _ = temp_db
    
    # 创建 queued run
    request = runs.RunCreateRequest(type="sleep", input={"seconds": 5})
    run_response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    run_id = run_response["id"]
    
    # Worker A 抢占
    worker_a = "worker-a"
    lease_seconds = 60
    
    claimed_run = claim_run(db, run_id, worker_a, lease_seconds)
    _commit_db(db)
    assert claimed_run is not None
    
    # 记录原始的 lease_expires_at
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    original_lease = db_run.lease_expires_at
    
    # 等待一小段时间
    import time
    time.sleep(0.1)
    
    # Worker A 心跳（应该成功）
    success = heartbeat(db, run_id, worker_a, lease_seconds)
    _commit_db(db)
    assert success is True
    
    # 验证 lease_expires_at 已更新
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    assert db_run.lease_expires_at is not None
    assert db_run.lease_expires_at > original_lease


def test_complete_success_clears_lease(temp_db) -> None:
    """测试成功完成任务后清除租约"""
    db, _ = temp_db
    
    # 创建 queued run
    request = runs.RunCreateRequest(type="sleep", input={"seconds": 5})
    run_response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    run_id = run_response["id"]
    
    # Worker 抢占
    worker_id = "worker-1"
    lease_seconds = 60
    
    claimed_run = claim_run(db, run_id, worker_id, lease_seconds)
    _commit_db(db)
    assert claimed_run is not None
    assert claimed_run.lease_expires_at is not None
    
    # 完成任务（成功）
    output_json = {"ok": True, "slept": 5}
    complete_success(db, run_id, output_json)
    _commit_db(db)
    
    # 验证状态和租约
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    assert db_run.status == RunStatus.SUCCEEDED
    assert db_run.lease_expires_at is None
    assert db_run.output_json == output_json
    assert db_run.progress == 100
    assert db_run.error is None


def test_complete_failed_clears_lease(temp_db) -> None:
    """测试失败完成任务后清除租约"""
    db, _ = temp_db
    
    # 创建 queued run
    request = runs.RunCreateRequest(type="sleep", input={"seconds": 5})
    run_response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    run_id = run_response["id"]
    
    # Worker 抢占
    worker_id = "worker-1"
    lease_seconds = 60
    
    claimed_run = claim_run(db, run_id, worker_id, lease_seconds)
    _commit_db(db)
    assert claimed_run is not None
    assert claimed_run.lease_expires_at is not None
    
    # 完成任务（失败）
    error_msg = "Task execution failed"
    complete_failed(db, run_id, error_msg)
    _commit_db(db)
    
    # 验证状态和租约
    db_run = db.query(RunModel).filter(RunModel.id == run_id).first()
    assert db_run.status == RunStatus.FAILED
    assert db_run.lease_expires_at is None
    assert db_run.error == error_msg


def test_fetch_and_claim_run(temp_db) -> None:
    """测试 fetch_and_claim_run 包装函数"""
    db, _ = temp_db
    
    # 创建 queued run
    request = runs.RunCreateRequest(type="sleep", input={"seconds": 5})
    run_response = asyncio.run(runs._create_run(request, db))
    _commit_db(db)
    run_id = run_response["id"]
    
    # 使用 fetch_and_claim_run
    worker_id = "worker-1"
    lease_seconds = 60
    claimed_run = fetch_and_claim_run(db, worker_id, lease_seconds)
    _commit_db(db)
    
    # 验证抢占成功
    assert claimed_run is not None
    assert claimed_run.id == run_id
    assert claimed_run.status == RunStatus.RUNNING
    assert claimed_run.worker_id == worker_id


def test_fetch_runnable_candidate_prioritizes_queued(temp_db) -> None:
    """测试 fetch_runnable_candidate 优先返回 queued 任务"""
    db, _ = temp_db
    
    # 创建一个过期的 running run
    request1 = runs.RunCreateRequest(type="sleep", input={"seconds": 1})
    run1_response = asyncio.run(runs._create_run(request1, db))
    _commit_db(db)
    run1_id = run1_response["id"]
    
    # 抢占并设置为过期
    worker_a = "worker-a"
    claimed_run1 = claim_run(db, run1_id, worker_a, 60)
    _commit_db(db)
    db_run1 = db.query(RunModel).filter(RunModel.id == run1_id).first()
    db_run1.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
    db_run1.status = RunStatus.RUNNING
    _commit_db(db)
    
    # 创建一个 queued run（后创建，但应该优先）
    request2 = runs.RunCreateRequest(type="sleep", input={"seconds": 2})
    run2_response = asyncio.run(runs._create_run(request2, db))
    _commit_db(db)
    run2_id = run2_response["id"]
    
    # fetch_runnable_candidate 应该返回 queued 的 run2，而不是过期的 run1
    now = datetime.now(UTC)
    candidate_id = fetch_runnable_candidate(db, now)
    assert candidate_id == run2_id  # queued 优先
