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
        Takes a list of messages and returns raw text output from the model.
        
        Message format:
        - Each message must be a dict with "role" and "content" keys
        - role: Must be one of "system", "user", or "assistant" (case-sensitive)
        - content: Must be a string
        
        Args:
            messages: List of message dicts in format [{"role": "system|user|assistant", "content": "..."}, ...]
            
        Returns:
            Raw text output from the model (string)
            
        Note:
            Default implementation converts messages to prompt string for backward compatibility.
            Subclasses should override this for better message handling.
        """
        # Validate message format
        for msg in messages:
            if not isinstance(msg, dict):
                raise ValueError(f"Message must be a dict, got {type(msg)}")
            role = msg.get("role", "user")
            if role not in ("system", "user", "assistant"):
                raise ValueError(f"Role must be 'system', 'user', or 'assistant', got '{role}'")
            content = msg.get("content", "")
            if not isinstance(content, str):
                raise ValueError(f"Content must be a string, got {type(content)}")
        
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
