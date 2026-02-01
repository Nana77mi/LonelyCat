from typing import List

from pydantic import BaseModel


class SkillManifest(BaseModel):
    name: str
    version: str
    description: str | None = None
    entrypoint: str | None = None
    capabilities: List[str] = []
