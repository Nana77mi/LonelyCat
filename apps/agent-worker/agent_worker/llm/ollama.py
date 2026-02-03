from __future__ import annotations

import time
from typing import Any

import httpx

from agent_worker.llm.base import BaseLLM


class OllamaLLM(BaseLLM):
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        timeout_s: float = 30.0,
        max_retries: int = 2,
        retry_backoff_s: float = 0.8,
        max_prompt_chars: int = 20000,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(max_prompt_chars=max_prompt_chars)
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._retry_backoff_s = retry_backoff_s
        self._transport = transport

    def generate(self, prompt: str) -> str:
        url = f"{self._base_url}/api/chat"
        prompt = self._trim_prompt(prompt)
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        data = self._post_with_retry(url, payload)
        try:
            return data["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("ollama response missing expected content") from exc

    def generate_messages(self, messages: list[dict[str, str]]) -> str:
        """Generate response from a list of messages.
        
        Ollama API natively supports messages format with roles: system, user, assistant.
        Messages are passed directly to the API without conversion.
        """
        url = f"{self._base_url}/api/chat"
        # Ollama API natively supports messages format - pass directly
        # Validate and format messages (role must be system/user/assistant)
        formatted_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            # Ollama API accepts system, user, assistant roles
            if role not in ("system", "user", "assistant"):
                raise ValueError(f"Ollama API only accepts 'system', 'user', or 'assistant' roles, got '{role}'")
            formatted_messages.append({"role": role, "content": content})
        
        payload = {
            "model": self._model,
            "messages": formatted_messages,
            "stream": False,
        }
        data = self._post_with_retry(url, payload)
        try:
            return data["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("ollama response missing expected content") from exc

    def _post_with_retry(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                with httpx.Client(
                    timeout=self._timeout_s, transport=self._transport
                ) as client:
                    response = client.post(url, json=payload)
            except httpx.TimeoutException:
                if attempt >= self._max_retries:
                    raise RuntimeError("ollama request timed out")
                self._sleep_backoff(attempt)
                attempt += 1
                continue
            except httpx.HTTPError as exc:
                raise RuntimeError(f"ollama request failed: {exc}") from exc

            if response.status_code == 429 or response.status_code >= 500:
                if attempt >= self._max_retries:
                    raise RuntimeError(
                        f"ollama request failed with status {response.status_code}"
                    )
                self._sleep_backoff(attempt)
                attempt += 1
                continue

            if 400 <= response.status_code < 500:
                hint = "check model name"
                if response.status_code == 404:
                    hint = "check model name or base url"
                raise ValueError(
                    f"ollama error status={response.status_code} hint={hint}"
                )

            try:
                return response.json()
            except ValueError as exc:
                raise RuntimeError("ollama response was not valid JSON") from exc

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self._retry_backoff_s * (2**attempt)
        if delay > 0:
            time.sleep(delay)
