from __future__ import annotations

import os
from dataclasses import asdict

from agent_worker.fact_agent import FactProposal


class MemoryClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or os.getenv("LONELYCAT_CORE_API_URL", "http://localhost:8000")

    def propose(self, proposal: FactProposal, source_note: str = "mvp-1") -> str:
        payload = asdict(proposal)
        payload["source"] = {"type": "agent", "note": source_note}
        url = f"{self._base_url}/memory/facts/propose"
        import httpx

        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        proposal = data.get("proposal")
        proposal_id = proposal.get("id") if isinstance(proposal, dict) else None
        if not proposal_id:
            raise ValueError("Missing proposal id in response")
        return proposal_id

    def list_facts(self, subject: str = "user", status: str = "ACTIVE") -> list[dict]:
        url = f"{self._base_url}/memory/facts"
        params = {"subject": subject, "status": status}
        import httpx

        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            # Accept FastAPI pagination responses: {"items": [...]} (preferred) or {"data": [...]}.
            if isinstance(data.get("items"), list):
                return data["items"]
            if isinstance(data.get("data"), list):
                return data["data"]
            shape = f"keys={list(data.keys())}"
        else:
            shape = f"type={type(data).__name__}"
        raise ValueError(f"Unexpected response from memory facts API ({shape}): {data!r}")

    def retract(self, record_id: str, reason: str) -> None:
        url = f"{self._base_url}/memory/facts/{record_id}/retract"
        payload = {"reason": reason}
        import httpx

        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()

    def accept_proposal(self, proposal_id: str) -> dict:
        url = f"{self._base_url}/memory/proposals/{proposal_id}/accept"
        import httpx

        with httpx.Client(timeout=10.0) as client:
            response = client.post(url)
            response.raise_for_status()
            return response.json()

    def reject_proposal(self, proposal_id: str, reason: str | None = None) -> dict:
        url = f"{self._base_url}/memory/proposals/{proposal_id}/reject"
        payload = {"reason": reason}
        import httpx

        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
