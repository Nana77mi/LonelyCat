from __future__ import annotations

import os
from dataclasses import dataclass

from agent_worker.config import ChatConfig
from agent_worker.llm import BaseLLM, JsonOnlyLLMWrapper, build_llm_from_env
from agent_worker.memory_client import MemoryClient
from agent_worker.memory_gate import MemoryGate
from agent_worker.persona import PersonaRegistry
from agent_worker.responder import FALLBACK_REPLY, Responder
from agent_worker.router import (
    NoActionDecision,
    RetractDecision,
    UpdateDecision,
)
from agent_worker.run import execute_decision
from agent_worker.trace import TraceCollector


PERSONA_REGISTRY = PersonaRegistry.load_default()

# Maximum number of conversation turns to keep in context
MAX_TURNS = int(os.getenv("CHAT_MAX_TURNS", "10"))

@dataclass(frozen=True)
class ChatResult:
    assistant_reply: str
    memory_status: str
    trace_id: str
    trace_lines: list[str]


class _DecideAdapter(BaseLLM):
    def __init__(self, llm: object) -> None:
        self._llm = llm

    def generate(self, prompt: str) -> str:
        return self._llm.decide(prompt)


def _coerce_llm(llm: object | None) -> BaseLLM:
    if llm is None:
        return build_llm_from_env()
    if hasattr(llm, "generate"):
        return llm  # type: ignore[return-value]
    if hasattr(llm, "decide"):
        return _DecideAdapter(llm)
    raise ValueError("LLM must implement generate(prompt)")


def chat_flow(
    user_message: str,
    persona_id: str | None,
    llm: BaseLLM | None,
    memory_client: MemoryClient | None,
    config: ChatConfig | None,
    history_messages: list[dict[str, str]] | None = None,
) -> ChatResult:
    config = config or ChatConfig.from_env()
    trace = TraceCollector.from_env()
    trace.record("chat_flow.start")

    llm = _coerce_llm(llm)
    gate_llm = JsonOnlyLLMWrapper(llm)
    persona = PERSONA_REGISTRY.get(persona_id or config.persona_default)

    active_facts: list[dict] = []
    memory_client_in_use: MemoryClient | None = None
    if config.memory_enabled:
        memory_client_in_use = memory_client or MemoryClient()
        try:
            trace.record("memory.list_facts.start")
            active_facts = memory_client_in_use.list_facts(
                scope="global", status="active"
            )
            trace.record("memory.list_facts.finish")
        except Exception:
            trace.record("memory.list_facts.error")
            active_facts = []
    else:
        trace.record("memory.disabled")

    responder = Responder(llm)
    gate = MemoryGate(gate_llm)
    had_error = False

    # Apply context window limit if history messages are provided
    if history_messages is not None:
        # Limit to last MAX_TURNS * 2 messages (each turn = user + assistant)
        # Filter out system messages for counting (they're handled separately)
        non_system_messages = [msg for msg in history_messages if msg.get("role") != "system"]
        if len(non_system_messages) > MAX_TURNS * 2:
            # Keep system messages and last MAX_TURNS * 2 non-system messages
            system_messages = [msg for msg in history_messages if msg.get("role") == "system"]
            limited_non_system = non_system_messages[-(MAX_TURNS * 2):]
            history_messages = system_messages + limited_non_system
            trace.record("chat_flow.context_window_limited", f"kept {len(history_messages)} messages")

    try:
        if history_messages is not None:
            # Use message-based reply with history
            assistant_reply, _memory_hint = responder.reply_with_messages(
                persona,
                user_message,
                history_messages,
                active_facts,
                trace=trace,
            )
        else:
            # Use original prompt-based reply for backward compatibility
            assistant_reply, _memory_hint = responder.reply(
                persona,
                user_message,
                active_facts,
                trace=trace,
            )
    except Exception as exc:
        if trace:
            trace.record("responder.error", str(exc))
        assistant_reply = "Okay."
        had_error = True
    if not assistant_reply:
        assistant_reply = FALLBACK_REPLY

    try:
        decision = gate.decide(user_message, active_facts, trace=trace)
    except Exception as exc:
        if trace:
            trace.record("gate.error", str(exc))
        decision = NoActionDecision()
        had_error = True

    if had_error:
        decision = NoActionDecision()
    if not config.memory_enabled:
        decision = NoActionDecision()
    elif isinstance(decision, UpdateDecision) and not config.memory_allow_update:
        decision = NoActionDecision()
    elif isinstance(decision, RetractDecision) and not config.memory_allow_retract:
        decision = NoActionDecision()

    if isinstance(decision, NoActionDecision) or memory_client_in_use is None:
        status = "NO_ACTION"
    else:
        status = execute_decision(
            decision,
            memory_client_in_use,
            propose_source_note="chat",
            trace=trace,
        )

    trace.record("chat_flow.finish")
    return ChatResult(
        assistant_reply=assistant_reply,
        memory_status=status,
        trace_id=trace.trace_id,
        trace_lines=trace.render_lines(),
    )
