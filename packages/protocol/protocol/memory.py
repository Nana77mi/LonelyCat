from protocol.base import BaseModel


class FactCandidate(BaseModel):
    content: str
    confidence: float


class FactRecord(BaseModel):
    content: str
    source: str
    metadata: dict | None = None
