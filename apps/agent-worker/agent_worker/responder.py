from __future__ import annotations

import json
import re

from agent_worker.llm import BaseLLM
from agent_worker.persona import Persona

POLICY_PROMPT = """You are an assistant responding to the user.
Use the active_facts as context when helpful.
Do not decide on memory actions here.
Respond with helpful, concise text.
"""
RETURN_TEXT_ONLY = "Return plain text. If you output JSON, include assistant_reply."


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
        return "", "NO_ACTION"
    if not isinstance(raw_text, str):
        raw_text = str(raw_text)
    stripped = raw_text.strip()
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
        return stripped, "NO_ACTION"
    memory_hint = data.get("memory", "NO_ACTION")
    if not isinstance(memory_hint, str):
        memory_hint = "NO_ACTION"
    return assistant_reply, memory_hint


class Responder:
    def __init__(self, llm: BaseLLM) -> None:
        self._llm = llm

    def reply(
        self, persona: Persona, user_message: str, active_facts: list[dict]
    ) -> tuple[str, str]:
        prompt = build_prompt(persona, POLICY_PROMPT, active_facts, user_message)
        raw = self._llm.generate(prompt)
        return parse_responder_output(raw)
