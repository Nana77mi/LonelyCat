"""PR6: run_code_snippet 任务 — TDD 先写测试。"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from worker.runner import TaskRunner
from worker.tools.catalog import ToolCatalog
from worker.tools.provider import BuiltinProvider, StubProvider
from worker.tools.skills_provider import SkillsProvider


def _mock_skills_client(invoke_response: dict):
    """返回 mock client：GET /skills 返回 python.run + shell.run，POST invoke 返回给定 response。"""
    client = MagicMock()
    client.get.return_value.status_code = 200
    client.get.return_value.json.return_value = [
        {"id": "python.run", "name": "Run Python", "interface": {"inputs": {}}, "limits": {}},
        {"id": "shell.run", "name": "Run Shell", "interface": {"inputs": {}}, "limits": {}},
    ]
    client.post.return_value.status_code = 200
    client.post.return_value.json.return_value = invoke_response
    return client


def _make_run_code_snippet_catalog(invoke_response: dict):
    client = _mock_skills_client(invoke_response)
    catalog = ToolCatalog(preferred_provider_order=["skills", "builtin", "stub"])
    catalog.register_provider("skills", SkillsProvider(base_url="http://core:5173", client=client))
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    return catalog, client


def test_run_code_snippet_python_output_has_exec_result_and_step():
    """run_code_snippet(language=python, code=...) 执行后 output 含 result.exec_id/exit_code，steps 含 tool.skill.python.run。"""
    runner = TaskRunner()
    run = MagicMock()
    run.input_json = {
        "conversation_id": "conv-1",
        "language": "python",
        "code": "print(1)",
        "settings_snapshot": {},  # 使 runner 走 build_catalog_from_settings
    }
    run.type = "run_code_snippet"
    run.id = "run-1"
    run.title = None

    exec_response = {
        "exec_id": "e_test123",
        "status": "SUCCEEDED",
        "exit_code": 0,
        "artifacts_dir": "projects/conv-1/artifacts/e_test123",
    }
    catalog, _ = _make_run_code_snippet_catalog(exec_response)
    try:
        with patch("worker.runner.build_catalog_from_settings", return_value=catalog):
            result = runner._handle_run_code_snippet(run, lambda: True)
    finally:
        catalog.close_providers()

    assert result.get("ok") is True
    assert "result" in result
    assert result["result"].get("exec_id") == "e_test123"
    assert result["result"].get("exit_code") == 0
    assert result["result"].get("status") == "SUCCEEDED"
    steps = result.get("steps", [])
    names = [s["name"] for s in steps]
    assert any("skill.python.run" in n for n in names)


def test_run_code_snippet_shell_invokes_shell_run():
    """run_code_snippet(language=shell, script=...) 调用 skill.shell.run。"""
    runner = TaskRunner()
    run = MagicMock()
    run.input_json = {
        "conversation_id": "c2",
        "language": "shell",
        "script": "echo hello",
        "settings_snapshot": {},
    }
    run.type = "run_code_snippet"
    run.id = "run-2"
    run.title = None

    catalog, client = _make_run_code_snippet_catalog({"exec_id": "e_shell", "status": "SUCCEEDED", "exit_code": 0})
    try:
        with patch("worker.runner.build_catalog_from_settings", return_value=catalog):
            result = runner._handle_run_code_snippet(run, lambda: True)
    finally:
        catalog.close_providers()

    assert result.get("ok") is True
    assert result["result"].get("exec_id") == "e_shell"
    body = client.post.call_args[1].get("json", {})
    assert body.get("script") == "echo hello"
    assert body.get("project_id") == "c2"


def test_run_code_snippet_missing_conversation_id_raises():
    """run_code_snippet 缺少 conversation_id 时抛出 ValueError。"""
    runner = TaskRunner()
    run = MagicMock()
    run.input_json = {"language": "python", "code": "print(1)"}
    run.type = "run_code_snippet"

    with pytest.raises(ValueError, match="conversation_id"):
        runner._handle_run_code_snippet(run, lambda: True)


def test_execute_dispatches_run_code_snippet():
    """execute() 当 run.type=run_code_snippet 时派发到 _handle_run_code_snippet。"""
    runner = TaskRunner()
    run = MagicMock()
    run.type = "run_code_snippet"
    run.input_json = {"conversation_id": "c1", "language": "python", "code": "1+1", "settings_snapshot": {}}
    run.id = "r1"
    run.title = None

    catalog, _ = _make_run_code_snippet_catalog({"exec_id": "e1", "status": "SUCCEEDED", "exit_code": 0})
    try:
        with patch("worker.runner.build_catalog_from_settings", return_value=catalog):
            result = runner.execute(run, MagicMock(), MagicMock(), lambda: True)
    finally:
        catalog.close_providers()

    assert "ok" in result
    assert result.get("ok") is True
