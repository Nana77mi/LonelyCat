from __future__ import annotations

import asyncio
import copy
import time
import uuid
import warnings
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class FactStatus(Enum):
    ACTIVE = "active"
    OVERRIDDEN = "overridden"
    RETRACTED = "retracted"


class ProposalStatus(Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class FactCandidate:
    """Proposed fact values.

    object should be JSON-serializable or otherwise copy-safe.
    """
    subject: str
    predicate: str
    object: Any
    confidence: float
    source: Dict[str, Any]


@dataclass
class FactRecord:
    id: str
    subject: str
    predicate: str
    object: Any
    confidence: float
    source: Dict[str, Any]
    status: FactStatus
    created_at: float
    seq: int
    overrides: Optional[str] = None
    retracted_reason: Optional[str] = None


@dataclass
class Proposal:
    id: str
    candidate: FactCandidate
    source_note: str
    reason: Optional[str]
    status: ProposalStatus
    created_at: float
    resolved_at: Optional[float] = None
    resolved_reason: Optional[str] = None


class FactsStore:
    """In-memory facts store.

    Invariants:
        - At most one ACTIVE record exists per (subject, predicate).
        - _active_by_key maps only ACTIVE record ids.
        - OVERRIDDEN and RETRACTED records are never present in _active_by_key.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._records: Dict[str, FactRecord] = {}
        self._active_by_key: Dict[Tuple[str, str], str] = {}
        self._proposals: Dict[str, Proposal] = {}
        self._seq = 0

    def _copy_record(self, record: FactRecord) -> FactRecord:
        try:
            return copy.deepcopy(record)
        except Exception:
            return replace(record)

    def _copy_proposal(self, proposal: Proposal) -> Proposal:
        try:
            return copy.deepcopy(proposal)
        except Exception:
            return replace(proposal)

    def _create_record(self, candidate: FactCandidate) -> FactRecord:
        key = (candidate.subject, candidate.predicate)
        previous_id = self._active_by_key.get(key)
        record_id = uuid.uuid4().hex
        self._seq += 1
        record = FactRecord(
            id=record_id,
            subject=candidate.subject,
            predicate=candidate.predicate,
            object=candidate.object,
            confidence=candidate.confidence,
            source=dict(candidate.source),
            status=FactStatus.ACTIVE,
            created_at=time.time(),
            seq=self._seq,
            overrides=None,
        )
        if previous_id is not None:
            previous = self._records.get(previous_id)
            if previous is not None and previous.status == FactStatus.ACTIVE:
                previous.status = FactStatus.OVERRIDDEN
                record.overrides = previous.id
        self._records[record.id] = record
        self._active_by_key[key] = record.id
        return record

    async def create_record_direct(self, candidate: FactCandidate) -> FactRecord:
        """Create an ACTIVE fact record directly (bypasses proposals)."""
        if not 0 <= candidate.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

        async with self._lock:
            record = self._create_record(candidate)
            return self._copy_record(record)

    async def propose(self, candidate: FactCandidate) -> FactRecord:
        """Deprecated: use create_record_direct or proposal flow instead."""
        warnings.warn(
            "FactsStore.propose is deprecated; use create_record_direct or proposals.",
            DeprecationWarning,
            stacklevel=2,
        )
        return await self.create_record_direct(candidate)

    async def create_proposal(
        self,
        candidate: FactCandidate,
        source_note: str,
        reason: Optional[str] = None,
    ) -> Proposal:
        if not 0 <= candidate.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

        async with self._lock:
            proposal_id = uuid.uuid4().hex
            proposal = Proposal(
                id=proposal_id,
                candidate=candidate,
                source_note=source_note,
                reason=reason,
                status=ProposalStatus.PENDING,
                created_at=time.time(),
                resolved_at=None,
                resolved_reason=None,
            )
            self._proposals[proposal.id] = proposal
            return self._copy_proposal(proposal)

    async def list_proposals(
        self, status: Optional[ProposalStatus] = None
    ) -> List[Proposal]:
        async with self._lock:
            proposals = list(self._proposals.values())
            if status is not None:
                proposals = [proposal for proposal in proposals if proposal.status == status]
            proposals.sort(key=lambda item: item.created_at)
            return [self._copy_proposal(proposal) for proposal in proposals]

    async def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        async with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return None
            return self._copy_proposal(proposal)

    async def accept_proposal(
        self, proposal_id: str, resolved_reason: Optional[str] = None
    ) -> Optional[Tuple[Proposal, FactRecord]]:
        async with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return None
            if proposal.status != ProposalStatus.PENDING:
                return None
            proposal.status = ProposalStatus.ACCEPTED
            proposal.resolved_at = time.time()
            proposal.resolved_reason = resolved_reason
            record = self._create_record(proposal.candidate)
            return self._copy_proposal(proposal), self._copy_record(record)

    async def reject_proposal(
        self, proposal_id: str, resolved_reason: Optional[str] = None
    ) -> Optional[Proposal]:
        async with self._lock:
            proposal = self._proposals.get(proposal_id)
            if proposal is None:
                return None
            if proposal.status != ProposalStatus.PENDING:
                return None
            proposal.status = ProposalStatus.REJECTED
            proposal.resolved_at = time.time()
            proposal.resolved_reason = resolved_reason
            return self._copy_proposal(proposal)

    async def get_active(self, subject: str, predicate: str) -> Optional[FactRecord]:
        async with self._lock:
            active_id = self._active_by_key.get((subject, predicate))
            if active_id is None:
                return None
            record = self._records.get(active_id)
            if record is None or record.status != FactStatus.ACTIVE:
                return None
            return self._copy_record(record)

    async def list_subject(self, subject: str) -> List[FactRecord]:
        async with self._lock:
            records = [record for record in self._records.values() if record.subject == subject]
            records.sort(key=lambda item: item.seq)
            return [self._copy_record(record) for record in records]

    async def retract(self, record_id: str, reason: str) -> None:
        """Retract a record without reactivating overridden facts."""
        async with self._lock:
            record = self._records.get(record_id)
            if record is None:
                return
            record.status = FactStatus.RETRACTED
            record.retracted_reason = reason
            key = (record.subject, record.predicate)
            if self._active_by_key.get(key) == record_id:
                self._active_by_key.pop(key, None)

    async def get(self, record_id: str) -> Optional[FactRecord]:
        async with self._lock:
            record = self._records.get(record_id)
            if record is None:
                return None
            return self._copy_record(record)
