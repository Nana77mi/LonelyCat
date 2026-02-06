"""PR4: GET /skills、POST /skills/{id}/invoke 测试。"""
from __future__ import annotations

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.sandbox import get_db
from app.db import Base, SettingsModel
from app.main import app

# 单测从 apps/core-api/tests 运行，repo 根为 parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def skills_root_env(monkeypatch):
    """确保 GET /skills 能读到 repo 下 skills/。"""
    monkeypatch.setenv("REPO_ROOT", str(REPO_ROOT))


def test_get_skills_list():
    """GET /skills 返回技能列表，含 id、name、description、runtime、interface。"""
    client = TestClient(app)
    r = client.get("/skills")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    ids = [s["id"] for s in data]
    assert "shell.run" in ids
    assert "python.run" in ids
    for s in data:
        assert "id" in s and "name" in s and "description" in s
        assert "runtime" in s and "interface" in s
        if s["id"] == "shell.run":
            assert s["runtime"].get("entrypoint") == "bash"
            assert "inputs" in s["interface"]


def test_get_skills_list_503_when_not_configured(monkeypatch):
    """当 skills 根未配置（如 REPO_ROOT 指向无 skills/_schema 的目录）时返回 503 并提示。"""
    monkeypatch.setenv("REPO_ROOT", tempfile.mkdtemp())
    monkeypatch.delenv("SKILLS_ROOT", raising=False)
    client = TestClient(app)
    r = client.get("/skills")
    assert r.status_code == 503
    data = r.json()
    assert data.get("detail", {}).get("code") == "SKILLS_NOT_CONFIGURED"
    assert "REPO_ROOT" in str(data.get("detail", {}).get("message", ""))


