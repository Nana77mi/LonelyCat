from __future__ import annotations

import json
import re

from agent_worker.llm import BaseLLM
from agent_worker.router import Decision, NoActionDecision, parse_llm_output_with_error
from agent_worker.trace import TraceCollector

MEMORY_GATE_MARKER = "### MEMORY_GATE ###"
MEMORY_POLICY = """Decide if the message implies a long-term, non-sensitive user fact.
Return ONLY a JSON object with an action:
PROPOSE: { "action":"PROPOSE","subject":"user","predicate":"...","object":"...","confidence":0.0-1.0 }
RETRACT: { "action":"RETRACT","subject":"user","predicate":"...","object":"...","reason":"..." }
UPDATE: { "action":"UPDATE","subject":"user","predicate":"...","old_object":"...","new_object":"...","confidence":0.0-1.0,"reason":"..." }
Or { "action":"NO_ACTION" } when unsure.
Never include assistant_reply or extra keys.
"""
RETURN_GATE_JSON = "Return ONLY the JSON object."


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
    decision, _error = parse_gate_output_with_error(raw)
    return decision


def parse_gate_output_with_error(raw: str | None) -> tuple[Decision, str | None]:
    if raw is None:
        return NoActionDecision(), "no_json_found"
    if not isinstance(raw, str):
        raw = str(raw)
    stripped = raw.strip()
    if not stripped:
        return NoActionDecision(), "no_json_found"
    candidate_text = _extract_json_block(stripped)
    if candidate_text:
        try:
            data = json.loads(candidate_text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "assistant_reply" in data:
            return NoActionDecision(), "assistant_reply_payload"
    return parse_llm_output_with_error(stripped)


def _extract_json_block(text: str) -> str | None:
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return json_match.group(0)
    return None


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
        decision, error = parse_gate_output_with_error(raw)
        if trace and error:
            trace.record("gate.parse_error", error)
        return decision
