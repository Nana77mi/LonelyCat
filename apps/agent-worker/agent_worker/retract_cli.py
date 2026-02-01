from __future__ import annotations

import sys
from typing import Sequence

from agent_worker.memory_client import MemoryClient
from agent_worker.retract_agent import RetractGate, RetractRequest, build_llm


def _format_retracted(record_id: str, request: RetractRequest) -> str:
    return (
        "RETRACTED "
        f"{record_id} "
        f"predicate={request.predicate} "
        f"object={request.object}"
    )


def _format_not_found(request: RetractRequest) -> str:
    return f"NOT_FOUND predicate={request.predicate} object={request.object}"


def main(argv: Sequence[str] | None = None, *, llm=None, memory_client=None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit("Usage: python -m agent_worker.retract_cli \"text\"")
    text = args[0]

    llm = llm or build_llm()
    gate = RetractGate(llm)
    request = gate.decide(text)
    if request is None:
        print("NO_ACTION")
        return

    memory_client = memory_client or MemoryClient()
    facts = memory_client.list_facts(subject=request.subject, status="ACTIVE")
    match = next(
        (
            record
            for record in facts
            if record.get("predicate") == request.predicate
            and record.get("object") == request.object
        ),
        None,
    )
    if not match:
        print(_format_not_found(request))
        return
    record_id = str(match.get("id"))
    memory_client.retract(record_id, request.reason)
    print(_format_retracted(record_id, request))


if __name__ == "__main__":
    main()
