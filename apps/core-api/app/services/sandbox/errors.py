"""Sandbox 错误类型：403 POLICY_DENIED、400 INVALID_ARGUMENT、500 RUNTIME_ERROR。"""
from __future__ import annotations


class SandboxError(Exception):
    """基类，带 code + message 供 API 返回 error_reason。"""
    code: str = "SANDBOX_ERROR"
    http_status: int = 500

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code

    def to_reason(self) -> dict:
        return {"code": self.code, "message": self.message}


class PolicyDeniedError(SandboxError):
    """越权/不允许的 command → 403。"""
    code = "POLICY_DENIED"
    http_status = 403


class InvalidArgumentError(SandboxError):
    """路径穿越、字段错误 → 400。"""
    code = "INVALID_ARGUMENT"
    http_status = 400


class SandboxRuntimeError(SandboxError):
    """docker 失败、IO 写失败 → 500。"""
    code = "RUNTIME_ERROR"
    http_status = 500
