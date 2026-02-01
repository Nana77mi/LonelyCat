from __future__ import annotations

import os
from dataclasses import asdict

from agent_worker.fact_agent import FactProposal


class MemoryClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or os.getenv("LONELYCAT_CORE_API_URL", "http://localhost:8000")

    def propose(self, proposal: FactProposal) -> str:
        payload = asdict(proposal)
        payload["source"] = {"type": "agent", "note": "mvp-1"}
        url = f"{self._base_url}/memory/facts/propose"
        import httpx

        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        record_id = data.get("id")
        if not record_id:
            raise ValueError("Missing record id in response")
        return record_id
