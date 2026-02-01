from typing import List

from protocol.base import BaseModel


class MCPServerManifest(BaseModel):
    name: str
    version: str
    description: str | None = None
    endpoints: List[str] = []
