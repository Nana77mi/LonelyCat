from __future__ import annotations

import os
from dataclasses import dataclass

from agent_worker.config import ChatConfig
from agent_worker.utils.facts_format import compute_facts_snapshot_id
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
from agent_worker.utils.facts import fetch_active_facts, fetch_active_facts_via_api


PERSONA_REGISTRY = PersonaRegistry.load_default()

# Maximum number of messages to keep in context (after filtering user/assistant only)
# Default: 40 messages (more robust than MAX_TURNS * 2 for non-strict alternation)
MAX_MESSAGES = int(os.getenv("CHAT_MAX_MESSAGES", "40"))

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
    conversation_id: str | None = None,
    active_facts: list[dict] | None = None,
) -> ChatResult:
    config = config or ChatConfig.from_env()
    trace = TraceCollector.from_env()
    trace.record("chat_flow.start")

    llm = _coerce_llm(llm)
    gate_llm = JsonOnlyLLMWrapper(llm)
    persona = PERSONA_REGISTRY.get(persona_id or config.persona_default)

    facts_list: list[dict] = []
    memory_client_in_use: MemoryClient | None = None
    if active_facts is not None:
        # 调用方已传入 facts（例如 core-api 内直接查 store，避免同进程 HTTP 自调用阻塞）
        facts_list = list(active_facts)
        trace.record("memory.list_facts.source", "provided")
        trace.record("memory.list_facts.schema_version", "1")
        trace.record("memory.list_facts.finish", f"count={len(facts_list)}")
        if facts_list:
            trace.record("memory.list_facts.sample", str(facts_list[0]) if len(facts_list) > 0 else "")
        facts_snapshot_id = compute_facts_snapshot_id(facts_list)
        trace.record("memory.list_facts.facts_snapshot_id", facts_snapshot_id)
        memory_client_in_use = memory_client or (MemoryClient() if config.memory_enabled else None)
    elif config.memory_enabled:
        memory_client_in_use = memory_client or MemoryClient()
        try:
            trace.record("memory.list_facts.start")
            base_url = os.getenv("LONELYCAT_CORE_API_URL", "http://localhost:5173")
            facts_list = fetch_active_facts_via_api(
                base_url,
                conversation_id=conversation_id,
            )
            trace.record("memory.list_facts.finish", f"count={len(facts_list)}")
            if facts_list:
                trace.record("memory.list_facts.sample", str(facts_list[0]) if len(facts_list) > 0 else "")
            else:
                trace.record("memory.list_facts.empty", "No active facts found")
            facts_snapshot_id = compute_facts_snapshot_id(facts_list)
            trace.record("memory.list_facts.facts_snapshot_id", facts_snapshot_id)
        except Exception as exc:
            import traceback
            error_detail = f"{type(exc).__name__}: {str(exc)}"
            trace.record("memory.list_facts.error", error_detail)
            trace.record("memory.list_facts.error_traceback", traceback.format_exc()[:500])
            facts_list = []
    else:
        trace.record("memory.disabled")

    responder = Responder(llm)
    gate = MemoryGate(gate_llm)
    had_error = False

    # Apply context window limit if history messages are provided
    if history_messages is not None:
        # Filter to only user/assistant messages (system messages are handled separately in responder)
        # Then truncate by message count (more robust than MAX_TURNS * 2 for non-strict alternation)
        user_assistant_messages = [
            msg for msg in history_messages 
            if msg.get("role") in ("user", "assistant")
        ]
        if len(user_assistant_messages) > MAX_MESSAGES:
            # Keep only the last MAX_MESSAGES user/assistant messages
            history_messages = user_assistant_messages[-MAX_MESSAGES:]
            trace.record("chat_flow.context_window_limited", f"kept {len(history_messages)} messages (max: {MAX_MESSAGES})")
        else:
            # Ensure only user/assistant messages are passed (filter out any system messages)
            history_messages = user_assistant_messages

    try:
        if history_messages is not None:
            # Use message-based reply with history
            assistant_reply, _memory_hint = responder.reply_with_messages(
                persona,
                user_message,
                history_messages,
                facts_list,
                trace=trace,
            )
        else:
            # Use original prompt-based reply for backward compatibility
            assistant_reply, _memory_hint = responder.reply(
                persona,
                user_message,
                facts_list,
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
        decision = gate.decide(user_message, facts_list, trace=trace)
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
