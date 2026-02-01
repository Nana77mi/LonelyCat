from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Protocol

from memory.facts import FactCandidate, FactRecord


class MemoryHook(Protocol):
    async def extract_candidates(
        self, session_id: str, transcript: List[Dict[str, Any]]
    ) -> List[FactCandidate]:
        ...

    async def on_committed(
        self,
        session_id: str,
        committed: List[FactRecord],
        transcript: List[Dict[str, Any]],
    ) -> None:
        ...


class RuleBasedMemoryHook:
    _like_pattern = re.compile(r"^我喜欢(.+)$")
    _dislike_pattern = re.compile(r"^我不喜欢(.+)$")
    _call_me_pattern = re.compile(r"^call me\s+(.+)$", re.IGNORECASE)
    _call_me_cn_pattern = re.compile(r"^叫我(.+)$")
    _trim_chars = " \t\n\r,.;!?！？。，“”\"'（）()"

    async def extract_candidates(
        self, session_id: str, transcript: List[Dict[str, Any]]
    ) -> List[FactCandidate]:
        latest_user_message = self._latest_user_message(transcript)
        if not latest_user_message:
            return []

        text = latest_user_message.strip(self._trim_chars)
        candidate = self._match_candidate(session_id, text)
        return [candidate] if candidate else []

    async def on_committed(
        self,
        session_id: str,
        committed: List[FactRecord],
        transcript: List[Dict[str, Any]],
    ) -> None:
        return None

    def _latest_user_message(self, transcript: List[Dict[str, Any]]) -> Optional[str]:
        for event in reversed(transcript):
            if event.get("role") == "user":
                return event.get("content", "")
        return None

    def _match_candidate(self, session_id: str, text: str) -> Optional[FactCandidate]:
        dislike = self._dislike_pattern.match(text)
        if dislike:
            value = dislike.group(1).strip(self._trim_chars)
            if value:
                return FactCandidate(
                    subject="user",
                    predicate="dislikes",
                    object=value,
                    confidence=0.9,
                    source={"session_id": session_id, "note": "rule_based"},
                )
            return None

        like = self._like_pattern.match(text)
        if like:
            value = like.group(1).strip(self._trim_chars)
            if value:
                return FactCandidate(
                    subject="user",
                    predicate="likes",
                    object=value,
                    confidence=0.9,
                    source={"session_id": session_id, "note": "rule_based"},
                )
            return None

        call_me = self._call_me_pattern.match(text)
        if call_me:
            value = call_me.group(1).strip(self._trim_chars)
            if value:
                return FactCandidate(
                    subject="user",
                    predicate="preferred_name",
                    object=value,
                    confidence=0.9,
                    source={"session_id": session_id, "note": "rule_based"},
                )
            return None

        call_me_cn = self._call_me_cn_pattern.match(text)
        if call_me_cn:
            value = call_me_cn.group(1).strip(self._trim_chars)
            if value:
                return FactCandidate(
                    subject="user",
                    predicate="preferred_name",
                    object=value,
                    confidence=0.9,
                    source={"session_id": session_id, "note": "rule_based"},
                )
        return None
