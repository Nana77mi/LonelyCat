from __future__ import annotations

from typing import Any, ClassVar, get_args, get_origin


try:
    from pydantic import BaseModel as PydanticBaseModel
except ModuleNotFoundError:  # pragma: no cover - offline tests use the stub
    PydanticBaseModel = None


class BaseModel:
    __pydantic__: ClassVar[type | None] = PydanticBaseModel

    def __init__(self, **data: Any) -> None:
        annotations = getattr(self, "__annotations__", {})
        for field in annotations:
            if field not in data and not self._field_has_default(field, annotations[field]):
                raise TypeError(f"Missing required field: {field}")
        for key, value in data.items():
            setattr(self, key, value)

    @classmethod
    def _field_has_default(cls, field: str, annotation: Any) -> bool:
        if field in cls.__dict__:
            return True
        origin = get_origin(annotation)
        if origin is None:
            return annotation is None or annotation is type(None)
        args = get_args(annotation)
        return type(None) in args

    @classmethod
    def model_json_schema(cls) -> dict:
        annotations = getattr(cls, "__annotations__", {})
        properties = {name: {"type": "string"} for name in annotations}
        return {"title": cls.__name__, "type": "object", "properties": properties}


if PydanticBaseModel is not None:

    class BaseModel(PydanticBaseModel):  # type: ignore[no-redef]
        pass
