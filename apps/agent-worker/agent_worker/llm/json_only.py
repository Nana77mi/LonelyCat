from __future__ import annotations

import json
import re

from agent_worker.llm.base import BaseLLM

JSON_ONLY_PREFIX = "You must reply with valid JSON only. Do not add extra text."
JSON_ONLY_SUFFIX = "If unsure, reply with JSON: {\"action\": \"NO_ACTION\"}."


class JsonOnlyLLMWrapper(BaseLLM):
    def __init__(self, llm: BaseLLM) -> None:
        max_prompt_chars = getattr(llm, "_max_prompt_chars", 20000)
        super().__init__(max_prompt_chars=max_prompt_chars)
        self._llm = llm

    def generate(self, prompt: str) -> str:
        prompt = self._wrap_prompt(prompt)
        raw = self._llm.generate(prompt)
        if raw is None:
            return "NO_ACTION"
        if not isinstance(raw, str):
            raw = str(raw)
        candidate = _extract_json_block(raw.strip())
        if not candidate:
            return "NO_ACTION"
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return "NO_ACTION"
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))

    def _wrap_prompt(self, prompt: str) -> str:
        return f"{JSON_ONLY_PREFIX}\n{prompt}\n{JSON_ONLY_SUFFIX}"


def _extract_json_block(text: str) -> str | None:
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    json_match = re.search(r"\{.*\}", text, re.DOTALL)
    if json_match:
        return json_match.group(0)
    return None
