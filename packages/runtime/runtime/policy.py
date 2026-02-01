class PolicyDenied(Exception):
    pass


class PolicyEngine:
    def __init__(self, allow: dict[str, bool] | None = None) -> None:
        self._allow = dict(allow or {})

    def is_allowed(self, tool_name: str, ctx: dict) -> bool:
        _ = ctx
        return self._allow.get(tool_name, False)
