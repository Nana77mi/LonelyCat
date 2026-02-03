"""text.summarize: reuse LLM for summarization."""

from __future__ import annotations

from typing import Any, Dict

from agent_worker.llm import BaseLLM


def text_summarize_impl(llm: BaseLLM, args: Dict[str, Any]) -> Dict[str, Any]:
    """Call LLM to summarize text."""
    text = args.get("text", "")
    max_length = args.get("max_length", 500)
    if not text:
        return {"summary": "", "truncated": False}
    prompt = f"请用简洁的要点总结以下内容（不超过 {max_length} 字）：\n\n{text}"
    summary = llm.generate(prompt)
    return {"summary": (summary or "").strip()[:max_length], "truncated": False}
