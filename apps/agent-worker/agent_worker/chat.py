from __future__ import annotations

import os
import sys
from typing import Sequence

from agent_worker.llm import BaseLLM, build_llm_from_env
from agent_worker.memory_client import MemoryClient
from agent_worker.memory_gate import MemoryGate
from agent_worker.persona import PersonaRegistry
from agent_worker.responder import Responder
from agent_worker.run import execute_decision


PERSONA_REGISTRY = PersonaRegistry.load_default()


class _DecideAdapter(BaseLLM):
    def __init__(self, llm: object) -> None:
        self._llm = llm

    def generate(self, prompt: str) -> str:
        return self._llm.decide(prompt)


def _coerce_llm(llm: object | None) -> BaseLLM:
    if llm is None:
        return build_llm_from_env()
    if hasattr(llm, "generate"):
        return llm  # type: ignore[return-value]
    if hasattr(llm, "decide"):
        return _DecideAdapter(llm)
    raise ValueError("LLM must implement generate(prompt)")


# chat() is the primary programmatic API.
# main() is a thin CLI wrapper and must not contain business logic.
def chat(
    user_message: str,
    persona_id: str | None = None,
    llm: BaseLLM | None = None,
    memory_client: MemoryClient | None = None,
) -> tuple[str, str]:
    memory_client = memory_client or MemoryClient()
    try:
        facts = memory_client.list_facts(subject="user", status="ACTIVE")
    except Exception:
        facts = []

    llm = _coerce_llm(llm)
    persona = PERSONA_REGISTRY.get(persona_id)

    responder = Responder(llm)
    gate = MemoryGate(llm)

    assistant_reply, _memory_hint = responder.reply(persona, user_message, facts)
    decision = gate.decide(user_message, facts)

    status = execute_decision(decision, memory_client, propose_source_note="chat")
    return assistant_reply, status


def main(argv: Sequence[str] | None = None, *, llm=None, memory_client=None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit('Usage: python -m agent_worker.chat "user message"')
    user_message = args[0]
    persona_id = os.getenv("AGENT_PERSONA")
    assistant_reply, status = chat(
        user_message,
        persona_id=persona_id,
        llm=llm,
        memory_client=memory_client,
    )
    print(assistant_reply)
    print(f"MEMORY: {status}")


if __name__ == "__main__":
    main()
