"""PR5: SkillsProvider — list_tools ← GET /skills，invoke ← POST /skills/{id}/invoke（TDD）."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from worker.task_context import TaskContext
from worker.tools.catalog import CAPABILITY_L2, ToolCatalog
from worker.tools.provider import BuiltinProvider, StubProvider


def _mock_ctx(conversation_id: str | None = "conv-1"):
    run = MagicMock()
    run.input_json = {"conversation_id": conversation_id} if conversation_id else {}
    run.id = "run-1"
    return TaskContext(run, "test_task")


def test_skills_provider_list_tools_returns_skills_from_api():
    """SkillsProvider.list_tools() 调用 GET /skills，将每项映射为 ToolMeta name=skill.<id>。"""
    from worker.tools.skills_provider import SkillsProvider

    skills_payload = [
        {
            "id": "shell.run",
            "name": "Run Shell",
            "description": "Run shell in sandbox",
            "interface": {"inputs": {"type": "object", "properties": {"script": {"type": "string"}}, "required": ["script"]}},
            "limits": {"timeout_ms": 60000},
        },
        {
            "id": "python.run",
            "name": "Run Python",
            "description": "Run Python in sandbox",
            "interface": {"inputs": {"type": "object", "properties": {"code": {"type": "string"}}}},
            "limits": {},
        },
    ]
    mock_client = MagicMock()
    mock_client.get.return_value.status_code = 200
    mock_client.get.return_value.json.return_value = skills_payload

    provider = SkillsProvider(base_url="http://core:5173", client=mock_client)
    tools = provider.list_tools()

    names = [t.name for t in tools]
    assert "skill.shell.run" in names
    assert "skill.python.run" in names
    meta = next(t for t in tools if t.name == "skill.shell.run")
    assert meta.provider_id == "skills"
    assert meta.capability_level == CAPABILITY_L2
    assert "script" in str(meta.input_schema)


def test_skills_provider_list_tools_empty_when_api_fails():
    """GET /skills 失败或非 200 时 list_tools 返回空列表（降级，不抛）。"""
    from worker.tools.skills_provider import SkillsProvider

    mock_client = MagicMock()
    mock_client.get.return_value.status_code = 500

    provider = SkillsProvider(base_url="http://core:5173", client=mock_client)
    tools = provider.list_tools()

    assert tools == []


def test_skills_provider_invoke_calls_invoke_api():
    """invoke(skill.shell.run, {script, project_id}, ctx) 调用 POST /skills/shell.run/invoke。"""
    from worker.tools.skills_provider import SkillsProvider

    mock_client = MagicMock()
    mock_client.get.return_value.status_code = 200
    mock_client.get.return_value.json.return_value = [
        {"id": "shell.run", "name": "Run Shell", "interface": {"inputs": {}}, "limits": {}},
    ]
    mock_client.post.return_value.status_code = 200
    mock_client.post.return_value.json.return_value = {
        "exec_id": "e_abc",
        "status": "SUCCEEDED",
        "exit_code": 0,
        "artifacts_dir": "projects/conv-1/artifacts/e_abc",
    }

    provider = SkillsProvider(base_url="http://core:5173", client=mock_client)
    ctx = _mock_ctx("conv-1")
    result = provider.invoke("skill.shell.run", {"script": "echo hi", "project_id": "conv-1"}, ctx)

    assert result.get("exec_id") == "e_abc"
    assert result.get("status") == "SUCCEEDED"
    mock_client.post.assert_called_once()
    call_args = mock_client.post.call_args
    assert "/skills/shell.run/invoke" in call_args[0][0]
    body = call_args[1].get("json", {})
    assert body.get("project_id") == "conv-1"
    assert body.get("script") == "echo hi"


def test_skills_provider_invoke_uses_ctx_conversation_id_as_project_id_when_not_in_args():
    """invoke 时若 args 无 project_id，则用 ctx.run.input_json.conversation_id。"""
    from worker.tools.skills_provider import SkillsProvider

    mock_client = MagicMock()
    mock_client.get.return_value.status_code = 200
    mock_client.get.return_value.json.return_value = [
        {"id": "shell.run", "name": "Run Shell", "interface": {"inputs": {}}, "limits": {}},
    ]
    mock_client.post.return_value.status_code = 200
    mock_client.post.return_value.json.return_value = {"exec_id": "e_x", "status": "SUCCEEDED", "exit_code": 0}

    provider = SkillsProvider(base_url="http://core:5173", client=mock_client)
    ctx = _mock_ctx("my-conv")
    provider.invoke("skill.shell.run", {"script": "true"}, ctx)

    body = mock_client.post.call_args[1].get("json", {})
    assert body.get("project_id") == "my-conv"


def test_skills_provider_invoke_unknown_tool_raises():
    """invoke 未知工具名（非 skill.<id> 或 id 不在 list_tools 中）应抛 ValueError。"""
    from worker.tools.skills_provider import SkillsProvider

    mock_client = MagicMock()
    mock_client.get.return_value.status_code = 200
    mock_client.get.return_value.json.return_value = [{"id": "shell.run", "name": "Run Shell", "interface": {}, "limits": {}}]

    provider = SkillsProvider(base_url="http://core:5173", client=mock_client)
    ctx = _mock_ctx()

    with pytest.raises(ValueError, match="Unknown tool|skill"):
        provider.invoke("skill.unknown.foo", {"project_id": "p1"}, ctx)


def test_catalog_with_skills_provider_includes_skill_tools():
    """Catalog 注册 SkillsProvider 后，list_tools 含 skill.shell.run 等。"""
    from worker.tools.skills_provider import SkillsProvider

    mock_client = MagicMock()
    mock_client.get.return_value.status_code = 200
    mock_client.get.return_value.json.return_value = [
        {"id": "shell.run", "name": "Run Shell", "description": "x", "interface": {}, "limits": {}},
    ]

    catalog = ToolCatalog(preferred_provider_order=["skills", "builtin", "stub"])
    catalog.register_provider("skills", SkillsProvider(base_url="http://core:5173", client=mock_client))
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    names = [t.name for t in catalog.list_tools()]

    assert "skill.shell.run" in names
    assert catalog.get("skill.shell.run").provider_id == "skills"
