from __future__ import annotations

from abc import ABC, abstractmethod


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

    def decide(self, prompt: str) -> str:
        return self.generate(prompt)

    def _trim_prompt(self, prompt: str) -> str:
        if self._max_prompt_chars <= 0:
            return prompt
        if len(prompt) <= self._max_prompt_chars:
            return prompt
        return prompt[: self._max_prompt_chars]
