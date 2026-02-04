"""Tests for MCPProvider: namespace prefix, list_tools failure degradation, close (Phase 2.2)."""

from unittest.mock import Mock, patch
import json
import os
import sys

import pytest

from worker.tools.catalog import ToolCatalog, ToolMeta
from worker.tools.provider import BuiltinProvider, StubProvider

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ECHO_SERVER_SCRIPT = os.path.join(TESTS_DIR, "fixtures", "mcp_echo_server.py")


def _echo_server_cmd():
    return [sys.executable, ECHO_SERVER_SCRIPT]


# Mock MCP "client" used by MCPProvider when client= is passed (tests only).
# Interface: list_tools() -> list of dict with name, inputSchema; call_tool(name, args) -> dict.
class MockMCPClient:
    def __init__(self, tools=None, call_tool_result=None, list_tools_raises=False):
        self.tools = tools or [
            {"name": "search", "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}},
            {"name": "read_file", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}}},
        ]
        self.call_tool_result = call_tool_result or {"content": [{"type": "text", "text": "ok"}]}
        self.list_tools_raises = list_tools_raises
        self.call_tool_calls = []

    def list_tools(self):
        if self.list_tools_raises:
            raise RuntimeError("MCP connection failed")
        return self.tools

    def call_tool(self, name: str, arguments: dict):
        self.call_tool_calls.append((name, arguments))
        return self.call_tool_result


def test_mcp_provider_tool_names_have_prefix():
    """MCPProvider 注册到 Catalog 的工具名强制前缀 mcp.<server_name>.<tool_name>。"""
    from worker.tools.mcp_provider import MCPProvider

    client = MockMCPClient()
    provider = MCPProvider(server_name="test_server", provider_id="mcp_test", client=client)
    tools = provider.list_tools()
    assert len(tools) == 2
    names = [t.name for t in tools]
    assert "mcp.test_server.search" in names
    assert "mcp.test_server.read_file" in names
    assert all(t.provider_id == "mcp_test" for t in tools)
    assert all(t.capability_level == "L0" for t in tools)
    assert all(t.risk_level == "unknown" for t in tools)


def test_mcp_provider_list_tools_failure_returns_empty_and_logs():
    """list_tools 失败时：provider 仍可用，返回空列表，并打 mcp.list_tools.failed 日志。"""
    from worker.tools.mcp_provider import MCPProvider

    client = MockMCPClient(list_tools_raises=True)
    provider = MCPProvider(server_name="srv", provider_id="mcp_srv", client=client)
    with patch("worker.tools.mcp_provider.logger") as mock_log:
        tools = provider.list_tools()
    assert tools == []
    mock_log.warning.assert_called_once()
    # logger.warning("%s server_name=%s error=%s", MCP_LIST_TOOLS_FAILED, ...) -> args[0] is format, args[1] is stage
    call_args = mock_log.warning.call_args[0]
    msg_parts = " ".join(str(a) for a in call_args)
    assert "mcp.list_tools.failed" in msg_parts or "list_tools" in msg_parts.lower()


def test_mcp_provider_close_idempotent():
    """close() 可多次调用不报错。"""
    from worker.tools.mcp_provider import MCPProvider

    provider = MCPProvider(server_name="srv", provider_id="mcp_srv", client=MockMCPClient())
    provider.close()
    provider.close()


def test_mcp_provider_invoke_after_close_raises_provider_closed():
    """close() 后 invoke(...) 必须失败且 error.code 稳定为 ProviderClosed。"""
    from worker.tools.mcp_provider import MCPProvider, MCPProviderClosedError

    provider = MCPProvider(server_name="srv", provider_id="mcp_srv", client=MockMCPClient())
    provider.list_tools()
    provider.close()
    ctx = Mock()
    with pytest.raises(MCPProviderClosedError) as exc_info:
        provider.invoke("mcp.srv.search", {"q": "x"}, ctx)
    assert exc_info.value.code == "ProviderClosed"


