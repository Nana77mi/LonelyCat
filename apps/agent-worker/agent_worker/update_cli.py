from __future__ import annotations

import sys
from typing import Sequence

from agent_worker.fact_agent import FactProposal
from agent_worker.memory_client import MemoryClient
from agent_worker.update_agent import UpdateGate, UpdateRequest, build_llm


def _format_updated(old_id: str, new_id: str, request: UpdateRequest) -> str:
    return (
        "UPDATED "
        f"{old_id} -> {new_id} "
        f"predicate={request.predicate} "
        f"old={request.old_object} "
        f"new={request.new_object}"
    )


def _format_not_found(request: UpdateRequest) -> str:
    return f"NOT_FOUND_OLD predicate={request.predicate} old_object={request.old_object}"


def main(argv: Sequence[str] | None = None, *, llm=None, memory_client=None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit("Usage: python -m agent_worker.update_cli \"text\"")
    text = args[0]

    llm = llm or build_llm()
    gate = UpdateGate(llm)
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
            and record.get("object") == request.old_object
        ),
        None,
    )
    if not match:
        print(_format_not_found(request))
        return
    old_id = str(match.get("id"))
    memory_client.retract(old_id, request.reason)
    proposal = FactProposal(
        subject=request.subject,
        predicate=request.predicate,
        object=request.new_object,
        confidence=request.confidence,
    )
    new_id = memory_client.propose(proposal, source_note="update")
    print(_format_updated(old_id, new_id, request))


if __name__ == "__main__":
    main()
