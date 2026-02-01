from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol


PROMPT = """You are a gatekeeper deciding whether to retract a previously stored fact.
If the input indicates negation or correction of a stored fact, respond with JSON:
{
  "action": "RETRACT",
  "subject": "user",
  "predicate": "...",
  "object": "...",
  "reason": "..."
}
If no retraction is needed, respond with exactly: NO_ACTION
"""


@dataclass(frozen=True)
class RetractRequest:
    subject: str
    predicate: str
    object: str
    reason: str


class LLM(Protocol):
    def decide(self, text: str) -> str:
        raise NotImplementedError


class StubLLM:
    def decide(self, text: str) -> str:
        return "NO_ACTION"


class RetractGate:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def decide(self, text: str) -> RetractRequest | None:
        raw = self._llm.decide(text)
        return self._parse_output(raw)

    def _parse_output(self, raw: str) -> RetractRequest | None:
        if raw is None:
            return None
        stripped = raw.strip()
        if stripped == "NO_ACTION":
            return None
        candidate_text = self._extract_json_block(stripped)
        if not candidate_text:
            return None
        try:
            data = json.loads(candidate_text)
        except json.JSONDecodeError:
            return None
        return self._coerce_candidate(data)

    def _extract_json_block(self, text: str) -> str | None:
        fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()
        if text.startswith("{") and text.endswith("}"):
            return text
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            return json_match.group(0)
        return None

    def _coerce_candidate(self, data: dict) -> RetractRequest | None:
        if data.get("action") != "RETRACT":
            return None
        required = {"subject", "predicate", "object", "reason"}
        if not required.issubset(data):
            return None
        subject = str(data.get("subject")).strip()
        predicate = str(data.get("predicate")).strip()
        object_value = str(data.get("object")).strip()
        reason = str(data.get("reason")).strip()
        if not subject or not predicate or not object_value or not reason:
            return None
        return RetractRequest(
            subject=subject,
            predicate=predicate,
            object=object_value,
            reason=reason,
        )


def build_llm() -> LLM:
    mode = os.getenv("LONELYCAT_LLM_MODE", "stub").lower()
    if mode == "stub":
        return StubLLM()
    raise ValueError(f"Unsupported LLM mode: {mode}")