def test_mcp_provider_invoke_strips_prefix_and_returns_result():
    """invoke 使用带前缀的 tool_name 时，向 MCP 传裸名；返回结果归一为 dict。"""
    from worker.tools.mcp_provider import MCPProvider

    client = MockMCPClient(call_tool_result={"content": [{"type": "text", "text": "hello"}]})
    provider = MCPProvider(server_name="test_server", provider_id="mcp_test", client=client)
    ctx = Mock()
    result = provider.invoke("mcp.test_server.search", {"q": "x"}, ctx, llm=None)
    assert isinstance(result, dict)
    assert client.call_tool_calls == [("search", {"q": "x"})]
    # 归一后应有 text 或 content 等便于 preview
    assert "content" in result or "text" in result


def test_mcp_provider_invoke_unknown_tool_raises():
    """invoke 传入非本 provider 的工具名（前缀不匹配或未知）应抛错。"""
    from worker.tools.mcp_provider import MCPProvider

    provider = MCPProvider(server_name="srv", provider_id="mcp_srv", client=MockMCPClient())
    ctx = Mock()
    with pytest.raises(ValueError, match="Unknown tool|not from this provider"):
        provider.invoke("web.search", {}, ctx)


def test_catalog_with_mcp_provider_list_tools_includes_mcp_tools():
    """Catalog 注册 MCPProvider 后，list_tools 聚合出带前缀的 MCP 工具。"""
    from worker.tools.mcp_provider import MCPProvider

    catalog = ToolCatalog(preferred_provider_order=["builtin", "mcp_test", "stub"])
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("mcp_test", MCPProvider(server_name="srv", provider_id="mcp_test", client=MockMCPClient()))
    catalog.register_provider("stub", StubProvider())
    all_tools = catalog.list_tools()
    names = [t.name for t in all_tools]
    assert "web.search" in names
    assert "mcp.srv.search" in names
    meta = catalog.get("mcp.srv.search")
    assert meta is not None
    assert meta.provider_id == "mcp_test"


def test_catalog_mcp_list_tools_failed_still_works():
    """MCP list_tools 失败时，Catalog 仍可正常解析 builtin/stub，不崩溃。"""
    from worker.tools.mcp_provider import MCPProvider

    catalog = ToolCatalog(preferred_provider_order=["mcp_fail", "builtin"])
    catalog.register_provider("mcp_fail", MCPProvider(server_name="f", provider_id="mcp_fail", client=MockMCPClient(list_tools_raises=True)))
    catalog.register_provider("builtin", BuiltinProvider())
    # mcp_fail 返回空列表，builtin 正常
    meta = catalog.get("web.search")
    assert meta is not None
    assert meta.provider_id == "builtin"


def test_catalog_close_providers_idempotent():
    """close_providers() 可多次调用不报错；关闭后 MCPProvider.list_tools 返回空。"""
    from worker.tools.mcp_provider import MCPProvider

    catalog = ToolCatalog(preferred_provider_order=["mcp_x", "builtin"])
    mcp = MCPProvider(server_name="x", provider_id="mcp_x", client=MockMCPClient())
    catalog.register_provider("mcp_x", mcp)
    catalog.register_provider("builtin", BuiltinProvider())
    assert len(mcp.list_tools()) == 2
    catalog.close_providers()
    catalog.close_providers()
    assert mcp.list_tools() == []


def test_mcp_provider_stdio_invoke_ping_step_and_preview():
    """集成：MCPProvider 用 stdio echo server，ToolRuntime.invoke(mcp.srv.ping) 落 step 且有 args/result preview。"""
    from worker.task_context import TaskContext
    from worker.tools import ToolRuntime
    from worker.tools.mcp_provider import MCPProvider

    catalog = ToolCatalog(preferred_provider_order=["builtin", "mcp_srv", "stub"])
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("mcp_srv", MCPProvider(server_name="srv", provider_id="mcp_srv", cmd=_echo_server_cmd(), cwd=None, env=None))
    catalog.register_provider("stub", StubProvider())
    runtime = ToolRuntime(catalog=catalog)
    run = Mock()
    run.input_json = {}
    ctx = TaskContext(run, "research_report")
    result = runtime.invoke(ctx, "mcp.srv.ping", {})
    assert isinstance(result, dict)
    assert "content" in result or "result" in result or "text" in result
    steps = ctx._steps
    assert len(steps) == 1
    assert steps[0]["name"] == "tool.mcp.srv.ping"
    assert steps[0]["ok"] is True
    assert "args_preview" in steps[0]["meta"]
    assert "result_preview" in steps[0]["meta"]
    assert steps[0]["meta"].get("provider_id") == "mcp_srv"
    catalog.close_providers()


