from __future__ import annotations

from typing import Awaitable, Callable

from runtime.policy import PolicyDenied, PolicyEngine

ToolFn = Callable[[dict, dict], Awaitable[dict] | dict]


class ToolNotFound(Exception):
    pass


class ToolRunner:
    def __init__(self, policy: PolicyEngine) -> None:
        self._policy = policy
        self._tools: dict[str, ToolFn] = {}

    def register(self, name: str, fn: ToolFn) -> None:
        self._tools[name] = fn

    async def run(self, name: str, arguments: dict, ctx: dict) -> dict:
        if not self._policy.is_allowed(name, ctx):
            raise PolicyDenied(f"Tool '{name}' is not allowed")

        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFound(f"Tool '{name}' not registered")

        result = tool(arguments, ctx)
        if hasattr(result, "__await__"):
            result = await result

        return result
