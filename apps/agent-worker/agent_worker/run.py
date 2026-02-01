from __future__ import annotations

import os
import sys
from typing import Protocol, Sequence

from agent_worker.fact_agent import FactProposal
from agent_worker.memory_client import MemoryClient
from agent_worker.router import (
    NoActionDecision,
    ProposeDecision,
    RetractDecision,
    UpdateDecision,
    parse_llm_output,
)


PROMPT = """You are a gatekeeper deciding whether to store, retract, or update a user fact.
Respond with exactly: NO_ACTION
Or JSON with one of:
- PROPOSE { "action": "PROPOSE", "subject": "user", "predicate": "...", "object": "...", "confidence": 0.0-1.0 }
- RETRACT { "action": "RETRACT", "subject": "user", "predicate": "...", "object": "...", "reason": "..." }
- UPDATE { "action": "UPDATE", "subject": "user", "predicate": "...", "old_object": "...", "new_object": "...", "confidence": 0.0-1.0, "reason": "..." }
"""


class LLM(Protocol):
    def decide(self, text: str) -> str:
        raise NotImplementedError


class StubLLM:
    def decide(self, text: str) -> str:
        return "NO_ACTION"


def build_llm() -> LLM:
    mode = os.getenv("LONELYCAT_LLM_MODE", "stub").lower()
    if mode == "stub":
        return StubLLM()
    raise ValueError(f"Unsupported LLM mode: {mode}")


def _format_proposed(record_id: str, decision: ProposeDecision) -> str:
    return (
        "PROPOSED "
        f"{record_id} "
        f"subject={decision.subject} "
        f"predicate={decision.predicate} "
        f"object={decision.object}"
    )


def _format_retracted(record_id: str, decision: RetractDecision) -> str:
    return (
        "RETRACTED "
        f"{record_id} "
        f"predicate={decision.predicate} "
        f"object={decision.object}"
    )


def _format_not_found_retract(decision: RetractDecision) -> str:
    return f"NOT_FOUND predicate={decision.predicate} object={decision.object}"


def _format_updated(old_id: str, new_id: str, decision: UpdateDecision) -> str:
    return (
        "UPDATED "
        f"{old_id} -> {new_id} "
        f"predicate={decision.predicate} "
        f"old={decision.old_object} "
        f"new={decision.new_object}"
    )


def _format_not_found_update(decision: UpdateDecision) -> str:
    return f"NOT_FOUND_OLD predicate={decision.predicate} old_object={decision.old_object}"


def main(argv: Sequence[str] | None = None, *, llm=None, memory_client=None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit("Usage: python -m agent_worker.run \"text\"")
    text = args[0]

    llm = llm or build_llm()
    decision = parse_llm_output(llm.decide(text))
    if isinstance(decision, NoActionDecision):
        print("NO_ACTION")
        return

    memory_client = memory_client or MemoryClient()
    if isinstance(decision, ProposeDecision):
        proposal = FactProposal(
            subject=decision.subject,
            predicate=decision.predicate,
            object=decision.object,
            confidence=decision.confidence,
        )
        record_id = memory_client.propose(proposal, source_note="mvp-1")
        print(_format_proposed(record_id, decision))
        return

    if isinstance(decision, RetractDecision):
        facts = memory_client.list_facts(subject=decision.subject, status="ACTIVE")
        match = next(
            (
                record
                for record in facts
                if record.get("predicate") == decision.predicate
                and record.get("object") == decision.object
            ),
            None,
        )
        if not match:
            print(_format_not_found_retract(decision))
            return
        record_id = str(match.get("id"))
        memory_client.retract(record_id, decision.reason)
        print(_format_retracted(record_id, decision))
        return

    if isinstance(decision, UpdateDecision):
        facts = memory_client.list_facts(subject=decision.subject, status="ACTIVE")
        match = next(
            (
                record
                for record in facts
                if record.get("predicate") == decision.predicate
                and record.get("object") == decision.old_object
            ),
            None,
        )
        if not match:
            print(_format_not_found_update(decision))
            return
        old_id = str(match.get("id"))
        memory_client.retract(old_id, decision.reason)
        proposal = FactProposal(
            subject=decision.subject,
            predicate=decision.predicate,
            object=decision.new_object,
            confidence=decision.confidence,
        )
        new_id = memory_client.propose(proposal, source_note="update")
        print(_format_updated(old_id, new_id, decision))
        return

    print("NO_ACTION")


if __name__ == "__main__":
    main()
