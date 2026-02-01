from typing import Any, Dict

from pydantic import BaseModel


class InboundEvent(BaseModel):
    source: str
    payload: Dict[str, Any]


class OutboundMessage(BaseModel):
    target: str
    content: str
