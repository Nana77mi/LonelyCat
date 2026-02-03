from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


DEFAULT_MAX_PROMPT_CHARS = 20000


class BaseLLM(ABC):
    def __init__(self, max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS) -> None:
        self._max_prompt_chars = max_prompt_chars

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """
        Takes a fully constructed prompt string.
        Returns raw text output from the model (string).
        Must NOT parse JSON here.
        """
        raise NotImplementedError

    def generate_messages(self, messages: list[dict[str, str]]) -> str:
        """
        Takes a list of messages in format [{"role": "user|assistant|system", "content": "..."}, ...].
        Returns raw text output from the model (string).
        Default implementation converts messages to prompt string for backward compatibility.
        Subclasses should override this for better message handling.
        """
        # Default implementation: convert messages to prompt string
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                prompt_parts.append(f"System: {content}")
            elif role == "user":
                prompt_parts.append(f"User: {content}")
            elif role == "assistant":
                prompt_parts.append(f"Assistant: {content}")
        prompt = "\n\n".join(prompt_parts)
        return self.generate(prompt)

    def decide(self, prompt: str) -> str:
        return self.generate(prompt)

    def _trim_prompt(self, prompt: str) -> str:
        if self._max_prompt_chars <= 0:
            return prompt
        if len(prompt) <= self._max_prompt_chars:
            return prompt
        return prompt[: self._max_prompt_chars]
