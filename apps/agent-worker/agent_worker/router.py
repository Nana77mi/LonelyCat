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
    decision, _error = parse_llm_output_with_error(text)
    return decision


def parse_llm_output_with_error(text: str | None) -> tuple[Decision, str | None]:
    if text is None:
        return NoActionDecision(), "no_json_found"
    stripped = text.strip()
    if not stripped:
        return NoActionDecision(), "no_json_found"
    if stripped == "NO_ACTION":
        return NoActionDecision(), None
    candidates = _extract_json_objects(stripped)
    if not candidates:
        return NoActionDecision(), "no_json_found"

    action_payload = None
    for _, payload in candidates:
        if isinstance(payload, dict) and isinstance(payload.get("action"), str):
            action_payload = payload
            break
    if action_payload is None:
        return NoActionDecision(), "missing_action"

    action = str(action_payload.get("action", "")).strip()
    action_upper = action.upper()
    if action_upper == "NO_ACTION":
        return NoActionDecision(), None
    if action_upper == "PROPOSE":
        decision = _parse_propose(action_payload)
    elif action_upper == "RETRACT":
        decision = _parse_retract(action_payload)
    elif action_upper == "UPDATE":
        decision = _parse_update(action_payload)
    else:
        return NoActionDecision(), "invalid_action"
    if decision is None:
        return NoActionDecision(), "missing_fields"
    return decision, None


def _extract_json_objects(text: str) -> list[tuple[int, dict]]:
    candidates: list[tuple[int, dict]] = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.DOTALL):
        candidate_text = match.group(1).strip()
        try:
            payload = json.loads(candidate_text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            candidates.append((match.start(), payload))

    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(text):
        start = text.find("{", idx)
        if start == -1:
            break
        try:
            payload, end = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            idx = start + 1
            continue
        if isinstance(payload, dict):
            candidates.append((start, payload))
        idx = start + end
    candidates.sort(key=lambda item: item[0])
    return candidates


def _coerce_confidence(data: dict) -> float | None:
    if "confidence" not in data:
        return None
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)):
        return None
    value = float(confidence)
    if not 0.0 <= value <= 1.0:
        return None
    return value


def _parse_propose(data: dict) -> ProposeDecision | None:
    required = {"subject", "predicate", "object", "confidence"}
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
    required = {"subject", "predicate", "old_object", "new_object", "confidence", "reason"}
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
