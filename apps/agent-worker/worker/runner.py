from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Session

from agent_worker.llm import BaseLLM
from worker.db import RunModel
from worker.db_models import MessageModel, MessageRole
from worker.task_context import TaskContext, run_task_with_steps
from worker.tools import ToolRuntime
from worker.tools.catalog import build_catalog_from_settings, get_default_catalog
from worker.tools.web_backends.errors import WebBlockedError, WebParseError


def _clear_invalid_ssl_cert_env_on_windows() -> None:
    """On Windows, unset SSL_CERT_FILE/REQUESTS_CA_BUNDLE if they point to non-existent or Unix-style paths (e.g. from WSL), so httpx uses the default cert store and avoids [Errno 2] No such file or directory."""
    if os.name != "nt":
        return
    for name in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        val = os.environ.get(name)
        if not val:
            continue
        # 若为 Unix 路径（以 / 开头）或路径不存在，则清除，避免 httpx 在 Windows 上报 Errno 2
        if val.strip().startswith("/") or (not os.path.isfile(val) and not os.path.isdir(val)):
            os.environ.pop(name, None)


class TaskRunner:
    """任务执行器
    
    根据 run.type 分发到对应的 handler 执行。
    """

    def __init__(self) -> None:
        """初始化任务执行器"""
        pass

    def _build_memory_client(self):
        """Build MemoryClient when memory is enabled (for facts in long tasks)."""
        try:
            from agent_worker.config import ChatConfig
            from agent_worker.memory_client import MemoryClient
            config = ChatConfig.from_env()
            if config.memory_enabled:
                return MemoryClient()
        except Exception:
            pass
        return None

    def execute(
        self,
        run: RunModel,
        db: Session,
        llm: BaseLLM,
        heartbeat_callback: Callable[[], bool],
        *,
        worker_id: Optional[str] = None,
        lease_seconds: int = 60,
    ) -> Dict[str, Any]:
        """执行任务
        
        约定：返回值必须为 dict 且包含 "ok": bool（表示 task 业务是否成功）；
        main.py 据此决定 RunStatus（SUCCEEDED/FAILED）。
        
        Args:
            run: Run 模型
            db: 数据库会话
            llm: LLM 实例
            heartbeat_callback: 心跳回调函数，返回 True 表示续租成功，False 表示失败
            worker_id: 可选，agent_loop_turn 时用于创建子 run（避免被其他 worker 抢占）
            lease_seconds: 可选，与 worker_id 配合使用
            
        Returns:
            任务执行结果（必须含 ok 字段）
            
        Raises:
            ValueError: 未知的任务类型
            Exception: 任务执行过程中的异常
        """
        # 规范化 type：去除首尾空格，空格替换为下划线（兼容 LLM 返回 "research report" 等）
        run_type = (run.type or "").strip().replace(" ", "_")
        if run_type == "sleep":
            return self._handle_sleep(run, heartbeat_callback)
        elif run_type == "summarize_conversation":
            return self._handle_summarize_conversation(run, db, llm, heartbeat_callback)
        elif run_type == "research_report":
            runtime = None
            catalog = None
            _clear_invalid_ssl_cert_env_on_windows()
            input_json = run.input_json or {}
            snapshot = input_json.get("settings_snapshot") if isinstance(input_json, dict) else None
            if snapshot and isinstance(snapshot, dict):
                catalog = build_catalog_from_settings(snapshot)
                runtime = ToolRuntime(catalog=catalog)
                _backend = (snapshot.get("web") or {}).get("search") or {}
                logger.info(
                    "research_report using settings_snapshot backend=%s",
                    _backend.get("backend", "?"),
                )
            else:
                logger.warning(
                    "research_report run has no settings_snapshot (run_id=%s), using default catalog (env/stub)",
                    getattr(run, "id", "?"),
                )
            try:
                return self._handle_research_report(run, heartbeat_callback, runtime=runtime, llm=llm)
            finally:
                if catalog is not None:
                    catalog.close_providers()
        elif run_type == "edit_docs_propose":
            return self._handle_edit_docs_propose(run, heartbeat_callback)
        elif run_type == "edit_docs_apply":
            return self._handle_edit_docs_apply(run, db, heartbeat_callback)
        elif run_type == "edit_docs_cancel":
            return self._handle_edit_docs_cancel(run, db, heartbeat_callback)
        elif run_type == "run_code_snippet":
            return self._handle_run_code_snippet(run, heartbeat_callback)
        elif run_type == "agent_loop_turn":
            return self._handle_agent_loop_turn(
                run, db, llm, heartbeat_callback,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
            )
        else:
            raise ValueError(f"Unknown task type: {run.type}")

    def _handle_sleep(
        self,
        run: RunModel,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """处理 sleep 任务；使用 run_task_with_steps 统一 trace/steps/artifacts。"""
        input_json = run.input_json
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        seconds_val = input_json.get("seconds")
        if not isinstance(seconds_val, (int, float)) or seconds_val < 0:
            raise ValueError("seconds must be >= 0")
        seconds = int(seconds_val)

        def body(ctx: TaskContext) -> None:
            slept = 0
            with ctx.step("sleep") as step_meta:
                step_meta["seconds_requested"] = seconds
                while slept < seconds:
                    if not heartbeat_callback():
                        raise RuntimeError(
                            "Heartbeat failed, task was taken over by another worker"
                        )
                    time.sleep(1)
                    slept += 1
                step_meta["slept"] = slept
                ctx.result["slept"] = slept
                ctx.artifacts["duration_seconds"] = slept

        return run_task_with_steps(run, "sleep", body)

    def _generate_final_response(self, observation: dict, exec_id: str) -> str:
        """
        PR-3: 根据 observation 生成人类可读回复

        返回格式：
        - stdout 非空：执行结果：{stdout} （exec_id={id}，可在任务详情查看 stdout/stderr/artifacts）
        - 执行失败：执行失败（exit_code=X）：{error} （exec_id={id}，可在任务详情查看完整错误信息）
        - 成功无输出：程序执行成功，但没有输出（提示：请在代码中使用 print() 输出结果）（exec_id={id}，可在任务详情查看 stdout/stderr/artifacts）
        """
        stdout_preview = observation.get("stdout_preview", "").strip()
        stderr_preview = observation.get("stderr_preview", "").strip()
        exit_code = observation.get("exit_code", 0)

        if stdout_preview:
            # stdout 非空：直接返回结果 + exec_id
            lines = [f"执行结果：{stdout_preview}"]
            if observation.get("stdout_truncated"):
                lines.append(f"（输出已截断，exec_id={exec_id}，可在任务详情查看完整 stdout/stderr/artifacts）")
            else:
                lines.append(f"（exec_id={exec_id}，可在任务详情查看 stdout/stderr/artifacts）")
            return "\n".join(lines)
        elif exit_code != 0:
            # 执行失败：显示错误信息 + exec_id
            error_msg = stderr_preview if stderr_preview else "未知错误"
            return f"执行失败（exit_code={exit_code}）：{error_msg}\n（exec_id={exec_id}，可在任务详情查看完整错误信息）"
        else:
            # 执行成功但无输出：提示用户 + exec_id
            return "程序执行成功，但没有输出（提示：请在代码中使用 print() 输出结果）\n（exec_id={}，可在任务详情查看 stdout/stderr/artifacts）".format(exec_id)

    def _fetch_observation(self, exec_id: str) -> dict:
        """
        PR-2: 从 core-api 获取 stdout/stderr/artifacts，只用 exec_id

        返回:
        {
            "stdout_preview": "...",
            "stderr_preview": "...",
            "stdout_truncated": bool,
            "stderr_truncated": bool,
            "stdout_bytes": int,
            "stderr_bytes": int,
            "artifacts_count": int
        }
        """
        core_api_url = os.getenv("CORE_API_URL", "http://localhost:8000")
        observation = {
            "stdout_preview": "",
            "stderr_preview": "",
            "stdout_truncated": False,
            "stderr_truncated": False,
            "stdout_bytes": 0,
            "stderr_bytes": 0,
            "artifacts_count": 0,
        }

        try:
            # 优先尝试聚合 endpoint /observation
            with httpx.Client(timeout=10.0) as client:
                obs_resp = client.get(f"{core_api_url}/sandbox/execs/{exec_id}/observation")
                if obs_resp.status_code == 200:
                    data = obs_resp.json()
                    observation["stdout_preview"] = data["stdout"]["content"][:1000]
                    observation["stderr_preview"] = data["stderr"]["content"][:1000]
                    observation["stdout_truncated"] = data["stdout"]["truncated"]
                    observation["stderr_truncated"] = data["stderr"]["truncated"]
                    observation["stdout_bytes"] = data["stdout"]["bytes"]
                    observation["stderr_bytes"] = data["stderr"]["bytes"]
                    observation["artifacts_count"] = len(data["artifacts"]["files"])
                    return observation
        except Exception as e:
            logger.warning(f"Failed to fetch observation from /observation endpoint: {e}")

        # 降级到 3 个单独请求
        try:
            with httpx.Client(timeout=10.0) as client:
                # GET stdout
                stdout_resp = client.get(f"{core_api_url}/sandbox/execs/{exec_id}/stdout")
                if stdout_resp.status_code == 200:
                    stdout_data = stdout_resp.json()
                    observation["stdout_preview"] = stdout_data["content"][:1000]
                    observation["stdout_truncated"] = stdout_data.get("truncated", False)
                    observation["stdout_bytes"] = stdout_data.get("bytes", 0)

                # GET stderr
                stderr_resp = client.get(f"{core_api_url}/sandbox/execs/{exec_id}/stderr")
                if stderr_resp.status_code == 200:
                    stderr_data = stderr_resp.json()
                    observation["stderr_preview"] = stderr_data["content"][:1000]
                    observation["stderr_truncated"] = stderr_data.get("truncated", False)
                    observation["stderr_bytes"] = stderr_data.get("bytes", 0)

                # GET artifacts
                artifacts_resp = client.get(f"{core_api_url}/sandbox/execs/{exec_id}/artifacts")
                if artifacts_resp.status_code == 200:
                    artifacts_data = artifacts_resp.json()
                    observation["artifacts_count"] = len(artifacts_data.get("files", []))
        except Exception as e:
            logger.warning(f"Failed to fetch observation from individual endpoints: {e}")

        return observation

    def _handle_research_report(
        self,
        run: RunModel,
        heartbeat_callback: Callable[[], bool],
        *,
        runtime: Optional[ToolRuntime] = None,
        llm: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """处理 research_report 任务；stub 搜索/抓取，产出 report + sources（含 provider）+ 可选总结。"""
        input_json = run.input_json
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        query = input_json.get("query")
        if not query or not isinstance(query, str):
            query = (run.title if run.title and isinstance(run.title, str) else None) or "调研"
        query = (query or "").strip() or "调研"
        if not query:
            raise ValueError("input_json['query'] must be a non-empty string")
        max_sources = input_json.get("max_sources", 5)
        if not isinstance(max_sources, int) or max_sources < 1:
            max_sources = 5
        max_sources = min(max_sources, 20)

        if runtime is None:
            runtime = ToolRuntime()

        def body(ctx: TaskContext) -> None:
            self._research_report_body(ctx, query, max_sources, runtime, llm=llm)

        return run_task_with_steps(run, "research_report", body)

    def _research_report_body(
        self,
        ctx: TaskContext,
        query: str,
        max_sources: int,
        runtime: ToolRuntime,
        *,
        llm: Optional[Any] = None,
    ) -> None:
        """research_report 业务逻辑：ToolRuntime 调用 search/fetch_pages，再 extract → dedupe_rank → write_report（含可选总结）。"""
        def _find_search_step() -> Optional[Dict[str, Any]]:
            query_for_match = (query.strip() if isinstance(query, str) else str(query)) or ""
            for s in reversed(ctx._steps):
                if s.get("name") != "tool.web.search":
                    continue
                meta = s.get("meta") or {}
                args_preview = meta.get("args_preview") or ""
                if query_for_match and query_for_match in args_preview:
                    return s
            return next((s for s in reversed(ctx._steps) if s.get("name") == "tool.web.search"), None)

        def _write_search_summary(backend_label: str, result_count: int, search_step: Optional[Dict[str, Any]], ok: bool) -> None:
            ctx.artifacts["search_summary"] = {
                "backend": backend_label,
                "result_count": result_count,
                "ok": ok,
                "error_code": search_step.get("error_code") if search_step else None,
                "detail_code": (search_step.get("meta") or {}).get("detail_code") if search_step else None,
                "duration_ms": search_step.get("duration_ms") if search_step else None,
            }

        def _write_serp_artifacts(exc: object) -> None:
            """WebParseError/WebBlockedError 带 serp_html 时落盘 search/serp.html 与 search/serp.meta.json，并写入 ctx.artifacts['search_serp_artifacts']。"""
            serp_html = getattr(exc, "serp_html", None)
            serp_meta = getattr(exc, "serp_meta", None)
            if not serp_html or not getattr(ctx, "artifact_dir", None):
                return
            search_dir = os.path.join(ctx.artifact_dir, "search")
            try:
                os.makedirs(search_dir, exist_ok=True)
            except OSError:
                return
            serp_html_path = os.path.join(search_dir, "serp.html")
            serp_meta_path = os.path.join(search_dir, "serp.meta.json")
            try:
                with open(serp_html_path, "w", encoding="utf-8") as f:
                    f.write(serp_html)
                if serp_meta is not None:
                    with open(serp_meta_path, "w", encoding="utf-8") as f:
                        json.dump(serp_meta, f, ensure_ascii=False, indent=2)
            except OSError:
                return
            ctx.artifacts["search_serp_artifacts"] = {
                "serp_html": "search/serp.html",
                "serp_meta": "search/serp.meta.json",
            }

        # 提前设置 artifact_dir，以便 WebParseError 时能落盘 SERP
        if getattr(ctx.run, "id", None) is not None:
            base = os.environ.get("WEB_FETCH_ARTIFACT_BASE", ".artifacts")
            ctx.artifact_dir = os.path.join(base, str(ctx.run.id))
            try:
                os.makedirs(ctx.artifact_dir, exist_ok=True)
            except OSError:
                ctx.artifact_dir = None

        try:
            search_result = runtime.invoke(ctx, "web.search", {"query": query})
        except Exception as e:
            if isinstance(e, (WebParseError, WebBlockedError)):
                _write_serp_artifacts(e)
            search_step = _find_search_step()
            _write_search_summary("stub", 0, search_step, ok=False)
            if "search_serp_artifacts" in ctx.artifacts:
                ctx.artifacts["search_summary"]["search_serp_artifacts"] = ctx.artifacts["search_serp_artifacts"]
            serp_meta = getattr(e, "serp_meta", None)
            if isinstance(serp_meta, dict):
                if serp_meta.get("user_agent") is not None:
                    ctx.artifacts["search_summary"]["effective_user_agent"] = (serp_meta.get("user_agent") or "")[:200]
                if serp_meta.get("cooldown_remaining_sec") is not None:
                    ctx.artifacts["search_summary"]["cooldown_remaining_sec"] = max(
                        0, int(serp_meta["cooldown_remaining_sec"])
                    )
            raise
        # web.search canonical 形状为 {"items": [...]}；list 仅历史兼容，后续淘汰
        raw_sources = (
            search_result.get("items", search_result)
            if isinstance(search_result, dict)
            else search_result
        )
        if not isinstance(raw_sources, list):
            raw_sources = []
        raw_sources = raw_sources[:max_sources]
        for s in raw_sources:
            s.setdefault("provider", "stub")
        backend_label = raw_sources[0].get("provider", "stub") if raw_sources else "stub"
        search_step = _find_search_step()
        _write_search_summary(backend_label, len(raw_sources), search_step, ok=True)

        # artifact_dir 已在 search 前设置，供 web.fetch 与 WebParseError 落盘
        # 抓取间隔（秒），0=不启用；从 settings_snapshot 读取，可在设置中调节
        input_json = getattr(ctx.run, "input_json", None) or {}
        snapshot = (input_json.get("settings_snapshot") or {}) if isinstance(input_json, dict) else {}
        fetch_cfg = (snapshot.get("web") or {}).get("fetch") or {}
        raw_delay = fetch_cfg.get("fetch_delay_seconds", 0)
        fetch_delay_seconds = max(0, int(raw_delay)) if isinstance(raw_delay, (int, float)) else 0

        fetch_artifacts_list: List[Dict[str, Any]] = []
        fetch_summaries: List[Dict[str, Any]] = []
        fetch_failure_count = 0
        for i, s in enumerate(raw_sources):
            url = s.get("url", "")
            if not url or not isinstance(url, str) or not (
                url.strip().startswith("http://") or url.strip().startswith("https://")
            ):
                s["content"] = ""
                continue
            url = url.strip()
            # 非首次抓取且启用了间隔时，先等待，降低被同一站点限流概率
            if i > 0 and fetch_delay_seconds > 0:
                time.sleep(fetch_delay_seconds)
            try:
                fetch_result = runtime.invoke(ctx, "web.fetch", {"url": url})
            except Exception as e:
                error_code = getattr(e, "code", None) or type(e).__name__
                s["content"] = ""
                fetch_summaries.append({
                    "url": url,
                    "ok": False,
                    "error_code": str(error_code),
                })
                fetch_failure_count += 1
                continue
            s["content"] = fetch_result.get("text", "") if isinstance(fetch_result, dict) else ""
            if isinstance(fetch_result, dict):
                if fetch_result.get("artifact_paths"):
                    fetch_artifacts_list.append({"url": url, "paths": fetch_result["artifact_paths"]})
                fetch_summaries.append({
                    "url": url,
                    "ok": True,
                    "final_url": fetch_result.get("final_url", url),
                    "status_code": fetch_result.get("status_code", 0),
                    "truncated": bool(fetch_result.get("truncated", False)),
                    "cache_hit": bool(fetch_result.get("cache_hit", False)),
                })
        if fetch_artifacts_list:
            ctx.artifacts["fetch_artifacts"] = fetch_artifacts_list
        if fetch_summaries:
            ctx.artifacts["fetch_summaries"] = fetch_summaries
        if fetch_failure_count > 0:
            ctx.artifacts["fetch_partial_failures"] = True
        # 至少有一次 fetch 成功时视为部分成功，不因单次失败判定整段失败；全部失败时标记为失败
        any_fetch_ok = any(f.get("ok") for f in fetch_summaries)
        if any_fetch_ok and not ctx._ok:
            ctx.set_ok(True)
            ctx.clear_error()
        elif not any_fetch_ok and fetch_summaries:
            # 有 fetch 尝试但全部失败（如 ToolNotFound），异常可能在 step 外抛出，需显式标记失败
            ctx.set_ok(False)
            first_fail = next((f for f in fetch_summaries if not f.get("ok")), None)
            if first_fail and ctx._error is None:
                ctx._error = {
                    "code": first_fail.get("error_code", "Error"),
                    "message": "所有来源抓取均失败",
                    "retryable": True,
                    "step": "tool.web.fetch",
                }

        with ctx.step("extract"):
            # 每段取 snippet 或 content 前 200 字作为候选 excerpt；产出 evidence（quote + source_url + source_index）
            excerpts = [s.get("snippet", "") or (s.get("content", "") or "")[:200] for s in raw_sources]
            evidence = []
            for i, s in enumerate(raw_sources[:10]):
                ex = excerpts[i] if i < len(excerpts) else (s.get("snippet", "") or (s.get("content", "") or "")[:200])
                if not ex:
                    continue
                evidence.append({
                    "quote": (ex[:100] if isinstance(ex, str) else str(ex)[:100]),
                    "source_url": (s.get("url") or "")[:2048],
                    "source_index": i,
                })
            ctx.artifacts["evidence"] = evidence[:10]

        with ctx.step("dedupe_rank"):
            # 简单去重/排序（stub 下可不变）
            ranked = list(raw_sources)

        with ctx.step("write_report"):
            _MAX_URL, _MAX_SNIPPET = 2048, 4096
            report_text = f"# Research Report ({backend_label})\n\nQuery: {query}\n\n## Sources\n\n"
            for i, s in enumerate(ranked, 1):
                u = (s.get("url") or "")[:_MAX_URL]
                # 优先用 web.fetch 的 content，无则用 web.search 的 snippet，使 report 体现“已抓取正文”
                sn = (s.get("content") or s.get("snippet") or "")[:_MAX_SNIPPET]
                report_text += f"- [{s.get('title', '')[:200]}]({u}): {sn}\n"
            evidence_list = ctx.artifacts.get("evidence") or []
            if evidence_list:
                report_text += "\n## Evidence\n\n"
                for e in evidence_list[:5]:
                    q = (e.get("quote") or "")[:200]
                    idx = e.get("source_index", 0)
                    report_text += f"- [{idx}] {q}\n"
            # 若有 LLM，根据上文生成简短总结段落
            if llm and report_text.strip():
                try:
                    excerpt = (report_text.strip())[:4000]
                    summary_result = runtime.invoke(
                        ctx, "text.summarize",
                        {"text": excerpt, "max_length": 500},
                        llm=llm,
                    )
                    summary = ""
                    if isinstance(summary_result, dict) and summary_result.get("summary"):
                        summary = (summary_result["summary"] or "").strip()
                    if summary:
                        report_text += "\n\n## 总结\n\n" + summary
                except Exception as e:
                    logger.warning("research_report summary step failed: %s", e)
            ctx.result["query"] = query
            ctx.result["source_count"] = len(ranked)
            # 若全部为 Stub 抓取（未真实抓取页面），在 report 末尾加说明
            all_stub = all(
                (s.get("content") or "").strip().startswith("Stub content for") or not (s.get("content") or "").strip()
                for s in ranked
            )
            if all_stub and ranked:
                report_text += "\n\n---\n*说明：当前为 Stub 抓取模式，未真实抓取页面正文。若需真实抓取，请设置环境变量 WEB_FETCH_BACKEND=httpx 并重启 agent-worker。*"
            if ctx.artifacts.get("fetch_partial_failures"):
                report_text += "\n\n---\n*部分来源因限流或网络原因未能抓取，以上为已成功抓取/搜索到的内容。*"
            ctx.artifacts["report"] = {"text": report_text, "format": "markdown"}
            sources_out = []
            for s in ranked:
                url = (s.get("url") or "")[:_MAX_URL]
                snippet = (s.get("snippet") or "")[:_MAX_SNIPPET]
                title = (s.get("title") or "")[:512]
                sources_out.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "provider": s.get("provider", "stub"),
                })
            ctx.artifacts["sources"] = sources_out

    def _handle_edit_docs_propose(
        self,
        run: RunModel,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """edit_docs_propose：只读，产出 diff + WAIT_CONFIRM，正常 SUCCEEDED。"""
        input_json = run.input_json or {}
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        target_path = input_json.get("target_path", "/sandbox/example.txt")
        if not isinstance(target_path, str):
            target_path = "/sandbox/example.txt"

        def body(ctx: TaskContext) -> None:
            self._edit_docs_propose_body(ctx, target_path)

        return run_task_with_steps(run, "edit_docs_propose", body)

    def _edit_docs_propose_body(self, ctx: TaskContext, target_path: str) -> None:
        """Steps: read_file → propose_patch → present_diff；产出 artifacts.diff + task_state=WAIT_CONFIRM。"""
        content = ""
        with ctx.step("read_file"):
            content = f"stub content for {target_path}\nline2\n"

        diff_text = ""
        with ctx.step("propose_patch"):
            diff_text = f"""--- a{target_path}
+++ b{target_path}
@@ -1,2 +1,2 @@
-stub content for {target_path}
+stub content for {target_path} (patched)
 line2
"""

        with ctx.step("present_diff"):
            patch_id_full = hashlib.sha256(diff_text.encode()).hexdigest()
            patch_id_short = patch_id_full[:16]
            ctx.result["task_state"] = "WAIT_CONFIRM"
            ctx.artifacts["diff"] = diff_text
            ctx.artifacts["files"] = [target_path]
            ctx.artifacts["patch_id"] = patch_id_full
            ctx.artifacts["patch_id_short"] = patch_id_short
            ctx.artifacts["applied"] = False

    def _handle_edit_docs_apply(
        self,
        run: RunModel,
        db: Session,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """edit_docs_apply：从 parent run 读 diff，执行 apply_patch（v0 仅记录 applied）。"""
        input_json = run.input_json or {}
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        parent_run_id = input_json.get("parent_run_id")
        patch_id = input_json.get("patch_id")
        if not parent_run_id or not isinstance(parent_run_id, str):
            raise ValueError("input_json['parent_run_id'] must be a non-empty string")
        if not patch_id or not isinstance(patch_id, str):
            raise ValueError("input_json['patch_id'] must be a non-empty string")

        parent_run = db.query(RunModel).filter(RunModel.id == parent_run_id).first()
        if not parent_run or not parent_run.output_json:
            raise ValueError(f"Parent run {parent_run_id} not found or has no output")
        artifacts = parent_run.output_json.get("artifacts") or {}
        diff_text = artifacts.get("diff")
        if not diff_text:
            raise ValueError("Parent run artifacts.diff is missing")
        parent_patch_id = artifacts.get("patch_id") or ""
        if not parent_patch_id:
            raise ValueError("Parent run artifacts.patch_id is missing")
        if parent_patch_id != patch_id and (len(parent_patch_id) < 16 or parent_patch_id[:16] != patch_id):
            raise ValueError(
                "PatchMismatch: input.patch_id does not match parent run artifacts.patch_id"
            )

        def body(ctx: TaskContext) -> None:
            self._edit_docs_apply_body(ctx, diff_text, parent_patch_id)

        return run_task_with_steps(run, "edit_docs_apply", body)

    def _edit_docs_apply_body(
        self, ctx: TaskContext, diff_text: str, patch_id: str
    ) -> None:
        """Steps: apply_patch（v0 不落盘，仅设 applied）→ 可选 lint。"""
        with ctx.step("apply_patch"):
            # v0: 不真实写文件，只记录已“应用”
            ctx.artifacts["applied"] = True
            ctx.artifacts["patch_id"] = patch_id
        with ctx.step("lint"):
            ctx.artifacts["lint_ok"] = True

    def _handle_edit_docs_cancel(
        self,
        run: RunModel,
        db: Session,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """edit_docs_cancel：只读、无副作用，记录用户拒绝；artifacts.patch_id + canceled=True。"""
        input_json = run.input_json or {}
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        parent_run_id = input_json.get("parent_run_id")
        if not parent_run_id or not isinstance(parent_run_id, str):
            raise ValueError("input_json['parent_run_id'] must be a non-empty string")
        patch_id = input_json.get("patch_id")
        parent_run = db.query(RunModel).filter(RunModel.id == parent_run_id).first()
        if not parent_run or not parent_run.output_json:
            raise ValueError(f"Parent run {parent_run_id} not found or has no output")
        parent_artifacts = parent_run.output_json.get("artifacts") or {}
        parent_patch_id_full = parent_artifacts.get("patch_id") or ""
        if not patch_id or not isinstance(patch_id, str):
            patch_id = parent_patch_id_full
        if not patch_id:
            raise ValueError("patch_id required or parent run must have artifacts.patch_id")
        # Idempotency: input patch_id (full or short) must match parent
        if parent_patch_id_full != patch_id and (
            len(parent_patch_id_full) < 16 or parent_patch_id_full[:16] != patch_id
        ):
            raise ValueError(
                "PatchMismatch: input.patch_id does not match parent run artifacts.patch_id"
            )
        # Use full patch_id in artifacts so UI tree has consistent propose.patch_id
        patch_id_for_artifacts = parent_patch_id_full if len(parent_patch_id_full) == 64 else patch_id

        def body(ctx: TaskContext) -> None:
            with ctx.step("record_cancel"):
                ctx.result["parent_run_id"] = parent_run_id
                ctx.artifacts["patch_id"] = patch_id_for_artifacts
                ctx.artifacts["canceled"] = True

        return run_task_with_steps(run, "edit_docs_cancel", body)

    def _handle_run_code_snippet(
        self,
        run: RunModel,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """PR6: run_code_snippet — language+code/script → 调用 skill.python.run / skill.shell.run，收集 exec 结果。"""
        input_json = run.input_json or {}
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        conversation_id = input_json.get("conversation_id")
        if not conversation_id or not isinstance(conversation_id, str):
            raise ValueError("input_json['conversation_id'] must be a non-empty string")
        conversation_id = conversation_id.strip()
        if not conversation_id:
            raise ValueError("input_json['conversation_id'] must be a non-empty string")
        language = (input_json.get("language") or "python").strip().lower()
        code = input_json.get("code")
        script = input_json.get("script")
        if language == "python":
            if code is None or (isinstance(code, str) and not code.strip()):
                raise ValueError("input_json['code'] required for language=python")
            tool_name = "skill.python.run"
            args = {"project_id": conversation_id, "code": code if isinstance(code, str) else str(code)}
        elif language == "shell":
            if script is None or (isinstance(script, str) and not script.strip()):
                raise ValueError("input_json['script'] required for language=shell")
            tool_name = "skill.shell.run"
            args = {"project_id": conversation_id, "script": script if isinstance(script, str) else str(script)}
        else:
            raise ValueError("input_json['language'] must be 'python' or 'shell'")
        if input_json.get("timeout_ms") is not None:
            args["timeout_ms"] = int(input_json["timeout_ms"])

        snapshot = input_json.get("settings_snapshot")
        catalog = build_catalog_from_settings(snapshot) if snapshot is not None else get_default_catalog()
        try:
            runtime = ToolRuntime(catalog=catalog)

            def body(ctx: TaskContext) -> None:
                with ctx.step(f"tool.{tool_name}") as step_meta:
                    if not heartbeat_callback():
                        raise RuntimeError("Heartbeat failed")
                    out = runtime.invoke(ctx, tool_name, args)
                    step_meta["provider_id"] = "skills"
                    step_meta["args_preview"] = {k: (v[:200] + "..." if isinstance(v, str) and len(v) > 200 else v) for k, v in args.items()}
                    step_meta["result_preview"] = out
                    ctx.result["exec_id"] = out.get("exec_id")
                    ctx.result["status"] = out.get("status")
                    ctx.result["exit_code"] = out.get("exit_code")
                    ctx.result["artifacts_dir"] = out.get("artifacts_dir")
                    ctx.artifacts["exec"] = out

                    # PR-2: OBSERVE 逻辑 - 只使用 exec_id，不依赖 artifacts_dir
                    exec_id = out.get("exec_id")
                    if exec_id:
                        observation = self._fetch_observation(exec_id)
                        ctx.result["observation"] = observation

                        # 在 steps 中记录 observation step
                        with ctx.step("observation") as obs_meta:
                            obs_meta["exec_id"] = exec_id
                            obs_meta["exit_code"] = out.get("exit_code")
                            obs_meta["stdout_preview"] = observation.get("stdout_preview", "")[:200]
                            obs_meta["stderr_preview"] = observation.get("stderr_preview", "")[:200]
                            obs_meta["stdout_truncated"] = observation.get("stdout_truncated", False)
                            obs_meta["stderr_truncated"] = observation.get("stderr_truncated", False)
                            obs_meta["stdout_bytes"] = observation.get("stdout_bytes", 0)
                            obs_meta["stderr_bytes"] = observation.get("stderr_bytes", 0)
                            obs_meta["artifacts_count"] = observation.get("artifacts_count", 0)

                    # PR-3: RESPOND 逻辑 - 根据 observation 生成最终回复
                    final_response = self._generate_final_response(observation, exec_id)
                    # 写入 ctx.result["reply"]（标准字段，UI 直接读取）
                    ctx.result["reply"] = final_response
                    # 保留 final_response 字段以兼容
                    ctx.result["final_response"] = final_response

                    # 记录到 steps
                    with ctx.step("respond") as respond_meta:
                        respond_meta["response_type"] = "direct"
                        respond_meta["response_preview"] = final_response[:200]
                        respond_meta["exec_id"] = exec_id

                    # 沙箱执行失败（如 exit_code 126）时任务应标为失败，Tasks UI 与 DB 一致
                    if out.get("status") != "SUCCEEDED":
                        exit_code = out.get("exit_code")
                        ctx.set_error(
                            "EXEC_FAILED",
                            f"执行失败 (exit_code={exit_code})，详见 artifacts 或 stdout/stderr。",
                            retryable=False,
                        )
            return run_task_with_steps(run, "run_code_snippet", body)
        finally:
            if catalog is not None and snapshot is not None:
                catalog.close_providers()

    def _handle_agent_loop_turn(
        self,
        run: RunModel,
        db: Session,
        llm: BaseLLM,
        heartbeat_callback: Callable[[], bool],
        *,
        worker_id: Optional[str] = None,
        lease_seconds: int = 60,
    ) -> Dict[str, Any]:
        """agent_loop_turn：单步推进状态机。调用 orchestration-step；若 reply 则返回完成；若 create_run 则标准创建子 run 并 yield，由子 run 完成后唤醒父 run。"""
        base_url = os.getenv("CORE_API_URL", "http://localhost:5173").rstrip("/")
        step_url = f"{base_url}/internal/runs/{run.id}/orchestration-step"
        runs_url = f"{base_url}/runs"
        yield_url = f"{base_url}/internal/runs/{run.id}/yield-waiting-child"

        inp = run.input_json or {}
        step_index = inp.get("step_index", 0)
        previous_output_json = inp.get("previous_output_json")
        run_ids_so_far: List[str] = list(inp.get("run_ids") or [])

        try:
            if not heartbeat_callback():
                return {"ok": False, "error": "Heartbeat failed"}
            with httpx.Client(timeout=60.0) as client:
                step_resp = client.post(
                    step_url,
                    json={"step_index": step_index, "previous_output_json": previous_output_json},
                )
            if step_resp.status_code != 200:
                return {
                    "ok": False,
                    "error": f"orchestration-step returned {step_resp.status_code}: {step_resp.text[:500]}",
                }
            step_data = step_resp.json()
            action = step_data.get("action")
            if action == "reply":
                final_reply = step_data.get("final_reply") or "任务已完成"
                return {
                    "ok": True,
                    "final_reply": final_reply,
                    "run_ids": run_ids_so_far,
                }
            if action == "wait":
                return {"ok": True, "yielded": True}
            if action != "create_run":
                return {
                    "ok": True,
                    "final_reply": "任务已完成",
                    "run_ids": run_ids_so_far,
                }
            run_request = step_data.get("run_request")
            if not run_request:
                return {"ok": False, "error": "orchestration-step create_run missing run_request"}
            with httpx.Client(timeout=30.0) as client:
                create_resp = client.post(runs_url, json=run_request)
            if create_resp.status_code != 200:
                return {
                    "ok": False,
                    "error": f"POST /runs returned {create_resp.status_code}: {create_resp.text[:500]}",
                }
            create_data = create_resp.json()
            run_obj = create_data.get("run") or create_data
            child_run_id = run_obj.get("id") if isinstance(run_obj, dict) else None
            if not child_run_id:
                return {"ok": False, "error": "POST /runs did not return run.id"}
            new_run_ids = run_ids_so_far + [child_run_id]
            with httpx.Client(timeout=10.0) as client:
                yield_resp = client.post(
                    yield_url,
                    json={
                        "child_run_id": child_run_id,
                        "step_index": step_index,
                        "run_ids": new_run_ids,
                    },
                )
            if yield_resp.status_code != 204:
                return {
                    "ok": False,
                    "error": f"yield-waiting-child returned {yield_resp.status_code}: {yield_resp.text[:500]}",
                }
            return {"ok": True, "yielded": True}
        except httpx.RequestError as e:
            return {"ok": False, "error": f"Request to core-api failed: {e}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def _handle_summarize_conversation(
        self,
        run: RunModel,
        db: Session,
        llm: BaseLLM,
        heartbeat_callback: Callable[[], bool],
    ) -> Dict[str, Any]:
        """处理 summarize_conversation 任务；使用 run_task_with_steps 统一 trace/steps/artifacts。"""
        input_json = run.input_json
        if not isinstance(input_json, dict):
            raise ValueError("input_json must be a dict")
        conversation_id = input_json.get("conversation_id")
        if not conversation_id or not isinstance(conversation_id, str):
            raise ValueError("input_json['conversation_id'] must be a non-empty string")
        max_messages = input_json.get("max_messages", 20)
        if not isinstance(max_messages, int) or max_messages < 1:
            raise ValueError("input_json['max_messages'] must be a positive integer")
        max_messages = max(10, min(50, max_messages))

        def body(ctx: TaskContext) -> None:
            self._summarize_body(ctx, db, llm, conversation_id, max_messages)

        out = run_task_with_steps(run, "summarize_conversation", body)
        # Backward compat: top-level summary / message_count / conversation_id / facts_snapshot_*
        out["summary"] = out.get("result", {}).get("summary", "")
        out["message_count"] = out.get("result", {}).get("message_count", 0)
        out["conversation_id"] = out.get("result", {}).get("conversation_id", "")
        if out.get("facts_snapshot_id") is not None:
            pass  # already set by TaskContext
        if not out.get("ok") and isinstance(out.get("error"), dict):
            out["error"] = out["error"].get("message", str(out["error"]))
        return out

    def _summarize_body(
        self,
        ctx: TaskContext,
        db: Session,
        llm: BaseLLM,
        conversation_id: str,
        max_messages: int,
    ) -> None:
        """Business logic for summarize_conversation; uses ctx.step() and sets result/artifacts."""
        messages: List[Any] = []
        with ctx.step("fetch_messages"):
            messages = (
                db.query(MessageModel)
                .filter(MessageModel.conversation_id == conversation_id)
                .filter(MessageModel.role.in_([MessageRole.USER, MessageRole.ASSISTANT]))
                .order_by(MessageModel.created_at.desc())
                .limit(max_messages)
                .all()
            )
            messages = list(reversed(messages))

        if not messages:
            raise ValueError(f"No messages found for conversation {conversation_id}")

        active_facts: List[dict] = []
        facts_snapshot_id = ""
        facts_snapshot_source = "computed"
        with ctx.step("fetch_facts") as meta:
            from agent_worker.utils.facts import fetch_active_facts_via_api
            from agent_worker.utils.facts_format import compute_facts_snapshot_id

            base_url = os.getenv("LONELYCAT_CORE_API_URL", "http://localhost:5173")
            active_facts = fetch_active_facts_via_api(
                base_url,
                conversation_id=conversation_id,
            )
            input_json = ctx.run.input_json or {}
            input_snapshot_id = input_json.get("facts_snapshot_id")
            if (
                input_snapshot_id
                and isinstance(input_snapshot_id, str)
                and len(input_snapshot_id) == 64
                and all(c in "0123456789abcdef" for c in input_snapshot_id.lower())
            ):
                facts_snapshot_id = input_snapshot_id
                facts_snapshot_source = "input_json"
            else:
                facts_snapshot_id = compute_facts_snapshot_id(active_facts)
                facts_snapshot_source = "computed"
            ctx.set_facts_snapshot(facts_snapshot_id, facts_snapshot_source)
            meta["facts_snapshot_id"] = facts_snapshot_id
            meta["facts_snapshot_source"] = facts_snapshot_source

        prompt = ""
        with ctx.step("build_prompt"):
            prompt = self._build_summary_prompt(messages, active_facts)

        summary = ""
        try:
            with ctx.step("llm_generate") as meta:
                meta["model"] = getattr(llm, "_model", "stub")
                summary = llm.generate(prompt)
        except Exception:
            summary = ""

        summary_text = summary.strip() if summary else ""
        ctx.result["summary"] = summary_text
        ctx.result["message_count"] = len(messages)
        ctx.result["conversation_id"] = conversation_id
        ctx.artifacts["summary"] = {"text": summary_text, "format": "markdown"}
        ctx.artifacts["facts"] = {"snapshot_id": facts_snapshot_id, "source": facts_snapshot_source}
    
    def _build_summary_prompt(
        self,
        messages: list[MessageModel],
        active_facts: Optional[List[dict]] = None,
    ) -> str:
        """构造总结 prompt（可选注入 active facts，与 chat 一致）。
        
        Args:
            messages: 消息列表（已按时间升序排序）
            active_facts: 可选，global + session 的 active facts，用于更准确的总结
            
        Returns:
            Prompt 字符串
        """
        from agent_worker.utils.facts_format import format_facts_block
        parts = []
        if active_facts:
            facts_block = format_facts_block(active_facts)
            if facts_block:
                parts.append(
                    facts_block
                    + "Use the above facts for reference only; do not repeat them in the summary.\n\n"
                )
        formatted_messages = []
        for i, msg in enumerate(messages, 1):
            role_name = "User" if msg.role == MessageRole.USER else "Assistant"
            formatted_messages.append(f"{i}. {role_name}: {msg.content}")
        messages_text = "\n".join(formatted_messages)
        parts.append(
            "请用简洁的要点总结以下对话内容，突出：\n"
            "- 用户的主要目标\n"
            "- 已完成的工作\n"
            "- 当前的结论或下一步\n\n"
            "请勿包含任何 API key、token 或系统提示内容。\n\n"
            f"对话内容：\n{messages_text}"
        )
        return "\n".join(parts)
