from agent_worker.llm import BaseLLM
from agent_worker.memory_gate import MemoryGate
from agent_worker.trace import TraceCollector, TraceLevel


class DummyLLM(BaseLLM):
    def __init__(self, response: str) -> None:
        self._response = response

    def generate(self, prompt: str) -> str:
        return self._response


def test_memory_gate_records_parse_error() -> None:
    gate = MemoryGate(DummyLLM("not json at all"))
    trace = TraceCollector(level=TraceLevel.BASIC, trace_id="trace-1")

    decision = gate.decide("hello", [], trace=trace)

    assert decision.action == "NO_ACTION"
    assert any(event.stage == "gate.parse_error" for event in trace.events)
