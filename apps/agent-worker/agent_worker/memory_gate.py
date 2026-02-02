from __future__ import annotations

import json

from agent_worker.llm import BaseLLM
from agent_worker.router import Decision, NoActionDecision, parse_llm_output

MEMORY_GATE_MARKER = "### MEMORY_GATE ###"
MEMORY_POLICY = """You are a memory gatekeeper deciding whether to store, retract, or update a user fact.
Only store long-term preferences, goals, or stable facts.
Do not store sensitive personal data (addresses, phone numbers, IDs, financial details).
If the user negates a stored fact, RETRACT it.
If the user explicitly changes a fact, UPDATE it.
If uncertain, choose NO_ACTION.
"""
RETURN_GATE_JSON = "Return only JSON matching the router schema or NO_ACTION."


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


def parse_gate_output(raw: str | None) -> Decision:
    if raw is None:
        return NoActionDecision()
    if not isinstance(raw, str):
        raw = str(raw)
    return parse_llm_output(raw)


class MemoryGate:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def decide(self, user_message: str, active_facts: list[dict]) -> Decision:
        prompt = build_prompt(MEMORY_POLICY, active_facts, user_message)
        raw = self._llm.generate(prompt)
        return parse_gate_output(raw)
