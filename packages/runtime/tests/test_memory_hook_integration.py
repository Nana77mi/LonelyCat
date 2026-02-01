import asyncio
from typing import Any, Dict, List

from memory.facts import FactsStore
from runtime.agent_loop import AgentLoop, TranscriptStore
from runtime.lane_queue import LaneQueue
from runtime.memory_hook import RuleBasedMemoryHook
from runtime.policy import PolicyEngine
from runtime.tool_runner import ToolRunner


class StubLLM:
    def __init__(self) -> None:
        self.calls: List[List[Dict[str, Any]]] = []
        self._step = 0

    async def generate(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.calls.append(messages)
        if self._step == 0:
            self._step += 1
            return {"type": "tool_call", "name": "search", "arguments": {"q": "cats"}}
        tool_result = next(item for item in messages if item.get("type") == "tool_result")
        return {"type": "final", "content": f"result is {tool_result['content']}"}


def test_memory_hook_disabled_no_change() -> None:
    async def run_test() -> None:
        llm = StubLLM()
        policy = PolicyEngine(allow={"search": True})
        tools = ToolRunner(policy)
        tool_calls: List[Dict[str, Any]] = []

        async def stub_search(arguments: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
            tool_calls.append({"name": "search", "arguments": arguments, "ctx": ctx})
            return {"content": "MEOW"}

        tools.register("search", stub_search)
        transcript = TranscriptStore()
        queue = LaneQueue(max_concurrency=2)
        loop = AgentLoop(llm=llm, tools=tools, transcript=transcript, queue=queue)

        result = await loop.handle("s1", "我喜欢猫")

        assert result == "result is MEOW"
        events = await transcript.get("s1")
        assert [event.get("role") or event.get("type") for event in events] == [
            "user",
            "tool_call",
            "tool_result",
            "assistant",
        ]
        assert events[0]["content"] == "我喜欢猫"
        assert events[1]["name"] == "search"
        assert events[2]["content"] == "MEOW"
        assert events[3]["content"] == "result is MEOW"
        assert len(tool_calls) == 1

    asyncio.run(run_test())


def test_memory_hook_enabled_writes_facts_and_audit_events() -> None:
    async def run_test() -> None:
        class FinalLLM:
            async def generate(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
                return {"type": "final", "content": "ok"}

        llm = FinalLLM()
        tools = ToolRunner(PolicyEngine())
        transcript = TranscriptStore()
        queue = LaneQueue(max_concurrency=2)
        facts = FactsStore()
        hook = RuleBasedMemoryHook()
        loop = AgentLoop(
            llm=llm,
            tools=tools,
            transcript=transcript,
            queue=queue,
            memory_hook=hook,
            facts=facts,
        )

        result = await loop.handle("s2", "我喜欢猫")

        assert result == "ok"
        events = await transcript.get("s2")
        assert events[0]["role"] == "user"
        assert events[1]["role"] == "assistant"
        assert events[2]["type"] == "memory_candidate"
        assert events[3]["type"] == "memory_commit"
        candidate = events[2]["candidate"]
        record = events[3]["record"]
        assert candidate["predicate"] == "likes"
        assert candidate["object"] == "猫"
        assert candidate["source"]["session_id"] == "s2"
        assert record["predicate"] == "likes"
        assert record["object"] == "猫"
        assert "id" in record
        record = await facts.get_active("user", "likes")
        assert record is not None
        assert record.object == "猫"

    asyncio.run(run_test())


def test_memory_hook_supports_preferred_name() -> None:
    async def run_test() -> None:
        class FinalLLM:
            async def generate(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
                return {"type": "final", "content": "ok"}

        llm = FinalLLM()
        tools = ToolRunner(PolicyEngine())
        transcript = TranscriptStore()
        queue = LaneQueue(max_concurrency=2)
        facts = FactsStore()
        hook = RuleBasedMemoryHook()
        loop = AgentLoop(
            llm=llm,
            tools=tools,
            transcript=transcript,
            queue=queue,
            memory_hook=hook,
            facts=facts,
        )

        await loop.handle("s3", "叫我七海")

        record = await facts.get_active("user", "preferred_name")
        assert record is not None
        assert record.object == "七海"
        events = await transcript.get("s3")
        assert events[0]["role"] == "user"
        assert events[1]["role"] == "assistant"
        assert events[2]["type"] == "memory_candidate"
        assert events[3]["type"] == "memory_commit"
        assert events[2]["candidate"]["predicate"] == "preferred_name"
        assert events[2]["candidate"]["object"] == "七海"
        assert events[3]["record"]["predicate"] == "preferred_name"
        assert events[3]["record"]["object"] == "七海"
        assert "id" in events[3]["record"]

    asyncio.run(run_test())


def test_memory_hook_session_serialization() -> None:
    async def run_test() -> None:
        class SlowLLM:
            async def generate(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
                await asyncio.sleep(0.05)
                return {"type": "final", "content": "ok"}

        llm = SlowLLM()
        tools = ToolRunner(PolicyEngine())
        transcript = TranscriptStore()
        queue = LaneQueue(max_concurrency=2)
        facts = FactsStore()
        hook = RuleBasedMemoryHook()
        loop = AgentLoop(
            llm=llm,
            tools=tools,
            transcript=transcript,
            queue=queue,
            memory_hook=hook,
            facts=facts,
        )

        await asyncio.gather(
            loop.handle("same", "我喜欢猫"),
            loop.handle("same", "我喜欢狗"),
        )

        record = await facts.get_active("user", "likes")
        assert record is not None
        assert record.object == "狗"
        all_records = await facts.list_subject("user")
        assert len([item for item in all_records if item.predicate == "likes"]) == 2

        events = await transcript.get("same")
        assert [event.get("role") or event.get("type") for event in events] == [
            "user",
            "assistant",
            "memory_candidate",
            "memory_commit",
            "user",
            "assistant",
            "memory_candidate",
            "memory_commit",
        ]
        first_candidate_object = events[2]["candidate"]["object"]
        second_candidate_object = events[6]["candidate"]["object"]
        assert (first_candidate_object, second_candidate_object) == ("猫", "狗")
        assert events[1]["content"] == "ok"
        assert events[5]["content"] == "ok"

    asyncio.run(run_test())
