from __future__ import annotations

import json

from agent_worker.llm import BaseLLM
from agent_worker.router import (
    Decision,
    NoActionDecision,
    RetractDecision,
    UpdateDecision,
    parse_llm_output_with_reason,
)
from agent_worker.trace import TraceCollector

MEMORY_GATE_MARKER = "### MEMORY_GATE ###"
MEMORY_POLICY = """You must output exactly one JSON object and nothing else.
Do not output any extra characters, markdown, or code fences.

Schema examples:
{"action":"NO_ACTION"}
{"action":"PROPOSE","subject":"user","predicate":"likes","object":"cats","confidence":0.9}
{"action":"RETRACT","subject":"user","predicate":"likes","object":"cats","reason":"no longer true"}
{"action":"UPDATE","subject":"user","predicate":"likes","old_object":"cats","new_object":"dogs","confidence":0.8,"reason":"preference changed"}

You are a memory gatekeeper deciding whether to store, retract, or update a user fact.

Allowed to store:
- stable preferences (likes/dislikes, favorites, consistent habits)
- long-term goals
- names or nicknames ONLY when the user explicitly says “remember my name is …”
- commonly used settings

Do not store sensitive personal data (addresses, phone numbers, IDs, financial details, health or other sensitive privacy).
If uncertain, choose NO_ACTION.

Explicit trigger phrases (tend toward action when safe):
- “remember / 记住 / 请记住 / from now on”
- “I like / I love / I prefer / my favorite”
- “I don’t like anymore / I no longer / 改成 / 不再”
- “actually / correction / 纠正一下 / 不是…是…”

If the user negates a stored fact, RETRACT it.
If the user explicitly changes a fact, UPDATE it.
If a negate/change target does not match any active fact, output NO_ACTION.
"""
RETURN_GATE_JSON = "Return only JSON matching the router schema."


def build_prompt(
    policy_prompt: str,
    active_facts: list[dict],
    user_message: str,
) -> str:
    facts_json = json.dumps(active_facts, separators=(",", ":"))
    return (
        f"{MEMORY_GATE_MARKER}\n"
        f"{policy_prompt}\n"
        f"user_message: {user_message}\n"
        f"active_facts: {facts_json}\n"
        f"{RETURN_GATE_JSON}\n"
    )


def parse_gate_output(raw: str | None, trace: TraceCollector | None = None) -> Decision:
    if raw is None:
        return NoActionDecision()
    if not isinstance(raw, str):
        raw = str(raw)
    stripped = raw.strip()
    if not stripped:
        return NoActionDecision()
    if "assistant_reply" in stripped and "action" not in stripped:
        return NoActionDecision()
    decision, error = parse_llm_output_with_reason(stripped)
    if isinstance(decision, NoActionDecision) and error and trace:
        trace.record("gate.parse_error", error)
    return decision


class MemoryGate:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def decide(
        self,
        user_message: str,
        active_facts: list[dict],
        trace: TraceCollector | None = None,
    ) -> Decision:
        prompt = build_prompt(MEMORY_POLICY, active_facts, user_message)
        if trace:
            trace.record("gate.prompt", prompt)
        raw = self._llm.generate(prompt)
        if trace:
            trace.record("gate.response", str(raw))
        decision = parse_gate_output(raw, trace=trace)
        if isinstance(decision, (RetractDecision, UpdateDecision)):
            if not _has_matching_fact(decision, active_facts):
                if trace:
                    trace.record("gate.not_found", "NOT_FOUND")
                return NoActionDecision()
        return decision


def _has_matching_fact(decision: Decision, active_facts: list[dict]) -> bool:
    if isinstance(decision, RetractDecision):
        return any(
            fact.get("predicate") == decision.predicate
            and fact.get("object") == decision.object
            and fact.get("status", "ACTIVE") == "ACTIVE"
            for fact in active_facts
        )
    if isinstance(decision, UpdateDecision):
        return any(
            fact.get("predicate") == decision.predicate
            and fact.get("object") == decision.old_object
            and fact.get("status", "ACTIVE") == "ACTIVE"
            for fact in active_facts
        )
    return False
