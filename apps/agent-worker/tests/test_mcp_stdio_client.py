"""Tests for MCPStdioClient: list_tools, call_tool, timeout, close（Phase 2.2 v0.1）."""

from __future__ import annotations

import os
import sys

import pytest

# Path to echo server fixture (run from apps/agent-worker or repo root)
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ECHO_SERVER_SCRIPT = os.path.join(TESTS_DIR, "fixtures", "mcp_echo_server.py")


def _echo_server_cmd():
    return [sys.executable, ECHO_SERVER_SCRIPT]


def test_list_tools_returns_tools():
    """启动 echo server 后 list_tools 返回工具列表。"""
    from worker.tools.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(cmd=_echo_server_cmd(), cwd=None, env=None)
    try:
        tools = client.list_tools(timeout_ms=5000)
        assert isinstance(tools, list)
        assert len(tools) >= 1
        names = [t.get("name") for t in tools]
        assert "ping" in names
        assert "echo" in names
        for t in tools:
            assert "name" in t
            assert "inputSchema" in t
    finally:
        client.close()


def test_call_tool_returns_dict():
    """call_tool 返回 dict（content 或 result）。"""
    from worker.tools.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(cmd=_echo_server_cmd(), cwd=None, env=None)
    try:
        result = client.call_tool("ping", {}, timeout_ms=5000)
        assert isinstance(result, dict)
        assert "content" in result or "result" in result or "text" in result
    finally:
        client.close()


def test_call_tool_timeout_raises_mcp_timeout_error():
    """call_tool 超时抛 MCPTimeoutError(code=Timeout)。"""
    from worker.tools.mcp_errors import MCPTimeoutError
    from worker.tools.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(cmd=_echo_server_cmd(), cwd=None, env=None)
    try:
        with pytest.raises(MCPTimeoutError) as exc_info:
            client.call_tool("echo", {"delay_sec": 2}, timeout_ms=300)
        assert exc_info.value.code == "Timeout"
    finally:
        client.close()


def test_close_idempotent():
    """close() 可多次调用不报错。"""
    from worker.tools.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(cmd=_echo_server_cmd(), cwd=None, env=None)
    client.list_tools(timeout_ms=2000)
    client.close()
    client.close()


def test_after_close_list_tools_raises():
    """close 后再 list_tools 抛 MCPConnectionError 或类似。"""
    from worker.tools.mcp_errors import MCPConnectionError
    from worker.tools.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(cmd=_echo_server_cmd(), cwd=None, env=None)
    client.list_tools(timeout_ms=2000)
    client.close()
    with pytest.raises((MCPConnectionError, ConnectionError, ValueError, RuntimeError), match="closed|connection|Connection"):
        client.list_tools(timeout_ms=1000)


def test_after_close_call_tool_raises():
    """close 后再 call_tool 抛 MCPConnectionError 或类似。"""
    from worker.tools.mcp_errors import MCPConnectionError
    from worker.tools.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(cmd=_echo_server_cmd(), cwd=None, env=None)
    client.list_tools(timeout_ms=2000)
    client.close()
    with pytest.raises((MCPConnectionError, ConnectionError, ValueError, RuntimeError), match="closed|connection|Connection"):
        client.call_tool("ping", {}, timeout_ms=1000)


def test_spawn_failed_raises():
    """不存在的可执行路径启动失败抛 MCPSpawnFailedError。"""
    from worker.tools.mcp_errors import MCPSpawnFailedError
    from worker.tools.mcp_stdio_client import MCPStdioClient

    client = MCPStdioClient(cmd=["nonexistent_executable_xyz_123"], cwd=None, env=None)
    try:
        with pytest.raises(MCPSpawnFailedError) as exc_info:
            client.list_tools(timeout_ms=2000)
        assert exc_info.value.code == "SpawnFailed"
    finally:
        client.close()
