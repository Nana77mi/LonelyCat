"""TDD: Sandbox spec and models (PR0).

- Skill manifests under skills/ must validate against skills/_schema/manifest.schema.json.
- SandboxExecRecord table exists and has expected columns; SandboxPolicy has expected defaults.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

# Repo root: from apps/core-api/tests -> ../../..
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SKILLS_SCHEMA_PATH = REPO_ROOT / "skills" / "_schema" / "manifest.schema.json"
SKILLS_MANIFESTS = [
    REPO_ROOT / "skills" / "shell.run" / "manifest.json",
    REPO_ROOT / "skills" / "python.run" / "manifest.json",
]


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TestSkillManifestSchema:
    """Manifests must conform to manifest.schema.json (id pattern, runtime.kind=docker, permissions)."""

    @pytest.fixture
    def schema(self):
        if not SKILLS_SCHEMA_PATH.exists():
            pytest.skip("skills/_schema/manifest.schema.json not found (run from repo root)")
        return _load_json(SKILLS_SCHEMA_PATH)

    @pytest.fixture
    def validator(self, schema):
        try:
            import jsonschema
        except ImportError:
            pytest.skip("jsonschema not installed")
        return jsonschema.Draft7Validator(schema)

    @pytest.mark.parametrize("manifest_path", SKILLS_MANIFESTS)
    def test_manifest_valid_against_schema(self, manifest_path, validator):
        if not manifest_path.exists():
            pytest.skip(f"{manifest_path} not found")
        data = _load_json(manifest_path)
        validator.validate(data)

    @pytest.mark.parametrize("manifest_path", SKILLS_MANIFESTS)
    def test_manifest_id_pattern(self, manifest_path):
        if not manifest_path.exists():
            pytest.skip(f"{manifest_path} not found")
        data = _load_json(manifest_path)
        import re
        assert "id" in data
        assert re.match(r"^[a-z0-9]+(\.[a-z0-9]+)+$", data["id"]), f"id must match [a-z0-9]+(.[a-z0-9]+)+: {data['id']}"

    @pytest.mark.parametrize("manifest_path", SKILLS_MANIFESTS)
    def test_manifest_runtime_kind_docker(self, manifest_path):
        if not manifest_path.exists():
            pytest.skip(f"{manifest_path} not found")
        data = _load_json(manifest_path)
        assert data.get("runtime", {}).get("kind") == "docker"

    @pytest.mark.parametrize("manifest_path", SKILLS_MANIFESTS)
    def test_manifest_net_mode_none(self, manifest_path):
        if not manifest_path.exists():
            pytest.skip(f"{manifest_path} not found")
        data = _load_json(manifest_path)
        assert data.get("permissions", {}).get("net", {}).get("mode") == "none"


class TestSandboxExecRecord:
    """SandboxExecRecord model exists and table has expected columns."""

    def test_sandbox_exec_record_import(self):
        from app.db import SandboxExecRecord
        assert SandboxExecRecord is not None

    def test_sandbox_exec_record_table_created(self):
        from app.db import Base, engine, SandboxExecRecord
        Base.metadata.create_all(bind=engine)
        from sqlalchemy import inspect
        inspector = inspect(engine)
        assert "sandbox_execs" in inspector.get_table_names()

    def test_sandbox_exec_record_expected_columns(self):
        from app.db import SandboxExecRecord
        cols = {c.name for c in SandboxExecRecord.__table__.columns}
        required = {
            "exec_id", "project_id", "task_id", "conversation_id", "skill_id",
            "image", "cmd", "args", "cwd", "env_keys", "policy_snapshot",
            "status", "exit_code", "error_reason", "started_at", "ended_at",
            "duration_ms", "artifacts_path", "stdout_truncated", "stderr_truncated",
            "idempotency_key",
        }
        assert required.issubset(cols), f"missing columns: {required - cols}"

    def test_sandbox_exec_record_crud(self):
        from app.db import SandboxExecRecord, SessionLocal, SandboxExecStatus
        from datetime import datetime, UTC
        db = SessionLocal()
        try:
            rec = SandboxExecRecord(
                exec_id="e_test_pr0",
                project_id="p_1",
                task_id="t_1",
                conversation_id="c_1",
                skill_id="shell.run",
                image="lonelycat-sandbox:py312",
                cmd="bash",
                args='["-lc", "echo 1"]',
                cwd="work",
                env_keys="[]",
                policy_snapshot="{}",
                status=SandboxExecStatus.SUCCEEDED,
                exit_code=0,
                error_reason=None,
                started_at=datetime.now(UTC),
                ended_at=datetime.now(UTC),
                duration_ms=100,
                artifacts_path="/tmp/artifacts/e_test_pr0",
                stdout_truncated=False,
                stderr_truncated=False,
            )
            db.add(rec)
            db.commit()
            found = db.query(SandboxExecRecord).filter(SandboxExecRecord.exec_id == "e_test_pr0").first()
            assert found is not None
            assert found.status == SandboxExecStatus.SUCCEEDED
            db.delete(found)
            db.commit()
        finally:
            db.close()


class TestSandboxPolicyDefaults:
    """SandboxPolicy (or system default policy) has expected default limits."""

    def test_sandbox_policy_defaults_import(self):
        from app.services.sandbox.schemas import SandboxPolicy
        assert SandboxPolicy is not None

    def test_sandbox_policy_default_timeout_and_limits(self):
        from app.services.sandbox.schemas import SandboxPolicy
        p = SandboxPolicy()
        assert p.timeout_ms == 60_000
        assert p.max_stdout_bytes == 1_048_576
        assert p.max_stderr_bytes == 1_048_576
        assert p.max_artifacts_bytes_total == 52_428_800
        assert p.memory_mb == 1024
        assert p.cpu_cores == 1
        assert p.pids == 256
        assert p.net_mode == "none"
