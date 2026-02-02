from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from agent_worker.fact_agent import FactProposal


class MemoryClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url or os.getenv("LONELYCAT_CORE_API_URL", "http://localhost:5173")

    def propose(
        self,
        proposal: FactProposal,
        source_note: str = "mvp-1",
        conversation_id: Optional[str] = None,
        excerpt: Optional[str] = None,
    ) -> str:
        """创建 Proposal
        
        Args:
            proposal: FactProposal 对象
            source_note: Source 备注
            conversation_id: 对话 ID（用于 source_ref）
            excerpt: 证据片段（用于 source_ref）
            
        Returns:
            Proposal ID
        """
        # 构建 key（从 subject.predicate 转换为 key）
        key = f"{proposal.subject}.{proposal.predicate}" if proposal.subject != "user" else proposal.predicate
        
        payload = {
            "payload": {
                "key": key,
                "value": proposal.object,
                "tags": [],
                "ttl_seconds": None,
            },
            "source_ref": {
                "kind": "chat",
                "ref_id": conversation_id or source_note,
                "excerpt": excerpt[:200] if excerpt else None,
            },
            "reason": None,
            "confidence": proposal.confidence,
            "scope_hint": "global",
        }
        
        url = f"{self._base_url}/memory/proposals"
        
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        
        proposal_data = data.get("proposal")
        proposal_id = proposal_data.get("id") if isinstance(proposal_data, dict) else None
        if not proposal_id:
            raise ValueError("Missing proposal id in response")
        return proposal_id

    def list_facts(
        self,
        scope: str = "global",
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
        status: str = "active",
    ) -> list[dict]:
        """列出 Fact
        
        Args:
            scope: Scope (global/project/session)
            project_id: Project ID（scope=project 时必需）
            session_id: Session ID（scope=session 时必需）
            status: 状态过滤（active/revoked/archived/all）
            
        Returns:
            Fact 列表
        """
        url = f"{self._base_url}/memory/facts"
        params: Dict[str, Any] = {
            "scope": scope,
            "status": status,
        }
        if project_id:
            params["project_id"] = project_id
        if session_id:
            params["session_id"] = session_id
        
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

    def revoke(self, fact_id: str) -> None:
        """撤销 Fact
        
        Args:
            fact_id: Fact ID
        """
        url = f"{self._base_url}/memory/facts/{fact_id}/revoke"
        
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url)
            response.raise_for_status()

    def archive(self, fact_id: str) -> None:
        """归档 Fact
        
        Args:
            fact_id: Fact ID
        """
        url = f"{self._base_url}/memory/facts/{fact_id}/archive"
        
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url)
            response.raise_for_status()

    def reactivate(self, fact_id: str) -> None:
        """重新激活 Fact
        
        Args:
            fact_id: Fact ID
        """
        url = f"{self._base_url}/memory/facts/{fact_id}/reactivate"
        
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url)
            response.raise_for_status()

    def accept_proposal(
        self,
        proposal_id: str,
        strategy: Optional[str] = None,
        scope: Optional[str] = None,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """接受 Proposal
        
        Args:
            proposal_id: Proposal ID
            strategy: 冲突解决策略（overwrite_latest/keep_both）
            scope: Scope（可选）
            project_id: Project ID（可选）
            session_id: Session ID（可选）
            
        Returns:
            响应数据
        """
        url = f"{self._base_url}/memory/proposals/{proposal_id}/accept"
        payload: Dict[str, Any] = {}
        if strategy:
            payload["strategy"] = strategy
        if scope:
            payload["scope"] = scope
        if project_id:
            payload["project_id"] = project_id
        if session_id:
            payload["session_id"] = session_id
        
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload if payload else None)
            response.raise_for_status()
            return response.json()

    def reject_proposal(self, proposal_id: str, reason: str | None = None) -> dict:
        """拒绝 Proposal
        
        Args:
            proposal_id: Proposal ID
            reason: 拒绝原因（可选）
            
        Returns:
            响应数据
        """
        url = f"{self._base_url}/memory/proposals/{proposal_id}/reject"
        payload = {"reason": reason}
        
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
