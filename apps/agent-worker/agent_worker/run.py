from __future__ import annotations

import logging
import sys
from typing import Sequence

from agent_worker.fact_agent import FactProposal
from agent_worker.llm import BaseLLM, JsonOnlyLLMWrapper, build_gate_llm_from_env
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


def _coerce_llm(llm: object | None) -> BaseLLM:
    if llm is None:
        return build_gate_llm_from_env()
    if hasattr(llm, "generate"):
        if isinstance(llm, BaseLLM):
            return JsonOnlyLLMWrapper(llm)
        return JsonOnlyLLMWrapper(llm)  # type: ignore[return-value]
    raise ValueError("LLM must implement generate(prompt)")


def _format_proposed(proposal_id: str, decision: ProposeDecision) -> str:
    return (
        "PROPOSED "
        f"{proposal_id} "
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


def execute_decision(
    decision,
    memory_client: MemoryClient | None = None,
    *,
    propose_source_note: str = "mvp-1",
    update_source_note: str = "update",
    trace=None,
) -> str:
    if isinstance(decision, NoActionDecision):
        return "NO_ACTION"

    memory_client = memory_client or MemoryClient()
    if isinstance(decision, ProposeDecision):
        try:
            if trace:
                trace.record("memory.propose.start")
            proposal = FactProposal(
                subject=decision.subject,
                predicate=decision.predicate,
                object=decision.object,
                confidence=decision.confidence,
            )
            proposal_id = memory_client.propose(proposal, source_note=propose_source_note)
            if trace:
                trace.record("memory.propose.finish")
            return _format_proposed(proposal_id, decision)
        except Exception as exc:
            if trace:
                trace.record("memory.propose.error", str(exc))
            logging.exception("Memory propose failed")
            return "NO_ACTION"

    if isinstance(decision, RetractDecision):
        try:
            if trace:
                trace.record("memory.retract.start")
            # 构建 key（从 subject.predicate 转换为 key）
            key = f"{decision.subject}.{decision.predicate}" if decision.subject != "user" else decision.predicate
            facts = memory_client.list_facts(scope="global", status="active")
            match = next(
                (
                    record
                    for record in facts
                    if record.get("key") == key
                    and record.get("value") == decision.object
                ),
                None,
            )
            if not match:
                return _format_not_found_retract(decision)
            record_id = str(match.get("id"))
            memory_client.revoke(record_id)
            if trace:
                trace.record("memory.retract.finish")
            return _format_retracted(record_id, decision)
        except Exception as exc:
            if trace:
                trace.record("memory.retract.error", str(exc))
            logging.exception("Memory retract failed")
            return "NO_ACTION"

    if isinstance(decision, UpdateDecision):
        try:
            if trace:
                trace.record("memory.update.start")
            # 构建 key（从 subject.predicate 转换为 key）
            key = f"{decision.subject}.{decision.predicate}" if decision.subject != "user" else decision.predicate
            facts = memory_client.list_facts(scope="global", status="active")
            match = next(
                (
                    record
                    for record in facts
                    if record.get("key") == key
                    and record.get("value") == decision.old_object
                ),
                None,
            )
            if not match:
                return _format_not_found_update(decision)
            old_id = str(match.get("id"))
            memory_client.revoke(old_id)
            proposal = FactProposal(
                subject=decision.subject,
                predicate=decision.predicate,
                object=decision.new_object,
                confidence=decision.confidence,
            )
            new_id = memory_client.propose(proposal, source_note=update_source_note)
            if trace:
                trace.record("memory.update.finish")
            return _format_updated(old_id, new_id, decision)
        except Exception as exc:
            if trace:
                trace.record("memory.update.error", str(exc))
            logging.exception("Memory update failed")
            return "NO_ACTION"

    return "NO_ACTION"


def main(argv: Sequence[str] | None = None, *, llm=None, memory_client=None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit("Usage: python -m agent_worker.run \"text\"")
    text = args[0]

    llm = _coerce_llm(llm)
    try:
        raw_output = llm.generate(text)
        if not isinstance(raw_output, str):
            raw_output = str(raw_output)
        decision = parse_llm_output(raw_output)
        status = execute_decision(decision, memory_client)
    except Exception:
        status = "NO_ACTION"
    print(status)


if __name__ == "__main__":
    main()
