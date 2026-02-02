from __future__ import annotations

import sys
from typing import Sequence

from agent_worker.fact_agent import FactProposal
from agent_worker.memory_client import MemoryClient
from agent_worker.update_agent import UpdateGate, UpdateRequest, build_llm


def _format_updated(old_id: str, proposal_id: str, request: UpdateRequest) -> str:
    return (
        "UPDATED "
        f"{old_id} -> {proposal_id} "
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
    # 构建 key（从 subject.predicate 转换为 key）
    key = f"{request.subject}.{request.predicate}" if request.subject != "user" else request.predicate
    facts = memory_client.list_facts(scope="global", status="active")
    match = next(
        (
            record
            for record in facts
            if record.get("key") == key
            and record.get("value") == request.old_object
        ),
        None,
    )
    if not match:
        print(_format_not_found(request))
        return
    old_id = str(match.get("id"))
    memory_client.revoke(old_id)
    proposal = FactProposal(
        subject=request.subject,
        predicate=request.predicate,
        object=request.new_object,
        confidence=request.confidence,
    )
    proposal_id = memory_client.propose(proposal, source_note="update")
    print(_format_updated(old_id, proposal_id, request))


if __name__ == "__main__":
    main()
