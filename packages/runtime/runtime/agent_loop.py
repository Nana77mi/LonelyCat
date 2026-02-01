from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol

from runtime.lane_queue import LaneQueue


class LLMProtocol(Protocol):
    async def generate(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        ...


class ToolRunnerProtocol(Protocol):
    async def run(self, name: str, arguments: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        ...


@dataclass
class TranscriptStore:
    """In-memory transcript storage.

    Structure contract:
    - User/assistant messages: {"role": "user"|"assistant", "content": str}
    - Tool call: {"type": "tool_call", "name": str, "arguments": dict}
    - Tool result: {"type": "tool_result", "name": str, "content": str|None}

    Concurrency semantics: guarded by an asyncio.Lock to keep per-session append
    order deterministic when accessed concurrently.
    """

    _items: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def append(self, session_id: str, item: Dict[str, Any]) -> None:
        async with self._lock:
            self._items.setdefault(session_id, []).append(item)

    async def get(self, session_id: str) -> List[Dict[str, Any]]:
        async with self._lock:
            return list(self._items.get(session_id, []))


class AgentLoop:
    def __init__(
        self,
        llm: LLMProtocol,
        tools: ToolRunnerProtocol,
        transcript: TranscriptStore,
        queue: LaneQueue,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._transcript = transcript
        self._queue = queue

    async def handle(self, session_id: str, user_text: str) -> str:
        async def run_loop() -> str:
            messages: List[Dict[str, Any]] = []
            user_event = {"role": "user", "content": user_text}
            await self._transcript.append(session_id, user_event)
            messages.append(user_event)

            first = await self._llm.generate(messages)
            if first.get("type") == "final":
                assistant_event = {"role": "assistant", "content": first["content"]}
                await self._transcript.append(session_id, assistant_event)
                return first["content"]

            if first.get("type") != "tool_call":
                raise ValueError("Unexpected LLM response")

            tool_call_event = {
                "type": "tool_call",
                "name": first["name"],
                "arguments": first.get("arguments", {}),
            }
            await self._transcript.append(session_id, tool_call_event)
            messages.append(tool_call_event)

            tool_result = await self._tools.run(
                first["name"], first.get("arguments", {}), {"session_id": session_id}
            )
            tool_result_event = {
                "type": "tool_result",
                "name": first["name"],
                "content": tool_result.get("content"),
            }
            await self._transcript.append(session_id, tool_result_event)
            messages.append(tool_result_event)

            second = await self._llm.generate(messages)
            if second.get("type") != "final":
                raise ValueError("Unexpected LLM response")

            assistant_event = {"role": "assistant", "content": second["content"]}
            await self._transcript.append(session_id, assistant_event)
            return second["content"]

        return await self._queue.submit(session_id, run_loop)