# --- 2.2 v0.2 多 MCP server ---


def test_catalog_list_tools_multiple_mcp_servers():
    """Catalog 注册多个 MCPProvider 时，list_tools 含多 server 工具；preferred_provider_order 可调。"""
    from worker.tools.mcp_provider import MCPProvider

    srv1_tools = [{"name": "ping", "inputSchema": {"type": "object"}}, {"name": "echo", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}}}]
    srv2_tools = [{"name": "search", "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}}, {"name": "read_file", "inputSchema": {"type": "object"}}]
    catalog = ToolCatalog(preferred_provider_order=["builtin", "mcp_srv1", "mcp_srv2", "stub"])
    catalog.register_provider("builtin", BuiltinProvider())
    catalog.register_provider("mcp_srv1", MCPProvider(server_name="srv1", provider_id="mcp_srv1", client=MockMCPClient(tools=srv1_tools)))
    catalog.register_provider("mcp_srv2", MCPProvider(server_name="srv2", provider_id="mcp_srv2", client=MockMCPClient(tools=srv2_tools)))
    catalog.register_provider("stub", StubProvider())
    all_tools = catalog.list_tools()
    names = [t.name for t in all_tools]
    assert "mcp.srv1.ping" in names
    assert "mcp.srv1.echo" in names
    assert "mcp.srv2.search" in names
    assert "mcp.srv2.read_file" in names
    assert catalog.get("mcp.srv1.ping").provider_id == "mcp_srv1"
    assert catalog.get("mcp.srv2.search").provider_id == "mcp_srv2"
    catalog.set_preferred_provider_order(["mcp_srv2", "mcp_srv1", "builtin", "stub"])
    order = catalog._preferred_provider_order
    assert "mcp_srv1" in order and "mcp_srv2" in order
    catalog.close_providers()


def test_mcp_servers_from_env_parsing():
    """MCP_SERVERS_JSON 解析：未设置返回 None；有效 JSON 返回 list；无效 JSON 返回 None。"""
    from worker.tools import catalog as catalog_mod

    with patch.dict(os.environ, {}, clear=False):
        if "MCP_SERVERS_JSON" in os.environ:
            del os.environ["MCP_SERVERS_JSON"]
        servers = catalog_mod._mcp_servers_from_env()
    assert servers is None

    with patch.dict(os.environ, {"MCP_SERVERS_JSON": "[]"}, clear=False):
        servers = catalog_mod._mcp_servers_from_env()
    assert servers == []

    with patch.dict(os.environ, {"MCP_SERVERS_JSON": "[{]"}, clear=False):
        servers = catalog_mod._mcp_servers_from_env()
    assert servers is None

    with patch.dict(os.environ, {"MCP_SERVERS_JSON": json.dumps([{"name": "srv1", "cmd": ["python", "-c", "1"], "cwd": None}])}, clear=False):
        servers = catalog_mod._mcp_servers_from_env()
    assert servers is not None
    assert len(servers) == 1
    assert servers[0]["name"] == "srv1"
    assert servers[0]["cmd"] == ["python", "-c", "1"]


def test_default_catalog_factory_with_mcp_servers_json_registers_multiple_servers():
    """get_default_catalog 由 _default_catalog_factory 构建；MCP_SERVERS_JSON 设置时注册多个 MCP provider。"""
    from worker.tools import catalog as catalog_mod

    servers_json = json.dumps([
        {"name": "srv1", "cmd": _echo_server_cmd(), "cwd": None},
        {"name": "srv2", "cmd": _echo_server_cmd(), "cwd": None},
    ])
    with patch.dict(os.environ, {"MCP_SERVERS_JSON": servers_json}, clear=False):
        catalog = catalog_mod._default_catalog_factory()
    try:
        order = catalog._preferred_provider_order
        assert "mcp_srv1" in order
        assert "mcp_srv2" in order
        all_tools = catalog.list_tools()
        names = [t.name for t in all_tools]
        assert "mcp.srv1.ping" in names
        assert "mcp.srv1.echo" in names
        assert "mcp.srv2.ping" in names
        assert "mcp.srv2.echo" in names
    finally:
        catalog.close_providers()


# --- 2.2 v0.2 加固：非法 JSON 告警、name 校验/去重、cmd 非空 ---


def test_mcp_servers_from_env_invalid_json_logs_warning():
    """非法 MCP_SERVERS_JSON 时返回 None 并打 warning（含截断原始串），避免静默回退。"""
    from worker.tools import catalog as catalog_mod

    with patch("worker.tools.catalog.logger") as mock_log:
        with patch.dict(os.environ, {"MCP_SERVERS_JSON": "[{invalid"}, clear=False):
            servers = catalog_mod._mcp_servers_from_env()
    assert servers is None
    assert mock_log.warning.called
    call_msg = " ".join(str(a) for a in mock_log.warning.call_args[0])
    assert "MCP_SERVERS_JSON" in call_msg or "json" in call_msg.lower()
    # 截断后的 raw 应在日志中
    assert "[{invalid" in call_msg or "invalid" in call_msg


def test_mcp_servers_from_env_invalid_name_filters():
    """name 仅允许 [a-z0-9_]+；非法 name 的项被跳过并打 warning，其余保留。"""
    from worker.tools import catalog as catalog_mod

    with patch("worker.tools.catalog.logger") as mock_log:
        with patch.dict(os.environ, {
            "MCP_SERVERS_JSON": json.dumps([
                {"name": "valid_srv", "cmd": ["python", "-c", "1"]},
                {"name": "bad-srv", "cmd": ["python", "-c", "2"]},
                {"name": "Srv2", "cmd": ["python", "-c", "3"]},
                {"name": "srv3", "cmd": ["python", "-c", "4"]},
            ]),
        }, clear=False):
            servers = catalog_mod._mcp_servers_from_env()
    assert servers is not None
    names = [s["name"] for s in servers]
    assert "valid_srv" in names
    assert "srv3" in names
    assert "bad-srv" not in names
    assert "Srv2" not in names
    assert mock_log.warning.call_count >= 2


def test_mcp_servers_from_env_duplicate_name_keeps_first_and_warns():
    """重复 name 时保留第一个，后续跳过并打 warning。"""
    from worker.tools import catalog as catalog_mod

    with patch("worker.tools.catalog.logger") as mock_log:
        with patch.dict(os.environ, {
            "MCP_SERVERS_JSON": json.dumps([
                {"name": "srv1", "cmd": ["python", "-c", "1"]},
                {"name": "srv1", "cmd": ["python", "-c", "2"]},
                {"name": "srv2", "cmd": ["python", "-c", "3"]},
            ]),
        }, clear=False):
            servers = catalog_mod._mcp_servers_from_env()
    assert servers is not None
    names = [s["name"] for s in servers]
    assert names == ["srv1", "srv2"]
    assert any("duplicate" in " ".join(str(a) for a in c[0]).lower() for c in mock_log.warning.call_args_list)


def test_mcp_servers_from_env_empty_cmd_skips_item_and_warns():
    """cmd 为空列表或无效时跳过该项并 warning，其余 server 仍返回。"""
    from worker.tools import catalog as catalog_mod

    with patch("worker.tools.catalog.logger") as mock_log:
        with patch.dict(os.environ, {
            "MCP_SERVERS_JSON": json.dumps([
                {"name": "srv_ok", "cmd": ["python", "-c", "1"]},
                {"name": "srv_empty", "cmd": []},
                {"name": "srv_ok2", "cmd": ["python", "-c", "2"]},
            ]),
        }, clear=False):
            servers = catalog_mod._mcp_servers_from_env()
    assert servers is not None
    names = [s["name"] for s in servers]
    assert "srv_ok" in names
    assert "srv_ok2" in names
    assert "srv_empty" not in names
    assert mock_log.warning.call_count >= 1
