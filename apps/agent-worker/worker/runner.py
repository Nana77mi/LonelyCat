from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

from sqlalchemy.orm import Session

from agent_worker.llm import BaseLLM
from worker.db import RunModel
from worker.db_models import MessageModel, MessageRole
from worker.task_context import TaskContext, run_task_with_steps
from worker.tools import ToolRuntime
from worker.tools.catalog import build_catalog_from_settings


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
    ) -> Dict[str, Any]:
        """执行任务
        
        约定：返回值必须为 dict 且包含 "ok": bool（表示 task 业务是否成功）；
        main.py 据此决定 RunStatus（SUCCEEDED/FAILED）。
        
        Args:
            run: Run 模型
            db: 数据库会话
            llm: LLM 实例
            heartbeat_callback: 心跳回调函数，返回 True 表示续租成功，False 表示失败
            
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
                return self._handle_research_report(run, heartbeat_callback, runtime=runtime)
            finally:
                if catalog is not None:
                    catalog.close_providers()
        elif run_type == "edit_docs_propose":
            return self._handle_edit_docs_propose(run, heartbeat_callback)
        elif run_type == "edit_docs_apply":
            return self._handle_edit_docs_apply(run, db, heartbeat_callback)
        elif run_type == "edit_docs_cancel":
            return self._handle_edit_docs_cancel(run, db, heartbeat_callback)
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

    def _handle_research_report(
        self,
        run: RunModel,
        heartbeat_callback: Callable[[], bool],
        *,
        runtime: Optional[ToolRuntime] = None,
    ) -> Dict[str, Any]:
        """处理 research_report 任务；stub 搜索/抓取，产出 report + sources（含 provider）。"""
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
            self._research_report_body(ctx, query, max_sources, runtime)

        return run_task_with_steps(run, "research_report", body)

    def _research_report_body(
        self,
        ctx: TaskContext,
        query: str,
        max_sources: int,
        runtime: ToolRuntime,
    ) -> None:
        """research_report 业务逻辑：ToolRuntime 调用 search/fetch_pages，再 extract → dedupe_rank → write_report。"""
        search_result = runtime.invoke(ctx, "web.search", {"query": query})
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
        # 实际使用的搜索后端：用于 report 标题展示（来自 WebProvider 的 normalize，非硬编码）
        backend_label = raw_sources[0].get("provider", "stub") if raw_sources else "stub"

        # 可选：为本 run 设置 artifact_dir，供 web.fetch 落盘 raw.html / extracted.txt / meta.json（PR#3）
        if getattr(ctx.run, "id", None) is not None:
            base = os.environ.get("WEB_FETCH_ARTIFACT_BASE", ".artifacts")
            ctx.artifact_dir = os.path.join(base, str(ctx.run.id))
            try:
                os.makedirs(ctx.artifact_dir, exist_ok=True)
            except OSError:
                ctx.artifact_dir = None

        fetch_artifacts_list: List[Dict[str, Any]] = []
        fetch_summaries: List[Dict[str, Any]] = []
        for s in raw_sources:
            url = s.get("url", "")
            if not url or not isinstance(url, str) or not (
                url.strip().startswith("http://") or url.strip().startswith("https://")
            ):
                s["content"] = ""
                continue
            url = url.strip()
            fetch_result = runtime.invoke(ctx, "web.fetch", {"url": url})
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
            ctx.result["query"] = query
            ctx.result["source_count"] = len(ranked)
            # 若全部为 Stub 抓取（未真实抓取页面），在 report 末尾加说明
            all_stub = all(
                (s.get("content") or "").strip().startswith("Stub content for") or not (s.get("content") or "").strip()
                for s in ranked
            )
            if all_stub and ranked:
                report_text += "\n\n---\n*说明：当前为 Stub 抓取模式，未真实抓取页面正文。若需真实抓取，请设置环境变量 WEB_FETCH_BACKEND=httpx 并重启 agent-worker。*"
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
