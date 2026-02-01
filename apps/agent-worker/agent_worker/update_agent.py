from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol


PROMPT = """You are a gatekeeper deciding whether to update a stored user preference.
If the input indicates a preference change, respond with JSON:
{
  "action": "UPDATE",
  "subject": "user",
  "predicate": "likes",
  "old_object": "cats",
  "new_object": "dogs",
  "confidence": 0.0-1.0,
  "reason": "user preference changed"
}
If no update is needed, respond with exactly: NO_ACTION
"""


@dataclass(frozen=True)
class UpdateRequest:
    subject: str
    predicate: str
    old_object: str
    new_object: str
    confidence: float
    reason: str


class LLM(Protocol):
    def decide(self, text: str) -> str:
        raise NotImplementedError


class StubLLM:
    def decide(self, text: str) -> str:
        return "NO_ACTION"


class UpdateGate:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def decide(self, text: str) -> UpdateRequest | None:
        raw = self._llm.decide(text)
        return self._parse_output(raw)

    def _parse_output(self, raw: str) -> UpdateRequest | None:
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

    def _coerce_candidate(self, data: dict) -> UpdateRequest | None:
        if data.get("action") != "UPDATE":
            return None
        required = {"subject", "predicate", "old_object", "new_object", "reason"}
        if not required.issubset(data):
            return None
        confidence = data.get("confidence", 0.7)
        if not isinstance(confidence, (int, float)):
            return None
        clamped_confidence = max(0.0, min(1.0, float(confidence)))
        subject = str(data.get("subject")).strip()
        predicate = str(data.get("predicate")).strip()
        old_object = str(data.get("old_object")).strip()
        new_object = str(data.get("new_object")).strip()
        reason = str(data.get("reason")).strip()
        if not subject or not predicate or not old_object or not new_object or not reason:
            return None
        return UpdateRequest(
            subject=subject,
            predicate=predicate,
            old_object=old_object,
            new_object=new_object,
            confidence=clamped_confidence,
            reason=reason,
        )


def build_llm() -> LLM:
    mode = os.getenv("LONELYCAT_LLM_MODE", "stub").lower()
    if mode == "stub":
        return StubLLM()
    raise ValueError(f"Unsupported LLM mode: {mode}")
