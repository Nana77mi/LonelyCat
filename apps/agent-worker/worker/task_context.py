"""TaskResult v0 helper: run_task_with_steps + TaskContext.

Handlers only write business logic; the framework guarantees trace_id,
steps (context manager), ok/error, and artifacts/result structure.
"""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Dict, List, Optional

# 输出大小超过此阈值时在 trace 中记录 task.output.too_large（不阻塞）
OUTPUT_SIZE_WARN_THRESHOLD = 1024 * 1024  # 1 MiB

from protocol.run_constants import is_valid_trace_id

from agent_worker.trace import TraceCollector
from worker.db import RunModel

VERSION = "task_result_v0"


class TaskContext:
    """Context for a single task run: trace_id, trace, steps, result, artifacts.

    Use ctx.step("name") as a context manager to record steps; set result/artifacts
    on ctx; build_output() returns the full task_result_v0 dict.
    """

    def __init__(self, run: RunModel, task_type: str) -> None:
        self.run = run
        self.task_type = task_type
        input_json = run.input_json or {}
        raw_trace_id = input_json.get("trace_id")
        self.trace_id: str = (
            raw_trace_id if is_valid_trace_id(raw_trace_id) else uuid.uuid4().hex
        )
        self.trace = TraceCollector.from_env_with_trace_id(self.trace_id)
        self._steps: List[Dict[str, Any]] = []
        self._result: Dict[str, Any] = {}
        self._artifacts: Dict[str, Any] = {}
        self._ok = True
        self._error: Optional[Dict[str, Any]] = None
        self._facts_snapshot_id: Optional[str] = None
        self._facts_snapshot_source: Optional[str] = None
        self.artifact_dir: Optional[str] = None  # 可选；research_report 时设为 run 专属目录，供 web.fetch 落盘

    def set_ok(self, ok: bool) -> None:
        """允许 handler 在部分成功场景下将任务标记为成功（如 research_report 部分 fetch 失败仍产出报告）。"""
        self._ok = ok

    def clear_error(self) -> None:
        """清除顶层 error，用于部分成功时不再展示整段失败。"""
        self._error = None

    @property
    def result(self) -> Dict[str, Any]:
        return self._result

    @property
    def artifacts(self) -> Dict[str, Any]:
        return self._artifacts

    def set_facts_snapshot(self, snapshot_id: str | None, source: str | None) -> None:
        self._facts_snapshot_id = snapshot_id
        self._facts_snapshot_source = source

    @contextmanager
    def step(self, name: str):
        """Record a step. Yields a dict for meta (handler can set keys). On exception appends failure, sets top-level error, re-raises."""
        t0 = time.perf_counter()
        self.trace.record(f"{self.task_type}.{name}")
        step_meta: Dict[str, Any] = {}
        step_ok = True
        error_code: Optional[str] = None
        try:
            yield step_meta
        except Exception as e:
            step_ok = False
            error_code = getattr(e, "code", None) or type(e).__name__ or "Error"
            detail_code = getattr(e, "detail_code", None)
            if detail_code is not None:
                step_meta["detail_code"] = detail_code
            if self._ok:
                self._ok = False
                raw_msg = str(e)[:500]
                # 被限流/封禁时给出明确用户提示，便于与“查太多被禁”区分
                if str(error_code) == "WebBlocked":
                    message = "请求过于频繁或被限制（如 403/429），请稍后再试。"
                    retryable = True
                else:
                    message = raw_msg
                    retryable = False
                self._error = {
                    "code": str(error_code),
                    "message": message,
                    "retryable": retryable,
                    "step": name,
                }
            raise
        finally:
            duration_ms = max(0, int((time.perf_counter() - t0) * 1000))
            self._steps.append({
                "name": name,
                "ok": step_ok,
                "duration_ms": duration_ms,
                "error_code": error_code,
                "meta": step_meta,
            })

    def build_output(self) -> Dict[str, Any]:
        """Build full task_result_v0 output dict."""
        out: Dict[str, Any] = {
            "version": VERSION,
            "ok": self._ok,
            "trace_id": self.trace_id,
            "task_type": self.task_type,
            "result": self._result,
            "artifacts": self._artifacts,
            "steps": self._steps,
            "trace_lines": self.trace.render_lines(),
            "error": self._error,
        }
        if self._facts_snapshot_id is not None:
            out["facts_snapshot_id"] = self._facts_snapshot_id
        if self._facts_snapshot_source is not None:
            out["facts_snapshot_source"] = self._facts_snapshot_source
        try:
            payload = json.dumps(out, default=str, ensure_ascii=False)
            if len(payload) > OUTPUT_SIZE_WARN_THRESHOLD:
                self.trace.record("task.output.too_large", str(len(payload)))
                out["trace_lines"] = self.trace.render_lines()
        except Exception:
            pass
        return out


def run_task_with_steps(
    run: RunModel,
    task_type: str,
    handler_fn: Callable[[TaskContext], None],
) -> Dict[str, Any]:
    """Run a task with unified trace_id, steps, and output structure.

    Creates TaskContext, calls handler_fn(ctx); handler uses ctx.step("name")
    and sets ctx.result / ctx.artifacts / ctx.set_facts_snapshot. Returns
    full task_result_v0 dict. On handler exception, still returns build_output()
    so failed runs remain diagnosable (ok=false, error, steps, trace_lines).
    """
    ctx = TaskContext(run, task_type)
    try:
        handler_fn(ctx)
    except Exception:
        # Step context already recorded failure and set ctx._ok/_error; re-raise
        # only after returning so caller can get structured output for storage.
        pass
    return ctx.build_output()
