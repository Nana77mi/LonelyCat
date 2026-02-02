from __future__ import annotations

import json
import re
import sys
from typing import Sequence

from agent_worker.llm import BaseLLM, build_llm_from_env
from agent_worker.persona import PersonaRegistry
from agent_worker.router import NoActionDecision, parse_llm_output
from agent_worker.run import execute_decision
from agent_worker.memory_client import MemoryClient


PERSONA_REGISTRY = PersonaRegistry.load_default()
POLICY_VERSION = "v1"  # Changing POLICY_PROMPT is a behavior change; persona updates are not.
POLICY_PROMPT = """You will receive:
- user_message
- active_facts (JSON list)
Respond with a single JSON object with EXACTLY these keys:
- assistant_reply (string)
- memory ("NO_ACTION" or an action JSON matching the router schema)

Memory safety guardrails:
- Do not store sensitive personal data (addresses, phone numbers, IDs, financial details).
- Only store stable preferences, goals, or long-term facts.
- If uncertain, choose NO_ACTION.
Decide on memory actions conservatively: store stable preferences/goals, retract when negated,
update when the user explicitly changes a preference. Use NO_ACTION otherwise.
"""
RETURN_ONLY_JSON = "Return only JSON."


def _coerce_llm(llm: object | None) -> BaseLLM:
    if llm is None:
        return build_llm_from_env()
    if hasattr(llm, "generate"):
        return llm  # type: ignore[return-value]
    raise ValueError("LLM must implement generate(prompt)")


def _extract_json_block(text: str) -> str | None:
    # Chat-specific helper: extracts a JSON object from the model output without changing routing logic.
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return json_match.group(0)
    return None


def _parse_chat_output(raw_text: str | None):
    if raw_text is None:
        return "", NoActionDecision()
    if not isinstance(raw_text, str):
        raw_text = str(raw_text)
    stripped = raw_text.strip()
    candidate_text = _extract_json_block(stripped)
    if not candidate_text:
        return stripped, NoActionDecision()
    try:
        data = json.loads(candidate_text)
    except json.JSONDecodeError:
        return stripped, NoActionDecision()
    if not isinstance(data, dict):
        return stripped, NoActionDecision()
    assistant_reply = data.get("assistant_reply")
    if not isinstance(assistant_reply, str):
        assistant_reply = "" if data.get("action") == "NO_ACTION" else stripped
    memory = data.get("memory", "NO_ACTION")
    if isinstance(memory, dict):
        decision = parse_llm_output(json.dumps(memory))
        return assistant_reply, decision
    if isinstance(memory, str) and memory.strip() == "NO_ACTION":
        return assistant_reply, NoActionDecision()
    return assistant_reply, NoActionDecision()


def build_chat_prompt(
    *,
    persona,
    policy_prompt: str,
    user_message: str,
    facts_json: str,
) -> str:
    """
    Build the final chat prompt.

    IMPORTANT:
    - Persona only affects assistant reply style.
    - Policy prompt defines behavioral constraints.
    - Memory decisions must NOT be influenced by persona.
    """
    return (
        f"{persona.system_prompt}\n\n"
        f"{policy_prompt}\n"
        f"user_message: {user_message}\n"
        f"active_facts: {facts_json}\n"
        f"{RETURN_ONLY_JSON}\n"
    )


# chat() is the primary programmatic API.
# main() is a thin CLI wrapper and must not contain business logic.
def chat(
    text: str,
    persona_id: str | None = None,
    llm: BaseLLM | None = None,
    memory_client: MemoryClient | None = None,
):
    memory_client = memory_client or MemoryClient()
    facts = memory_client.list_facts(subject="user", status="ACTIVE")

    llm = _coerce_llm(llm)
    persona = PERSONA_REGISTRY.get(persona_id)
    prompt = build_chat_prompt(
        persona=persona,
        policy_prompt=POLICY_PROMPT,
        user_message=text,
        facts_json=json.dumps(facts, separators=(",", ":")),
    )
    raw_response = llm.generate(prompt)
    assistant_reply, decision = _parse_chat_output(raw_response)

    status = execute_decision(decision, memory_client, propose_source_note="chat")
    return assistant_reply, status


def main(argv: Sequence[str] | None = None, *, llm=None, memory_client=None) -> None:
    args = list(argv or sys.argv[1:])
    if not args:
        raise SystemExit("Usage: python -m agent_worker.chat \"user message\"")
    user_message = args[0]
    assistant_reply, status = chat(
        user_message,
        llm=llm,
        memory_client=memory_client,
    )
    print(assistant_reply)
    print(f"MEMORY: {status}")


if __name__ == "__main__":
    main()