def test_post_skill_invoke_shell_run():
    """POST /skills/shell.run/invoke 使用 manifest 构建 exec 并执行沙箱（mock runner）。"""
    root = tempfile.mkdtemp(prefix="lc_skills_invoke_")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        db.add(
            SettingsModel(
                key="v0",
                value={
                    "version": "settings_v0",
                    "sandbox": {
                        "workspace_root_win": root,
                        "workspace_root_wsl": root,
                        "runtime_mode": "windows",
                    },
                },
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            with patch("app.api.sandbox.run_sandbox_exec") as mock_run:
                from app.services.sandbox.schemas import SandboxExecResponse

                mock_run.return_value = SandboxExecResponse(
                    exec_id="e_mock123",
                    status="SUCCEEDED",
                    exit_code=0,
                    artifacts_dir="projects/p1/artifacts/e_mock123",
                    stdout_path="stdout.txt",
                    stderr_path="stderr.txt",
                )
                client = TestClient(app)
                r = client.post(
                    "/skills/shell.run/invoke",
                    json={"project_id": "p1", "script": "echo hello"},
                )
            assert r.status_code == 200
            data = r.json()
            assert "exec_id" in data
            assert data["status"] == "SUCCEEDED"
            assert data["exit_code"] == 0
        finally:
            app.dependency_overrides.pop(get_db, None)
        db.close()
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass
        try:
            import shutil
            shutil.rmtree(root, ignore_errors=True)
        except Exception:
            pass


def test_post_skill_invoke_shell_run_missing_script():
    """POST /skills/shell.run/invoke 缺少 script 返回 400。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        db.add(SettingsModel(key="v0", value={"version": "settings_v0", "sandbox": {"workspace_root_win": "/tmp", "workspace_root_wsl": "/tmp", "runtime_mode": "windows"}}, updated_at=datetime.now(UTC)))
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.post("/skills/shell.run/invoke", json={"project_id": "p1"})
            assert r.status_code == 400
        finally:
            app.dependency_overrides.pop(get_db, None)
        db.close()
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_post_skill_invoke_not_found():
    """POST /skills/nonexistent.run/invoke 返回 404。"""
    client = TestClient(app)
    r = client.post("/skills/nonexistent.run/invoke", json={"project_id": "p1", "script": "true"})
    assert r.status_code == 404


def test_get_skills_skips_bad_manifest(monkeypatch):
    """GET /skills 遇到 schema 校验失败的 manifest 时跳过该 skill，仍返回 200。"""
    tmp = tempfile.mkdtemp(prefix="lc_skills_bad_")
    try:
        skills_root = Path(tmp)
        (skills_root / "shell.run").mkdir(parents=True)
        (skills_root / "invalid.one").mkdir(parents=True)
        schema_dir = skills_root / "_schema"
        schema_dir.mkdir(parents=True)
        # 从 repo 拷贝 schema 和合法 manifest
        repo_skills = REPO_ROOT / "skills"
        schema_src = repo_skills / "_schema" / "manifest.schema.json"
        if schema_src.is_file():
            import shutil
            shutil.copy(schema_src, schema_dir / "manifest.schema.json")
        manifest_ok = repo_skills / "shell.run" / "manifest.json"
        if manifest_ok.is_file():
            import shutil
            shutil.copy(manifest_ok, skills_root / "shell.run" / "manifest.json")
        # 坏 manifest：缺 required 字段（如 runtime）
        (skills_root / "invalid.one" / "manifest.json").write_text(
            '{"id":"invalid.one","name":"Bad","description":"x"}',
            encoding="utf-8",
        )
        monkeypatch.setenv("SKILLS_ROOT", str(skills_root))
        client = TestClient(app)
        r = client.get("/skills")
        assert r.status_code == 200
        data = r.json()
        ids = [s["id"] for s in data]
        assert "invalid.one" not in ids
        if manifest_ok.is_file():
            assert "shell.run" in ids
    finally:
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass


def test_python_run_script_path_traversal_rejected():
    """POST /skills/python.run/invoke 的 script_path 含 .. 或路径穿越返回 400。"""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        db.add(
            SettingsModel(
                key="v0",
                value={
                    "version": "settings_v0",
                    "sandbox": {"workspace_root_win": "/tmp", "workspace_root_wsl": "/tmp", "runtime_mode": "windows"},
                },
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            client = TestClient(app)
            r = client.post(
                "/skills/python.run/invoke",
                json={"project_id": "p1", "script_path": "../x.py"},
            )
            assert r.status_code == 400
            detail = r.json().get("detail")
            msg = detail.get("message", "") if isinstance(detail, dict) else str(detail)
            assert "script_path" in msg or "穿越" in msg
        finally:
            app.dependency_overrides.pop(get_db, None)
        db.close()
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass


def test_python_run_script_path_ok():
    """POST /skills/python.run/invoke 的 script_path 为合法相对路径 a/b.py 可接受。"""
    root = tempfile.mkdtemp(prefix="lc_skills_py_")
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = Session()
        db.add(
            SettingsModel(
                key="v0",
                value={
                    "version": "settings_v0",
                    "sandbox": {
                        "workspace_root_win": root,
                        "workspace_root_wsl": root,
                        "runtime_mode": "windows",
                    },
                },
                updated_at=datetime.now(UTC),
            )
        )
        db.commit()

        def override_get_db():
            try:
                yield db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        try:
            with patch("app.api.sandbox.run_sandbox_exec") as mock_run:
                from app.services.sandbox.schemas import SandboxExecResponse

                mock_run.return_value = SandboxExecResponse(
                    exec_id="e_py",
                    status="SUCCEEDED",
                    exit_code=0,
                    artifacts_dir="projects/p1/artifacts/e_py",
                    stdout_path="stdout.txt",
                    stderr_path="stderr.txt",
                )
                client = TestClient(app)
                r = client.post(
                    "/skills/python.run/invoke",
                    json={"project_id": "p1", "script_path": "a/b.py"},
                )
            assert r.status_code == 200
            assert r.json().get("status") == "SUCCEEDED"
        finally:
            app.dependency_overrides.pop(get_db, None)
        db.close()
    finally:
        try:
            os.unlink(db_path)
        except Exception:
            pass
        try:
            import shutil
            shutil.rmtree(root, ignore_errors=True)
        except Exception:
            pass
