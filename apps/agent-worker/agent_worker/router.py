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
    decision, _ = parse_llm_output_with_reason(text)
    return decision


def parse_llm_output_with_reason(text: str | None) -> tuple[Decision, str | None]:
    if text is None:
        return NoActionDecision(), "empty"
    stripped = text.strip()
    if stripped == "NO_ACTION":
        return NoActionDecision(), None
    candidates = _extract_json_candidates(stripped)
    if not candidates:
        return NoActionDecision(), "no_json_candidates"
    last_valid: Decision | None = None
    last_error: str | None = None
    for candidate_text in candidates:
        try:
            data = json.loads(candidate_text)
        except json.JSONDecodeError:
            last_error = "json_decode_error"
            continue
        if not isinstance(data, dict):
            last_error = "json_not_object"
            continue
        action = data.get("action")
        if action == "PROPOSE":
            decision = _parse_propose(data)
        elif action == "RETRACT":
            decision = _parse_retract(data)
        elif action == "UPDATE":
            decision = _parse_update(data)
        else:
            decision = None
            last_error = "missing_action"
        if decision:
            last_valid = decision
    if last_valid:
        return last_valid, None
    return NoActionDecision(), last_error or "invalid_json"


def _extract_json_candidates(text: str) -> list[str]:
    fenced = [
        block.strip()
        for block in re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    ]
    fenced = [block for block in fenced if block]
    if fenced:
        return fenced
    return _find_json_objects(text)


def _find_json_objects(text: str) -> list[str]:
    candidates: list[str] = []
    depth = 0
    start_index: int | None = None
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start_index = index
            depth += 1
            continue
        if char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start_index is not None:
                candidates.append(text[start_index : index + 1])
                start_index = None
    return candidates


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
