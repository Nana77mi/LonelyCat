import asyncio

import pytest

from runtime.policy import PolicyDenied, PolicyEngine
from runtime.tool_runner import ToolNotFound, ToolRunner


def test_policy_default_deny() -> None:
    async def run_test() -> None:
        policy = PolicyEngine()
        runner = ToolRunner(policy)
        runner.register("echo", lambda args, ctx: {"content": args["x"]})

        with pytest.raises(PolicyDenied):
            await runner.run("echo", {"x": "hi"}, {"session_id": "s"})

    asyncio.run(run_test())


def test_policy_allowlist_permits() -> None:
    async def run_test() -> None:
        policy = PolicyEngine(allow={"echo": True})
        runner = ToolRunner(policy)
        runner.register("echo", lambda args, ctx: {"content": args["x"]})

        result = await runner.run("echo", {"x": "hi"}, {"session_id": "s"})

        assert result == {"content": "hi"}

    asyncio.run(run_test())


def test_tool_not_found() -> None:
    async def run_test() -> None:
        policy = PolicyEngine(allow={"missing": True})
        runner = ToolRunner(policy)

        with pytest.raises(ToolNotFound):
            await runner.run("missing", {}, {"session_id": "s"})

    asyncio.run(run_test())


def test_async_tool_works() -> None:
    async def run_test() -> None:
        policy = PolicyEngine(allow={"async_tool": True})
        runner = ToolRunner(policy)

        async def async_tool(args, ctx):
            await asyncio.sleep(0)
            return {"ok": True}

        runner.register("async_tool", async_tool)

        result = await runner.run("async_tool", {}, {"session_id": "s"})

        assert result == {"ok": True}

    asyncio.run(run_test())
