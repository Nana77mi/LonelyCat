"""PR3: Sandbox API GET /execs、GET /execs/{id}、GET /execs/{id}/artifacts 与 POST 持久化。"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.sandbox import get_db
from app.db import Base, SandboxExecRecord, SandboxExecStatus, SettingsModel
from app.main import app
from app.services.sandbox.schemas import SandboxExecResponse


@pytest.fixture
def temp_db_and_workspace():
    """临时 DB + 临时 workspace 目录；并插入 settings 与一条 exec 记录及 manifest。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    root = tempfile.mkdtemp(prefix="lc_sandbox_pr3_")
    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        # 默认 settings，workspace 指向 temp 目录
        settings_value = {
            "version": "settings_v0",
            "sandbox": {
                "workspace_root_win": root,
                "workspace_root_wsl": root,
                "runtime_mode": "windows",
            },
        }
        db.add(SettingsModel(key="v0", value=settings_value, updated_at=datetime.now(UTC)))
        db.commit()
        exec_id = "e_test1234567890ab"
        artifacts_path = f"projects/p1/artifacts/{exec_id}"
        art_dir = Path(root) / artifacts_path
        art_dir.mkdir(parents=True, exist_ok=True)
        (art_dir / "manifest.json").write_text(
            json.dumps({"files": [{"path": "stdout.txt", "size": 10, "hash": "abc"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        rec = SandboxExecRecord(
            exec_id=exec_id,
            project_id="p1",
            task_id="task-1",
            conversation_id=None,
            skill_id="shell.run",
            image="lonelycat-sandbox:py312",
            cmd="bash",
            args=json.dumps(["-lc", "echo 1"], ensure_ascii=False),
            cwd="work",
            env_keys=json.dumps([], ensure_ascii=False),
            policy_snapshot=None,
            status=SandboxExecStatus.SUCCEEDED,
            exit_code=0,
            error_reason=None,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            duration_ms=100,
            artifacts_path=artifacts_path,
            stdout_truncated=False,
            stderr_truncated=False,
        )
        db.add(rec)
        db.commit()
        yield db, root, exec_id
        db.close()
    finally:
        try:
            import shutil
            shutil.rmtree(root, ignore_errors=True)
        except Exception:
            pass
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_get_sandbox_execs_empty():
    """GET /sandbox/execs 无记录时返回 []。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        db.add(SettingsModel(key="v0", value={"version": "settings_v0", "sandbox": {}}, updated_at=datetime.now(UTC)))
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.get("/sandbox/execs")
            assert r.status_code == 200
            assert r.json() == []
        finally:
            app.dependency_overrides.pop(get_db, None)
        db.close()
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_get_sandbox_execs_list_and_detail_and_artifacts(temp_db_and_workspace):
    """GET /sandbox/execs、GET /sandbox/execs/{id}、GET /sandbox/execs/{id}/artifacts。"""
    db, _root, exec_id = temp_db_and_workspace

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        # 列表
        r = client.get("/sandbox/execs")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["exec_id"] == exec_id
        assert data[0]["project_id"] == "p1"
        assert data[0]["task_id"] == "task-1"
        assert data[0]["status"] == "SUCCEEDED"
        assert data[0]["artifacts_path"] == f"projects/p1/artifacts/{exec_id}"

        # ?task_id= 筛选
        r2 = client.get("/sandbox/execs", params={"task_id": "task-1"})
        assert r2.status_code == 200
        assert len(r2.json()) == 1
        r3 = client.get("/sandbox/execs", params={"task_id": "other"})
        assert r3.status_code == 200
        assert r3.json() == []

        # 详情
        r4 = client.get(f"/sandbox/execs/{exec_id}")
        assert r4.status_code == 200
        detail = r4.json()
        assert detail["exec_id"] == exec_id
        assert detail["cmd"] == "bash"
        assert detail["args"] == ["-lc", "echo 1"]
        assert detail["exit_code"] == 0

        # 产物列表（含 exec_id、artifacts_dir、missing_manifest）
        r5 = client.get(f"/sandbox/execs/{exec_id}/artifacts")
        assert r5.status_code == 200
        art = r5.json()
        assert art["exec_id"] == exec_id
        assert art["artifacts_dir"] == f"projects/p1/artifacts/{exec_id}"
        assert art["files"] == [{"path": "stdout.txt", "size": 10, "hash": "abc"}]
        assert art["missing_manifest"] is False
        assert art.get("missing_reason") is None
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_get_sandbox_exec_404():
    """GET /sandbox/execs/{id} 不存在返回 404。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        db.add(SettingsModel(key="v0", value={"version": "settings_v0", "sandbox": {}}, updated_at=datetime.now(UTC)))
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.get("/sandbox/execs/e_nonexistent")
            assert r.status_code == 404
            r2 = client.get("/sandbox/execs/e_nonexistent/artifacts")
            assert r2.status_code == 404
        finally:
            app.dependency_overrides.pop(get_db, None)
        db.close()
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_post_sandbox_execs_persists_record():
    """POST /sandbox/execs 成功后将记录写入 sandbox_execs，GET /execs 可查到。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    root = tempfile.mkdtemp(prefix="lc_sandbox_pr3_post_")
    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        settings_value = {
            "version": "settings_v0",
            "sandbox": {"workspace_root_win": root, "workspace_root_wsl": root, "runtime_mode": "windows"},
        }
        db.add(SettingsModel(key="v0", value=settings_value, updated_at=datetime.now(UTC)))
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        fake_resp = SandboxExecResponse(
            exec_id="e_mock1234567890ab",
            status="SUCCEEDED",
            exit_code=0,
            artifacts_dir="projects/p1/artifacts/e_mock1234567890ab",
            stdout_path="stdout.txt",
            stderr_path="stderr.txt",
        )
        app.dependency_overrides[get_db] = override_get_db
        with patch("app.api.sandbox.run_sandbox_exec", return_value=fake_resp):
            try:
                client = TestClient(app)
                r = client.post(
                    "/sandbox/execs",
                    json={
                        "project_id": "p1",
                        "skill_id": "shell.run",
                        "exec": {"kind": "shell", "command": "bash", "args": ["-lc", "echo 1"]},
                        "inputs": [],
                        "task_ref": {"task_id": "t1", "conversation_id": None},
                    },
                )
                assert r.status_code == 200
                body = r.json()
                exec_id_returned = body["exec_id"]
                assert exec_id_returned.startswith("e_") and len(exec_id_returned) == 18
                assert body["status"] == "SUCCEEDED"
                list_r = client.get("/sandbox/execs")
                assert list_r.status_code == 200
                items = list_r.json()
                assert len(items) == 1
                assert items[0]["exec_id"] == exec_id_returned
                assert items[0]["status"] == "SUCCEEDED"
                # 详情中 status 一致，env_keys 仅 key 不存敏感 value
                detail_r = client.get(f"/sandbox/execs/{items[0]['exec_id']}")
                assert detail_r.status_code == 200
                detail = detail_r.json()
                assert detail["status"] == "SUCCEEDED"
                assert detail["env_keys"] is not None
                assert isinstance(detail["env_keys"], list)
                # env_keys 不应包含 value，仅 key 名
                for k in detail["env_keys"]:
                    assert isinstance(k, str)
            finally:
                app.dependency_overrides.pop(get_db, None)
        db.close()
    finally:
        try:
            import shutil
            shutil.rmtree(root, ignore_errors=True)
        except Exception:
            pass
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_get_sandbox_execs_ordering_desc(temp_db_and_workspace):
    """GET /sandbox/execs 按 started_at 倒序；插入两条不同时间，确保先新后旧。"""
    db, _root, exec_id = temp_db_and_workspace
    from app.db import SandboxExecStatus
    # 插入第二条，started_at 更早
    rec2 = SandboxExecRecord(
        exec_id="e_older000000000001",
        project_id="p1",
        task_id="task-1",
        conversation_id=None,
        skill_id="shell.run",
        status=SandboxExecStatus.SUCCEEDED,
        started_at=datetime.now(UTC).replace(year=2020),
        ended_at=datetime.now(UTC),
        duration_ms=100,
        artifacts_path="projects/p1/artifacts/e_older000000000001",
    )
    db.add(rec2)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        r = client.get("/sandbox/execs")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 2
        # 第一条应为更新的（exec_id 或 started_at 更晚）
        first_started = data[0].get("started_at")
        second_started = data[1].get("started_at")
        assert first_started >= second_started
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_sandbox_health_probe_param(temp_db_and_workspace):
    """GET /sandbox/health 无 probe 不返回 probe_*；?probe=1 时执行探针并返回 probe_run、probe_ok、probe_error。"""
    db, root, _exec_id = temp_db_and_workspace

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        r = client.get("/sandbox/health")
        assert r.status_code == 200
        data = r.json()
        assert "probe_run" not in data

        with patch("app.api.sandbox.subprocess.run") as mock_run:
            mock_run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            r2 = client.get("/sandbox/health", params={"probe": 1})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2.get("probe_run") is True
        assert d2.get("probe_ok") is True
        assert d2.get("probe_error") is None

        with patch("app.api.sandbox.subprocess.run") as mock_run:
            import subprocess
            mock_run.side_effect = subprocess.TimeoutExpired("docker", 5)
            r3 = client.get("/sandbox/health", params={"probe": 1})
        assert r3.status_code == 200
        d3 = r3.json()
        assert d3.get("probe_run") is True
        assert d3.get("probe_ok") is False
        assert isinstance(d3.get("probe_error"), str) and len(d3["probe_error"]) > 0
    finally:
        app.dependency_overrides.pop(get_db, None)

# ===== PR-1: stdout/stderr/observation endpoints =====


@contextmanager
def temp_db_and_workspace_with_output():
    """创建包含 stdout/stderr 文件的测试环境（独立 fixture）"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    root = tempfile.mkdtemp(prefix="lc_sandbox_pr1_")
    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        # 默认 settings，workspace 指向 temp 目录
        settings_value = {
            "version": "settings_v0",
            "sandbox": {
                "workspace_root_win": root,
                "workspace_root_wsl": root,
                "runtime_mode": "windows",
            },
        }
        db.add(SettingsModel(key="v0", value=settings_value, updated_at=datetime.now(UTC)))
        db.commit()
        exec_id = "e_test1234567890ab"
        artifacts_path = f"projects/p1/artifacts/{exec_id}"
        art_dir = Path(root) / artifacts_path
        art_dir.mkdir(parents=True, exist_ok=True)

        # 创建 manifest.json
        (art_dir / "manifest.json").write_text(
            json.dumps({"files": [
                {"path": "stdout.txt", "size": 7, "hash": "abc"},
                {"path": "stderr.txt", "size": 22, "hash": "def"}
            ]}, ensure_ascii=False),
            encoding="utf-8",
        )

        # 创建 stdout.txt 和 stderr.txt
        stdout_content = "328350\n"
        stderr_content = "Some warning message\n"
        (art_dir / "stdout.txt").write_text(stdout_content, encoding="utf-8")
        (art_dir / "stderr.txt").write_text(stderr_content, encoding="utf-8")

        rec = SandboxExecRecord(
            exec_id=exec_id,
            project_id="p1",
            task_id="task-1",
            conversation_id=None,
            skill_id="python.run",
            image="lonelycat-sandbox:py312",
            cmd="python",
            args=json.dumps(["-c", "print(...)"], ensure_ascii=False),
            cwd="work",
            env_keys=json.dumps([], ensure_ascii=False),
            policy_snapshot=None,
            status=SandboxExecStatus.SUCCEEDED,
            exit_code=0,
            error_reason=None,
            started_at=datetime.now(UTC),
            ended_at=datetime.now(UTC),
            duration_ms=100,
            artifacts_path=artifacts_path,
            stdout_truncated=False,
            stderr_truncated=False,
        )
        db.add(rec)
        db.commit()
        yield db, root, exec_id, stdout_content, stderr_content
        db.close()
    finally:
        try:
            import shutil
            shutil.rmtree(root, ignore_errors=True)
        except Exception:
            pass
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_get_stdout_normal():
    """GET /sandbox/execs/{id}/stdout 正常返回：content, truncated, bytes"""
    with temp_db_and_workspace_with_output() as (db, root, exec_id, stdout_content, stderr_content):
        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.get(f"/sandbox/execs/{exec_id}/stdout")
            assert r.status_code == 200
            data = r.json()
            assert data["exec_id"] == exec_id
            assert data["content"] == stdout_content
            assert data["truncated"] is False
            # bytes 是实际返回内容的字节数
            assert data["bytes"] == len(stdout_content.encode("utf-8"))
            assert data.get("missing_file") is None
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_get_stdout_truncated():
    """GET /sandbox/execs/{id}/stdout 返回 truncated=true（从 DB 字段）"""
    with temp_db_and_workspace_with_output() as (db, root, exec_id, stdout_content, stderr_content):
        # 修改 DB 记录，设置 stdout_truncated=True
        rec = db.query(SandboxExecRecord).filter(SandboxExecRecord.exec_id == exec_id).first()
        rec.stdout_truncated = True
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.get(f"/sandbox/execs/{exec_id}/stdout")
            assert r.status_code == 200
            data = r.json()
            assert data["truncated"] is True
            # 即使截断，bytes 也应该是实际返回内容的字节数
            assert data["bytes"] == len(stdout_content.encode("utf-8"))
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_get_stdout_missing_file():
    """GET /sandbox/execs/{id}/stdout 文件不存在：返回 content="", missing_file=true"""
    with temp_db_and_workspace_with_output() as (db, root, exec_id, stdout_content, stderr_content):
        # 删除 stdout.txt 文件
        art_dir = Path(root) / f"projects/p1/artifacts/{exec_id}"
        (art_dir / "stdout.txt").unlink()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.get(f"/sandbox/execs/{exec_id}/stdout")
            assert r.status_code == 200
            data = r.json()
            assert data["exec_id"] == exec_id
            assert data["content"] == ""
            assert data["missing_file"] is True
            assert data["bytes"] == 0
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_get_stderr_normal():
    """GET /sandbox/execs/{id}/stderr 正常返回：content, truncated, bytes"""
    with temp_db_and_workspace_with_output() as (db, root, exec_id, stdout_content, stderr_content):
        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.get(f"/sandbox/execs/{exec_id}/stderr")
            assert r.status_code == 200
            data = r.json()
            assert data["exec_id"] == exec_id
            assert data["content"] == stderr_content
            assert data["truncated"] is False
            assert data["bytes"] == len(stderr_content.encode("utf-8"))
            assert data.get("missing_file") is None
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_get_stderr_missing_file():
    """GET /sandbox/execs/{id}/stderr 文件不存在：返回 content="", missing_file=true"""
    with temp_db_and_workspace_with_output() as (db, root, exec_id, stdout_content, stderr_content):
        # 删除 stderr.txt 文件
        art_dir = Path(root) / f"projects/p1/artifacts/{exec_id}"
        (art_dir / "stderr.txt").unlink()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.get(f"/sandbox/execs/{exec_id}/stderr")
            assert r.status_code == 200
            data = r.json()
            assert data["content"] == ""
            assert data["missing_file"] is True
            assert data["bytes"] == 0
        finally:
            app.dependency_overrides.pop(get_db, None)


def test_get_observation_aggregated():
    """GET /sandbox/execs/{id}/observation 聚合返回完整信息"""
    with temp_db_and_workspace_with_output() as (db, root, exec_id, stdout_content, stderr_content):
        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.get(f"/sandbox/execs/{exec_id}/observation")
            assert r.status_code == 200
            data = r.json()
            assert data["exec_id"] == exec_id
            assert data["exit_code"] == 0

            # 验证 stdout
            assert data["stdout"]["content"] == stdout_content
            assert data["stdout"]["truncated"] is False
            assert data["stdout"]["bytes"] == len(stdout_content.encode("utf-8"))

            # 验证 stderr
            assert data["stderr"]["content"] == stderr_content
            assert data["stderr"]["truncated"] is False
            assert data["stderr"]["bytes"] == len(stderr_content.encode("utf-8"))

            # 验证 artifacts
            assert "artifacts" in data
            assert data["artifacts"]["missing_manifest"] is False
            assert len(data["artifacts"]["files"]) > 0
        finally:
            app.dependency_overrides.pop(get_db, None)
