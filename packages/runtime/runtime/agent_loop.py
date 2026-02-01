from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from runtime.lane_queue import LaneQueue
from runtime.memory_hook import MemoryHook
from memory.facts import FactCandidate, FactRecord, FactsStore


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
        memory_hook: Optional[MemoryHook] = None,
        facts: Optional[FactsStore] = None,
    ) -> None:
        self._llm = llm
        self._tools = tools
        self._transcript = transcript
        self._queue = queue
        self._memory_hook = memory_hook
        self._facts = facts

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
                await self._run_memory_hook(session_id)
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
            await self._run_memory_hook(session_id)
            return second["content"]

        return await self._queue.submit(session_id, run_loop)

    async def _run_memory_hook(self, session_id: str) -> None:
        if self._memory_hook is None or self._facts is None:
            return
        transcript = await self._transcript.get(session_id)
        candidates = await self._memory_hook.extract_candidates(session_id, transcript)
        if not candidates:
            return
        for candidate in candidates:
            await self._transcript.append(
                session_id,
                {
                    "type": "memory_candidate",
                    "candidate": self._candidate_summary(candidate),
                },
            )
        committed: List[FactRecord] = []
        for candidate in candidates:
            committed.append(await self._facts.propose(candidate))
        for record in committed:
            await self._transcript.append(
                session_id,
                {
                    "type": "memory_commit",
                    "record": self._record_summary(record),
                },
            )
        await self._memory_hook.on_committed(session_id, committed, transcript)

    def _candidate_summary(self, candidate: FactCandidate) -> Dict[str, Any]:
        return {
            "subject": candidate.subject,
            "predicate": candidate.predicate,
            "object": candidate.object,
            "confidence": candidate.confidence,
            "source": dict(candidate.source),
        }

    def _record_summary(self, record: FactRecord) -> Dict[str, Any]:
        return {
            "id": record.id,
            "subject": record.subject,
            "predicate": record.predicate,
            "object": record.object,
            "confidence": record.confidence,
            "source": dict(record.source),
        }
