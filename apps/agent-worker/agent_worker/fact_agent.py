from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Protocol


PROMPT = """You are a gatekeeper deciding whether to store a stable fact about a user.
Only store stable facts (preferences, identity, long-term goals). Do not store transient info.
If the input contains a stable fact, respond with JSON:
{ "subject": "...", "predicate": "...", "object": "...", "confidence": 0.0-1.0 }
If no stable fact, respond with exactly: NO_FACT
Subject guideline: use "user" when the fact is about the user's stable preferences.
"""


@dataclass(frozen=True)
class FactProposal:
    subject: str
    predicate: str
    object: str
    confidence: float


class LLM(Protocol):
    def decide(self, text: str) -> str:
        raise NotImplementedError


class StubLLM:
    def decide(self, text: str) -> str:
        lowered = text.lower()
        if "like cats" in lowered:
            return json.dumps(
                {
                    "subject": "user",
                    "predicate": "likes",
                    "object": "cats",
                    "confidence": 0.9,
                }
            )
        return "NO_FACT"


class FactGate:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    def decide(self, text: str) -> FactProposal | None:
        raw = self._llm.decide(text)
        return self._parse_output(raw)

    def _parse_output(self, raw: str) -> FactProposal | None:
        if raw is None:
            return None
        stripped = raw.strip()
        if stripped == "NO_FACT":
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

    def _coerce_candidate(self, data: dict) -> FactProposal | None:
        required = {"subject", "predicate", "object", "confidence"}
        if not required.issubset(data):
            return None
        confidence = data.get("confidence")
        if not isinstance(confidence, (int, float)):
            return None
        if not 0 <= confidence <= 1:
            return None
        subject = str(data.get("subject")).strip()
        predicate = str(data.get("predicate")).strip()
        object_value = str(data.get("object")).strip()
        if not subject or not predicate or not object_value:
            return None
        return FactProposal(
            subject=subject,
            predicate=predicate,
            object=object_value,
            confidence=float(confidence),
        )


def build_llm() -> LLM:
    mode = os.getenv("LONELYCAT_LLM_MODE", "stub").lower()
    if mode == "stub":
        return StubLLM()
    raise ValueError(f"Unsupported LLM mode: {mode}")
