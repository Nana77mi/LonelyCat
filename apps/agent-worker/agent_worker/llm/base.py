from __future__ import annotations

from abc import ABC, abstractmethod


class BaseLLM(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        """
        Takes a fully constructed prompt string.
        Returns raw text output from the model (string).
        Must NOT parse JSON here.
        """
        raise NotImplementedError
