from __future__ import annotations

from enum import Enum
import json
import os
from functools import lru_cache
from typing import Any, Dict, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException

from pydantic import BaseModel, Field

from memory.facts import (
    FactCandidate,
    FactRecord,
    FactStatus,
    FactsStore,
    Proposal,
    ProposalStatus,
)

router = APIRouter()


class FactStatusFilter(str, Enum):
    ACTIVE = "ACTIVE"
    OVERRIDDEN = "OVERRIDDEN"
    RETRACTED = "RETRACTED"
    ALL = "ALL"


class FactCandidateIn(BaseModel):
    subject: str
    predicate: str
    object: Any
    confidence: float
    source: Dict[str, Any] = Field(default_factory=dict)
    source_note: Optional[str] = None
    reason: Optional[str] = None


class RetractRequest(BaseModel):
    reason: str


class ProposalStatusFilter(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ALL = "ALL"


class ProposalCandidateOut(BaseModel):
    subject: str
    predicate: str
    object: Any
    confidence: float
    source: Dict[str, Any] = Field(default_factory=dict)


class ProposalOut(BaseModel):
    id: str
    candidate: ProposalCandidateOut
    source_note: str
    reason: Optional[str]
    status: ProposalStatusFilter
    created_at: float
    resolved_at: Optional[float]
    resolved_reason: Optional[str]


class ProposeFactResponse(BaseModel):
    status: ProposalStatusFilter
    proposal: ProposalOut
    record: Optional[Dict[str, Any]] = None


class RejectProposalRequest(BaseModel):
    reason: Optional[str] = None


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
    if record.status == FactStatus.ACTIVE:
        return "ACTIVE"
    if record.status == FactStatus.OVERRIDDEN:
        return "OVERRIDDEN"
    return "RETRACTED"


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


def _serialize_proposal(proposal: Proposal) -> Dict[str, Any]:
    return {
        "id": proposal.id,
        "candidate": {
            "subject": proposal.candidate.subject,
            "predicate": proposal.candidate.predicate,
            "object": _ensure_json_safe(proposal.candidate.object),
            "confidence": proposal.candidate.confidence,
            "source": proposal.candidate.source,
        },
        "source_note": proposal.source_note,
        "reason": proposal.reason,
        "status": proposal.status.value,
        "created_at": proposal.created_at,
        "resolved_at": proposal.resolved_at,
        "resolved_reason": proposal.resolved_reason,
    }


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


def _auto_accept_enabled() -> bool:
    return os.getenv("MEMORY_AUTO_ACCEPT", "").strip() == "1"


def _auto_accept_min_confidence() -> float:
    value = os.getenv("MEMORY_AUTO_ACCEPT_MIN_CONF", "").strip()
    if not value:
        return 0.85
    try:
        return float(value)
    except ValueError:
        return 0.85


def _auto_accept_predicates() -> Optional[set[str]]:
    raw = os.getenv("MEMORY_AUTO_ACCEPT_PREDICATES", "")
    if not raw.strip():
        return None
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _should_auto_accept(candidate: FactCandidate) -> bool:
    if not _auto_accept_enabled():
        return False
    if candidate.confidence < _auto_accept_min_confidence():
        return False
    predicates = _auto_accept_predicates()
    if predicates is None:
        return True
    return candidate.predicate.lower() in predicates


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
    fact_candidate = FactCandidate(
        subject=candidate.subject,
        predicate=candidate.predicate,
        object=candidate.object,
        confidence=candidate.confidence,
        source=candidate.source,
    )
    source_note = candidate.source_note or str(candidate.source.get("type", "api"))
    proposal = await store.create_proposal(
        fact_candidate,
        source_note=source_note,
        reason=candidate.reason,
    )
    if _should_auto_accept(fact_candidate):
        accepted = await store.accept_proposal(proposal.id, resolved_reason="auto-accepted")
        if accepted is None:
            raise HTTPException(status_code=409, detail="Proposal already resolved")
        accepted_proposal, record = accepted
        return {
            "status": accepted_proposal.status.value,
            "proposal": _serialize_proposal(accepted_proposal),
            "record": _serialize_record(record),
        }
    return {
        "status": proposal.status.value,
        "proposal": _serialize_proposal(proposal),
        "record": None,
    }


@router.get("/proposals")
async def list_proposals(
    status: ProposalStatusFilter = ProposalStatusFilter.PENDING,
    store: FactsStore = Depends(get_facts_store),
) -> Dict[str, Any]:
    status_filter = None if status == ProposalStatusFilter.ALL else ProposalStatus(status.value)
    proposals = await store.list_proposals(status_filter)
    return {"items": [_serialize_proposal(proposal) for proposal in proposals]}


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    store: FactsStore = Depends(get_facts_store),
) -> Dict[str, Any]:
    proposal = await store.get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return _serialize_proposal(proposal)


# Response shape: {"proposal": Proposal, "record": FactRecord} to keep proposal+fact consistent.
@router.post("/proposals/{proposal_id}/accept")
async def accept_proposal(
    proposal_id: str,
    store: FactsStore = Depends(get_facts_store),
) -> Dict[str, Any]:
    accepted = await store.accept_proposal(proposal_id)
    if accepted is None:
        proposal = await store.get_proposal(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=400, detail="Proposal already resolved")
    proposal, record = accepted
    return {"proposal": _serialize_proposal(proposal), "record": _serialize_record(record)}


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    payload: RejectProposalRequest,
    store: FactsStore = Depends(get_facts_store),
) -> Dict[str, Any]:
    proposal = await store.reject_proposal(proposal_id, resolved_reason=payload.reason)
    if proposal is None:
        existing = await store.get_proposal(proposal_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="Proposal not found")
        raise HTTPException(status_code=400, detail="Proposal already resolved")
    return _serialize_proposal(proposal)


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
