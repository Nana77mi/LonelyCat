from __future__ import annotations

import os
import sys
from typing import Sequence

from agent_worker.chat_flow import chat_flow
from agent_worker.config import ChatConfig
from agent_worker.llm import BaseLLM
from agent_worker.memory_client import MemoryClient


# chat() is the primary programmatic API.
# main() is a thin CLI wrapper and must not contain business logic.
def chat(
    user_message: str,
    persona_id: str | None = None,
    llm: BaseLLM | None = None,
    memory_client: MemoryClient | None = None,
) -> tuple[str, str]:
    result = chat_flow(
        user_message=user_message,
        persona_id=persona_id,
        llm=llm,
        memory_client=memory_client,
        config=ChatConfig.from_env(),
    )
    return result.assistant_reply, result.memory_status


def main(argv: Sequence[str] | None = None, *, llm=None, memory_client=None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit('Usage: python -m agent_worker.chat "user message"')
    user_message = args[0]
    config = ChatConfig.from_env()
    persona_id = os.getenv("AGENT_PERSONA") or config.persona_default
    result = chat_flow(
        user_message=user_message,
        persona_id=persona_id,
        llm=llm,
        memory_client=memory_client,
        config=config,
    )
    for line in result.trace_lines:
        print(line)
    assistant_reply = result.assistant_reply
    status = result.memory_status
    print(assistant_reply)
    print(f"MEMORY: {status}")


if __name__ == "__main__":
    main()
