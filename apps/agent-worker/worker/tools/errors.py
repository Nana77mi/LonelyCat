"""工具体系统一错误：ToolNotFound 等，供 runtime 与 provider 共用。"""


class ToolNotFoundError(ValueError):
    """Tool not in catalog or no implementation; error.code = ToolNotFound for UI/debug."""

    code: str = "ToolNotFound"

    def __init__(self, name: str, detail: str = "") -> None:
        self.name = name
        self.detail = detail
        super().__init__(f"Tool not found: {name}" + (f" ({detail})" if detail else ""))
