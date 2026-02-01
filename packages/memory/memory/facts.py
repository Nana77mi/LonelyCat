from __future__ import annotations

import asyncio
import copy
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class FactStatus(Enum):
    ACTIVE = "active"
    OVERRIDDEN = "overridden"
    RETRACTED = "retracted"


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
        self._seq = 0

    def _copy_record(self, record: FactRecord) -> FactRecord:
        try:
            return copy.deepcopy(record)
        except Exception:
            return replace(record)

    async def propose(self, candidate: FactCandidate) -> FactRecord:
        if not 0 <= candidate.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")

        async with self._lock:
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
            return self._copy_record(record)

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
