from __future__ import annotations

import json
import re

from agent_worker.llm import BaseLLM
from agent_worker.router import parse_llm_output
from agent_worker.trace import TraceCollector
from agent_worker.persona import Persona

POLICY_PROMPT = """You are an assistant responding to the user.
Use the active_facts as context when helpful.
Do not decide on memory actions here.
Respond with helpful, concise text.
"""
RETURN_TEXT_ONLY = "Return plain text. If you output JSON, include assistant_reply."
FALLBACK_REPLY = "I'm sorry, I couldn't generate a response."


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


def build_prompt(
    persona: Persona,
    policy_prompt: str,
    active_facts: list[dict],
    user_message: str,
) -> str:
    facts_json = json.dumps(active_facts, separators=(",", ":"))
    return (
        f"{persona.system_prompt}\n\n"
        f"{policy_prompt}\n"
        f"user_message: {user_message}\n"
        f"active_facts: {facts_json}\n"
        f"{RETURN_TEXT_ONLY}\n"
    )


def parse_responder_output(raw_text: str | None) -> tuple[str, str]:
    if raw_text is None:
        return FALLBACK_REPLY, "NO_ACTION"
    if not isinstance(raw_text, str):
        raw_text = str(raw_text)
    stripped = raw_text.strip()
    if not stripped:
        return FALLBACK_REPLY, "NO_ACTION"
    candidate_text = _extract_json_block(stripped)
    if not candidate_text:
        return stripped, "NO_ACTION"
    try:
        data = json.loads(candidate_text)
    except json.JSONDecodeError:
        return stripped, "NO_ACTION"
    if not isinstance(data, dict):
        return stripped, "NO_ACTION"
    assistant_reply = data.get("assistant_reply")
    if not isinstance(assistant_reply, str):
        if data.get("action") is not None:
            return FALLBACK_REPLY, "NO_ACTION"
        return stripped, "NO_ACTION"
    memory_hint = data.get("memory", "NO_ACTION")
    if not isinstance(memory_hint, str):
        memory_hint = "NO_ACTION"
    return assistant_reply, memory_hint


class Responder:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def reply(
        self,
        persona: Persona,
        user_message: str,
        active_facts: list[dict],
        trace: TraceCollector | None = None,
    ) -> tuple[str, str]:
        prompt = build_prompt(persona, POLICY_PROMPT, active_facts, user_message)
        if trace:
            trace.record("responder.prompt", prompt)
        raw = self._llm.generate(prompt)
        if trace:
            trace.record("responder.response", str(raw))
        if raw is not None and isinstance(raw, str):
            maybe_decision = parse_llm_output(raw)
            if maybe_decision.action != "NO_ACTION" and "assistant_reply" not in raw:
                return FALLBACK_REPLY, "NO_ACTION"
        return parse_responder_output(raw)
