from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Union


@dataclass(frozen=True)
class NoActionDecision:
    action: Literal["NO_ACTION"] = "NO_ACTION"


@dataclass(frozen=True)
class ProposeDecision:
    action: Literal["PROPOSE"]
    subject: str
    predicate: str
    object: str
    confidence: float


@dataclass(frozen=True)
class RetractDecision:
    action: Literal["RETRACT"]
    subject: str
    predicate: str
    object: str
    reason: str


@dataclass(frozen=True)
class UpdateDecision:
    action: Literal["UPDATE"]
    subject: str
    predicate: str
    old_object: str
    new_object: str
    confidence: float
    reason: str


Decision = Union[NoActionDecision, ProposeDecision, RetractDecision, UpdateDecision]


def parse_llm_output(text: str | None) -> Decision:
    if text is None:
        return NoActionDecision()
    stripped = text.strip()
    if stripped == "NO_ACTION":
        return NoActionDecision()
    candidate_text = _extract_json_block(stripped)
    if not candidate_text:
        return NoActionDecision()
    try:
        data = json.loads(candidate_text)
    except json.JSONDecodeError:
        return NoActionDecision()
    if not isinstance(data, dict):
        return NoActionDecision()
    action = data.get("action")
    if action == "PROPOSE":
        decision = _parse_propose(data)
    elif action == "RETRACT":
        decision = _parse_retract(data)
    elif action == "UPDATE":
        decision = _parse_update(data)
    else:
        decision = None
    return decision or NoActionDecision()


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


def _coerce_confidence(data: dict, default: float = 0.7) -> float | None:
    confidence = data.get("confidence", default)
    if not isinstance(confidence, (int, float)):
        return None
    return max(0.0, min(1.0, float(confidence)))


def _parse_propose(data: dict) -> ProposeDecision | None:
    required = {"subject", "predicate", "object"}
    if not required.issubset(data):
        return None
    confidence = _coerce_confidence(data)
    if confidence is None:
        return None
    subject = str(data.get("subject")).strip()
    predicate = str(data.get("predicate")).strip()
    object_value = str(data.get("object")).strip()
    if not subject or not predicate or not object_value:
        return None
    return ProposeDecision(
        action="PROPOSE",
        subject=subject,
        predicate=predicate,
        object=object_value,
        confidence=confidence,
    )


def _parse_retract(data: dict) -> RetractDecision | None:
    required = {"subject", "predicate", "object", "reason"}
    if not required.issubset(data):
        return None
    subject = str(data.get("subject")).strip()
    predicate = str(data.get("predicate")).strip()
    object_value = str(data.get("object")).strip()
    reason = str(data.get("reason")).strip()
    if not subject or not predicate or not object_value or not reason:
        return None
    return RetractDecision(
        action="RETRACT",
        subject=subject,
        predicate=predicate,
        object=object_value,
        reason=reason,
    )


def _parse_update(data: dict) -> UpdateDecision | None:
    required = {"subject", "predicate", "old_object", "new_object", "reason"}
    if not required.issubset(data):
        return None
    confidence = _coerce_confidence(data)
    if confidence is None:
        return None
    subject = str(data.get("subject")).strip()
    predicate = str(data.get("predicate")).strip()
    old_object = str(data.get("old_object")).strip()
    new_object = str(data.get("new_object")).strip()
    reason = str(data.get("reason")).strip()
    if not subject or not predicate or not old_object or not new_object or not reason:
        return None
    return UpdateDecision(
        action="UPDATE",
        subject=subject,
        predicate=predicate,
        old_object=old_object,
        new_object=new_object,
        confidence=confidence,
        reason=reason,
    )
