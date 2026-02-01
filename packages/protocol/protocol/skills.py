from typing import List

from protocol.base import BaseModel


class SkillManifest(BaseModel):
    name: str
    version: str
    description: str | None = None
    entrypoint: str | None = None
    capabilities: List[str] = []
