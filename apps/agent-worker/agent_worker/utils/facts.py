"""Utility functions for fetching and managing facts."""

from __future__ import annotations

import os
from typing import Optional

import httpx

from agent_worker.memory_client import MemoryClient


def fetch_active_facts_via_api(
    base_url: str,
    *,
    conversation_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Fetch active facts from core-api GET /memory/facts/active (single entry point).
    Worker and chat_flow use this instead of MemoryClient.list_facts for read path.
    """
    url = f"{base_url.rstrip('/')}/memory/facts/active"
    params: dict = {}
    if conversation_id is not None:
        params["conversation_id"] = conversation_id
    if limit is not None:
        params["limit"] = limit
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, params=params or None)
            response.raise_for_status()
            data = response.json()
    except Exception:
        return []
    items = data.get("items")
    if not isinstance(items, list):
        return []
    return [f for f in items if isinstance(f, dict)]


def fetch_active_facts(
    memory_client: MemoryClient,
    *,
    conversation_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> list[dict]:
    """
    统一获取active facts的函数
    
    Args:
        memory_client: Memory客户端实例
        conversation_id: 对话ID（用于session scope）
        project_id: 项目ID（用于project scope，暂未实现）
    
    Returns:
        Active facts列表（global + session + project，去重后）
    
    去重规则：
    - 按key去重
    - 优先级：session > project > global
    - value使用json.dumps(value, sort_keys=True)进行稳定序列化比较
    """
    facts_by_key: dict[str, dict] = {}
    
    try:
        # 1. 查询global scope facts（优先级最低）
        global_facts = memory_client.list_facts(scope="global", status="active")
        # 注意：list_facts已经按status="active"过滤，但这里再次检查确保
        for fact in global_facts:
            # list_facts返回的facts可能已经过滤了status，但为了安全再次检查
            if fact.get("status") != "active":
                continue
            key = fact.get("key", "")
            if key:
                facts_by_key[key] = fact
        
        # 2. 查询project scope facts（优先级中等，暂未实现）
        # project_facts = []
        # if project_id:
        #     try:
        #         project_facts = memory_client.list_facts(
        #             scope="project",
        #             project_id=project_id,
        #             status="active"
        #         )
        #         for fact in project_facts:
        #             if fact.get("status") == "active":
        #                 key = fact.get("key", "")
        #                 if key:
        #                     facts_by_key[key] = fact  # project覆盖global
        #     except Exception:
        #         pass
        
        # 3. 查询session scope facts（优先级最高）
        session_facts = []
        if conversation_id:
            try:
                session_facts = memory_client.list_facts(
                    scope="session",
                    session_id=conversation_id,
                    status="active"
                )
                for fact in session_facts:
                    if fact.get("status") == "active":
                        key = fact.get("key", "")
                        if key:
                            facts_by_key[key] = fact  # session覆盖global和project
            except Exception:
                pass
        
        return list(facts_by_key.values())
    except Exception:
        return []
