from __future__ import annotations

from enum import Enum
import json
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel, Field

from memory.facts import FactCandidate, FactRecord, FactStatus, FactsStore

router = APIRouter()


class FactStatusFilter(str, Enum):
    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"
    ALL = "ALL"


class FactCandidateIn(BaseModel):
    subject: str
    predicate: str
    object: Any
    confidence: float
    source: Dict[str, Any] = Field(default_factory=dict)


class RetractRequest(BaseModel):
    reason: str


@lru_cache(maxsize=1)
def get_facts_store() -> FactsStore:
    return FactsStore()


def _ensure_json_safe(value: Any) -> Any:
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def _status_string(record: FactRecord) -> str:
    return "ACTIVE" if record.status == FactStatus.ACTIVE else "RETRACTED"


def _serialize_record(record: FactRecord) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "id": record.id,
        "subject": record.subject,
        "predicate": record.predicate,
        "object": _ensure_json_safe(record.object),
        "confidence": record.confidence,
        "status": _status_string(record),
        "created_at": record.created_at,
        "seq": record.seq,
        "source": record.source,
        "overrides": record.overrides,
        "retracted_reason": record.retracted_reason,
    }
    return data


def _filter_records(
    records: Iterable[FactRecord],
    status: FactStatusFilter,
    predicate_contains: Optional[str],
) -> list[FactRecord]:
    filtered = list(records)
    if status != FactStatusFilter.ALL:
        filtered = [record for record in filtered if _status_string(record) == status.value]
    if predicate_contains:
        needle = predicate_contains.lower()
        filtered = [record for record in filtered if needle in record.predicate.lower()]
    return filtered


@router.get("/facts")
async def list_facts(
    subject: str = "user",
    status: FactStatusFilter = FactStatusFilter.ALL,
    predicate_contains: Optional[str] = None,
    store: FactsStore = Depends(get_facts_store),
) -> Dict[str, Any]:
    records = await store.list_subject(subject)
    filtered = _filter_records(records, status, predicate_contains)
    return {"items": [_serialize_record(record) for record in filtered]}


@router.get("/facts/{record_id}")
async def get_fact(record_id: str, store: FactsStore = Depends(get_facts_store)) -> Dict[str, Any]:
    record = await store.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return _serialize_record(record)


@router.post("/facts/propose")
async def propose_fact(
    candidate: FactCandidateIn,
    store: FactsStore = Depends(get_facts_store),
) -> Dict[str, Any]:
    record = await store.propose(
        FactCandidate(
            subject=candidate.subject,
            predicate=candidate.predicate,
            object=candidate.object,
            confidence=candidate.confidence,
            source=candidate.source,
        )
    )
    return _serialize_record(record)


@router.post("/facts/{record_id}/retract")
async def retract_fact(
    record_id: str,
    payload: RetractRequest,
    store: FactsStore = Depends(get_facts_store),
) -> Dict[str, Any]:
    record = await store.get(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    if record.status == FactStatus.RETRACTED:
        raise HTTPException(status_code=400, detail="Fact already retracted")
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(status_code=400, detail="Retraction reason required")
    await store.retract(record_id, reason)
    updated = await store.get(record_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return _serialize_record(updated)


@router.get("/facts/{record_id}/chain")
async def get_fact_chain(
    record_id: str,
    max_depth: int = 20,
    store: FactsStore = Depends(get_facts_store),
) -> Dict[str, Any]:
    if max_depth <= 0:
        return {"root_id": record_id, "items": [], "truncated": True}
    items: list[Dict[str, Any]] = []
    visited: set[str] = set()
    current_id: Optional[str] = record_id
    truncated = False
    while current_id is not None and len(items) < max_depth:
        if current_id in visited:
            truncated = True
            break
        visited.add(current_id)
        record = await store.get(current_id)
        if record is None:
            truncated = True
            break
        items.append(_serialize_record(record))
        current_id = record.overrides
    if current_id is not None and len(items) >= max_depth:
        truncated = True
    return {"root_id": record_id, "items": items, "truncated": truncated}
