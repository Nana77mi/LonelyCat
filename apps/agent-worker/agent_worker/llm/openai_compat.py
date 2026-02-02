from __future__ import annotations

import os
from typing import Any

import httpx

from agent_worker.llm.base import BaseLLM


class OpenAICompatLLM(BaseLLM):
    def __init__(self) -> None:
        self._base_url = os.getenv("LLM_BASE_URL")
        self._model = os.getenv("LLM_MODEL")
        self._api_key = os.getenv("LLM_API_KEY")
        timeout_value = os.getenv("LLM_TIMEOUT", "30")

        if not self._base_url:
            raise RuntimeError("LLM_BASE_URL must be set for openai_compat")
        if not self._model:
            raise RuntimeError("LLM_MODEL must be set for openai_compat")
        if not self._api_key:
            raise RuntimeError("LLM_API_KEY must be set for openai_compat")

        try:
            self._timeout = float(timeout_value)
        except ValueError as exc:
            raise RuntimeError("LLM_TIMEOUT must be a number") from exc

    def generate(self, prompt: str) -> str:
        url = f"{self._base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data: Any = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("LLM response was not valid JSON") from exc

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LLM response missing expected content") from exc
