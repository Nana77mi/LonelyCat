"""Tests for edit_docs_propose and edit_docs_apply (two-phase, WAIT_CONFIRM)."""

from unittest.mock import Mock

import pytest

from worker.runner import TaskRunner


def test_edit_docs_propose_output_has_waits_confirm_and_diff():
    """edit_docs_propose 执行后 SUCCEEDED，output 含 task_state=WAIT_CONFIRM、artifacts.diff、patch_id 全量+短显。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"target_path": "/sandbox/example.txt"}
    result = runner._handle_edit_docs_propose(run, lambda: True)
    assert result.get("ok") is True
    assert result.get("result", {}).get("task_state") == "WAIT_CONFIRM"
    artifacts = result.get("artifacts", {})
    assert "diff" in artifacts
    assert "patch_id" in artifacts
    assert len(artifacts["patch_id"]) == 64
    assert "patch_id_short" in artifacts
    assert artifacts["patch_id_short"] == artifacts["patch_id"][:16]
    assert "files" in artifacts
    assert artifacts.get("applied") is False
    steps = result.get("steps", [])
    names = [s["name"] for s in steps]
    assert "read_file" in names
    assert "propose_patch" in names
    assert "present_diff" in names


def test_edit_docs_apply_reads_parent_and_sets_applied():
    """edit_docs_apply 从 parent run 读 diff，校验 patch_id 后执行，artifacts.applied 为 True。"""
    runner = TaskRunner()
    parent_run = Mock()
    parent_run.id = "parent-123"
    full_id = "a" * 64
    parent_run.output_json = {
        "artifacts": {
            "diff": "--- a/f\n+++ b/f\n@@ -1 +1 @@\n-old\n+new\n",
            "patch_id": full_id,
            "files": ["f"],
        }
    }
    run = Mock()
    run.input_json = {"parent_run_id": "parent-123", "patch_id": full_id[:16]}
    run.type = "edit_docs_apply"
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = parent_run
    result = runner._handle_edit_docs_apply(run, db, lambda: True)
    assert result.get("ok") is True
    assert result.get("artifacts", {}).get("applied") is True
    steps = result.get("steps", [])
    names = [s["name"] for s in steps]
    assert "apply_patch" in names


def test_edit_docs_apply_patch_id_mismatch_raises():
    """input.patch_id 与 parent artifacts.patch_id 不一致时 PatchMismatch。"""
    runner = TaskRunner()
    parent_run = Mock()
    parent_run.id = "parent-123"
    parent_run.output_json = {
        "artifacts": {
            "diff": "--- a/f\n+++ b/f\n",
            "patch_id": "a" * 64,
            "files": ["f"],
        }
    }
    run = Mock()
    run.input_json = {"parent_run_id": "parent-123", "patch_id": "b" * 16}
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = parent_run
    with pytest.raises(ValueError, match="PatchMismatch"):
        runner._handle_edit_docs_apply(run, db, lambda: True)
