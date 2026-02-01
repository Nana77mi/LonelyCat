from typing import Any, Dict

from protocol.base import BaseModel


class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any]


class ToolResult(BaseModel):
    name: str
    output: Dict[str, Any]
