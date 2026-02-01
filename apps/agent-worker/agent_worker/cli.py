from __future__ import annotations

import sys
from typing import Sequence

from agent_worker.fact_agent import FactGate, FactProposal, build_llm
from agent_worker.memory_client import MemoryClient


def _format_proposed(record_id: str, proposal: FactProposal) -> str:
    return (
        "PROPOSED "
        f"{record_id} "
        f"(subject={proposal.subject}, "
        f"predicate={proposal.predicate}, "
        f"object={proposal.object}, "
        f"confidence={proposal.confidence})"
    )


def main(argv: Sequence[str] | None = None, *, llm=None, memory_client=None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit("Usage: python -m agent_worker.cli \"text\"")
    text = args[0]

    llm = llm or build_llm()
    gate = FactGate(llm)
    proposal = gate.decide(text)
    if proposal is None:
        print("NO_FACT")
        return

    memory_client = memory_client or MemoryClient()
    record_id = memory_client.propose(proposal)
    print(_format_proposed(record_id, proposal))


if __name__ == "__main__":
    main()
