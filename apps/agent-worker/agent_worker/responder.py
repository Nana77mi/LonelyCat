from __future__ import annotations

import json
import re

from agent_worker.llm import BaseLLM
from agent_worker.router import parse_llm_output
from agent_worker.trace import TraceCollector
from agent_worker.persona import Persona
from agent_worker.utils.facts_format import format_facts_block

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

    def reply_with_messages(
        self,
        persona: Persona,
        user_message: str,
        history_messages: list[dict[str, str]],
        active_facts: list[dict],
        trace: TraceCollector | None = None,
    ) -> tuple[str, str]:
        """Reply with history messages support.
        
        Args:
            persona: Persona configuration
            user_message: Current user message
            history_messages: List of previous messages in format [{"role": "user|assistant", "content": "..."}, ...]
            active_facts: List of active facts from memory
            trace: Optional trace collector
            
        Returns:
            Tuple of (assistant_reply, memory_hint)
        """
        # Build messages list
        messages: list[dict[str, str]] = []
        
        # Add system prompt with facts in system message (not user). History filtered below.
        facts_block = format_facts_block(active_facts)
        system_parts = [persona.system_prompt, "", POLICY_PROMPT]
        if facts_block:
            system_parts.append(facts_block)
        system_parts.append(RETURN_TEXT_ONLY)
        system_content = "\n".join(system_parts)
        messages.append({"role": "system", "content": system_content})
        
        # Add history messages (filter out any system messages to avoid duplication)
        for msg in history_messages:
            role = msg.get("role", "user")
            if role == "system":
                continue
            messages.append({"role": role, "content": msg.get("content", "")})
        
        # Current user message: only user text (facts are in system message)
        current_user_content = f"user_message: {user_message}"
        messages.append({"role": "user", "content": current_user_content})
        
        if trace:
            trace.record("responder.messages", json.dumps(messages, indent=2))
        
        # Generate response using messages
        raw = self._llm.generate_messages(messages)
        
        if trace:
            trace.record("responder.response", str(raw))
        
        if raw is not None and isinstance(raw, str):
            maybe_decision = parse_llm_output(raw)
            if maybe_decision.action != "NO_ACTION" and "assistant_reply" not in raw:
                return FALLBACK_REPLY, "NO_ACTION"
        
        return parse_responder_output(raw)
