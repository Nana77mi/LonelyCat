from __future__ import annotations

import os
from typing import Any

import httpx

from agent_worker.llm.base import BaseLLM


class OpenAIChatLLM(BaseLLM):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        self._api_key = api_key
        self._model = model
        self._timeout = 15.0
        self._base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

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
            raise RuntimeError(f"OpenAI request failed: {exc}") from exc
        except ValueError as exc:
            raise RuntimeError("OpenAI response was not valid JSON") from exc

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenAI response missing expected content") from exc
