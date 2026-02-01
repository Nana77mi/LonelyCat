import asyncio
from typing import Any, Dict, List

from runtime.agent_loop import AgentLoop, TranscriptStore
from runtime.lane_queue import LaneQueue


class StubLLM:
    def __init__(self) -> None:
        self.calls: List[List[Dict[str, Any]]] = []
        self._step = 0

    async def generate(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.calls.append(messages)
        if self._step == 0:
            self._step += 1
            return {"type": "tool_call", "name": "search", "arguments": {"q": "cats"}}
        tool_result = next(
            item for item in messages if item.get("type") == "tool_result"
        )
        return {"type": "final", "content": f"result is {tool_result['content']}"}


class StubToolRunner:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def run(self, name: str, arguments: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"name": name, "arguments": arguments, "ctx": ctx})
        return {"content": "MEOW"}


def test_agent_loop_tool_call_path() -> None:
    async def run_test() -> None:
        llm = StubLLM()
        tools = StubToolRunner()
        transcript = TranscriptStore()
        queue = LaneQueue(max_concurrency=2)
        loop = AgentLoop(llm=llm, tools=tools, transcript=transcript, queue=queue)

        result = await loop.handle("s1", "hello")

        assert result == "result is MEOW"
        assert await transcript.get("s1") == [
            {"role": "user", "content": "hello"},
            {"type": "tool_call", "name": "search", "arguments": {"q": "cats"}},
            {"type": "tool_result", "name": "search", "content": "MEOW"},
            {"role": "assistant", "content": "result is MEOW"},
        ]
        assert len(tools.calls) == 1

    asyncio.run(run_test())


def test_agent_loop_direct_final_path() -> None:
    async def run_test() -> None:
        class FinalLLM:
            async def generate(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
                return {"type": "final", "content": "done"}

        class NoopTools:
            def __init__(self) -> None:
                self.called = False

            async def run(self, name: str, arguments: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
                self.called = True
                return {"content": "unused"}

        llm = FinalLLM()
        tools = NoopTools()
        transcript = TranscriptStore()
        queue = LaneQueue(max_concurrency=2)
        loop = AgentLoop(llm=llm, tools=tools, transcript=transcript, queue=queue)

        result = await loop.handle("s2", "hello")

        assert result == "done"
        assert await transcript.get("s2") == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "done"},
        ]
        assert tools.called is False

    asyncio.run(run_test())


def test_agent_loop_serializes_same_session() -> None:
    async def run_test() -> None:
        class SlowLLM:
            def __init__(self) -> None:
                self.running = 0
                self.peak_running = 0

            async def generate(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
                self.running += 1
                self.peak_running = max(self.peak_running, self.running)
                await asyncio.sleep(0.05)
                self.running -= 1
                return {"type": "final", "content": "ok"}

        class NoopTools:
            async def run(self, name: str, arguments: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
                return {"content": "unused"}

        llm = SlowLLM()
        tools = NoopTools()
        transcript = TranscriptStore()
        queue = LaneQueue(max_concurrency=2)
        loop = AgentLoop(llm=llm, tools=tools, transcript=transcript, queue=queue)

        await asyncio.gather(
            loop.handle("same", "hello"),
            loop.handle("same", "hi"),
        )

        assert llm.peak_running == 1
        assert await transcript.get("same") == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "ok"},
        ]

    asyncio.run(run_test())
