"""Tests for sleep task: trace_id, steps, artifacts (run_task_with_steps)."""

from unittest.mock import Mock

import pytest

from worker.runner import TaskRunner


def test_sleep_output_has_trace_id_steps_and_task_type():
    """sleep 执行后 output 含 trace_id、steps、task_type、version。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"seconds": 0, "trace_id": "a" * 32}
    result = runner._handle_sleep(run, lambda: True)
    assert result["trace_id"] == "a" * 32
    assert result.get("version") == "task_result_v0"
    assert result.get("task_type") == "sleep"
    assert "steps" in result
    names = [s["name"] for s in result["steps"]]
    assert names == ["sleep"]
    for s in result["steps"]:
        assert "duration_ms" in s
        assert s["duration_ms"] >= 0
        assert "ok" in s
        assert "error_code" in s
        assert "meta" in s


def test_sleep_output_has_result_and_artifacts():
    """sleep 的 result.slept 与 artifacts 存在。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"seconds": 0}
    result = runner._handle_sleep(run, lambda: True)
    assert result.get("ok") is True
    assert "result" in result
    assert result["result"].get("slept") == 0
    assert "artifacts" in result
    assert result["artifacts"].get("duration_seconds") == 0


def test_sleep_step_meta_has_seconds_requested_and_slept():
    """sleep 步骤的 meta 含 seconds_requested、slept，便于 Drawer/Debug bundle 排查。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"seconds": 1}
    result = runner._handle_sleep(run, lambda: True)
    steps = result.get("steps", [])
    assert len(steps) == 1
    meta = steps[0].get("meta", {})
    assert meta.get("seconds_requested") == 1
    assert meta.get("slept") == 1


def test_sleep_slept_seconds_match_input():
    """seconds=2 时 result.slept 为 2（需实际 sleep 约 2 秒）。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"seconds": 2}
    result = runner._handle_sleep(run, lambda: True)
    assert result.get("ok") is True
    assert result["result"]["slept"] == 2
    assert result["artifacts"].get("duration_seconds") == 2


def test_sleep_heartbeat_failure_raises():
    """心跳失败时抛出 RuntimeError（任务被接管）。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"seconds": 10}
    first_call = [True]

    def fail_after_first():
        if first_call[0]:
            first_call[0] = False
            return True
        return False

    with pytest.raises(RuntimeError, match="Heartbeat"):
        runner._handle_sleep(run, fail_after_first)


def test_sleep_invalid_seconds_raises():
    """seconds 非法时抛出 ValueError（可读 message）。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"seconds": -1}
    with pytest.raises(ValueError, match=">= 0"):
        runner._handle_sleep(run, lambda: True)
