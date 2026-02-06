"""防线：所有任务 output 必须包含 version/task_type/trace_id/steps/artifacts（测试层）。"""

from unittest.mock import Mock, patch

import pytest

from protocol.run_constants import is_valid_trace_id

from agent_worker.llm.stub import StubLLM
from worker.db_models import MessageRole
from worker.runner import TaskRunner
from worker.tools.catalog import ToolCatalog
from worker.tools.provider import BuiltinProvider, StubProvider
from worker.tools.skills_provider import SkillsProvider

# 与 core-api DEFAULT_ALLOWED_RUN_TYPES 对齐，至少包含已迁移到 task_result_v0 的类型
ALLOWED_RUN_TYPES = [
    "sleep",
    "summarize_conversation",
    "research_report",
    "run_code_snippet",
    "edit_docs_propose",
    "edit_docs_apply",
    "edit_docs_cancel",
]


def _assert_task_result_v0_schema(output: dict, task_type: str) -> None:
    """断言 output 符合 task_result_v0：version、task_type、trace_id、steps、artifacts。"""
    assert output.get("version") == "task_result_v0", f"{task_type}: missing version"
    assert output.get("task_type") == task_type, f"{task_type}: task_type mismatch"
    trace_id = output.get("trace_id")
    assert trace_id is not None and is_valid_trace_id(trace_id), f"{task_type}: invalid trace_id"
    steps = output.get("steps")
    assert isinstance(steps, list), f"{task_type}: steps must be list"
    artifacts = output.get("artifacts")
    assert isinstance(artifacts, dict), f"{task_type}: artifacts must be dict"


def _make_mock_db_with_messages(messages_list):
    db = Mock()
    chain = (
        db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.limit.return_value
    )
    chain.all.return_value = messages_list
    return db


def test_sleep_output_has_schema():
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"seconds": 0, "trace_id": "a" * 32}
    result = runner._handle_sleep(run, lambda: True)
    _assert_task_result_v0_schema(result, "sleep")


def test_summarize_conversation_output_has_schema():
    runner = TaskRunner()
    runner._build_memory_client = lambda: None
    run = Mock()
    run.input_json = {"conversation_id": "c1", "max_messages": 20, "trace_id": "b" * 32}
    msg = Mock(role=MessageRole.USER, content="hi")
    db = _make_mock_db_with_messages([msg])
    result = runner._handle_summarize_conversation(run, db, StubLLM(), lambda: True)
    _assert_task_result_v0_schema(result, "summarize_conversation")


def test_research_report_output_has_schema():
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "q", "trace_id": "c" * 32}
    result = runner._handle_research_report(run, lambda: True)
    _assert_task_result_v0_schema(result, "research_report")


def test_research_report_tool_fail_output_has_schema():
    """工具失败路径也返回完整 schema，便于可诊断。"""
    from worker.tools import ToolRuntime
    from worker.tools.catalog import ToolCatalog
    from worker.tools.provider import FailingProvider

    catalog = ToolCatalog(preferred_provider_order=["builtin"])
    catalog.register_provider("builtin", FailingProvider())
    runtime = ToolRuntime(catalog=catalog)
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"query": "x", "trace_id": "d" * 32}
    result = runner._handle_research_report(run, lambda: True, runtime=runtime)
    assert result.get("ok") is False
    _assert_task_result_v0_schema(result, "research_report")


def test_edit_docs_propose_output_has_schema():
    runner = TaskRunner()
    run = Mock()
    run.input_json = {"target_path": "/sandbox/f.txt", "trace_id": "e" * 32}
    result = runner._handle_edit_docs_propose(run, lambda: True)
    _assert_task_result_v0_schema(result, "edit_docs_propose")


def test_edit_docs_apply_output_has_schema():
    runner = TaskRunner()
    parent_run = Mock()
    parent_run.id = "parent-1"
    full_id = "f" * 64
    parent_run.output_json = {
        "artifacts": {"diff": "--- a\n+++ b\n", "patch_id": full_id, "files": ["f"]},
    }
    run = Mock()
    run.input_json = {"parent_run_id": "parent-1", "patch_id": full_id[:16]}
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = parent_run
    result = runner._handle_edit_docs_apply(run, db, lambda: True)
    _assert_task_result_v0_schema(result, "edit_docs_apply")


def test_edit_docs_cancel_output_has_schema():
    runner = TaskRunner()
    parent_run = Mock()
    parent_run.id = "parent-2"
    parent_run.output_json = {
        "artifacts": {"patch_id": "a" * 64, "diff": "--- a\n+++ b\n", "files": ["f"]},
    }
    run = Mock()
    run.input_json = {"parent_run_id": "parent-2", "patch_id": "a" * 16}
    db = Mock()
    db.query.return_value.filter.return_value.first.return_value = parent_run
    result = runner._handle_edit_docs_cancel(run, db, lambda: True)
    _assert_task_result_v0_schema(result, "edit_docs_cancel")


def test_run_code_snippet_output_has_schema():
    """run_code_snippet 的 output 符合 task_result_v0。"""
    runner = TaskRunner()
    run = Mock()
    run.input_json = {
        "conversation_id": "c1",
        "language": "python",
        "code": "print(1)",
        "settings_snapshot": {},
    }
    run.type = "run_code_snippet"
    run.id = "r1"
    run.title = None
    client = Mock()
    client.get.return_value.status_code = 200
    client.get.return_value.json.return_value = [
        {"id": "python.run", "name": "Run Python", "interface": {"inputs": {}}, "limits": {}},
    ]
    client.post.return_value.status_code = 200
    client.post.return_value.json.return_value = {"exec_id": "e1", "status": "SUCCEEDED", "exit_code": 0}
    catalog = ToolCatalog(preferred_provider_order=["skills", "builtin", "stub"])
    catalog.register_provider("skills", SkillsProvider(base_url="http://x", client=client))
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("stub", StubProvider())
    try:
        with patch("worker.runner.build_catalog_from_settings", return_value=catalog):
            result = runner._handle_run_code_snippet(run, lambda: True)
    finally:
        catalog.close_providers()
    _assert_task_result_v0_schema(result, "run_code_snippet")


def test_all_allowed_run_types_have_schema_test():
    """确保 ALLOWED_RUN_TYPES 中每类都有对应的 schema 断言（本文件内通过各 test_*_output_has_schema 覆盖）。"""
    covered = {
        "sleep",
        "summarize_conversation",
        "research_report",
        "run_code_snippet",
        "edit_docs_propose",
        "edit_docs_apply",
        "edit_docs_cancel",
    }
    for t in ALLOWED_RUN_TYPES:
        assert t in covered, f"ALLOWED_RUN_TYPES has {t} but no schema test; add test_*_output_has_schema"
