"""Agent Decision service for Agent Loop.

This module implements the decision layer that determines whether to:
- Only reply (reply-only)
- Create a run (run-only)
- Reply and create a run (reply_and_run)
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

# Try to import agent_worker components, but make them optional
try:
    from agent_worker.llm.factory import build_gate_llm_from_env
    from agent_worker.memory_client import MemoryClient
    AGENT_WORKER_AVAILABLE = True
except ImportError:
    AGENT_WORKER_AVAILABLE = False
    build_gate_llm_from_env = None  # type: ignore
    MemoryClient = None  # type: ignore

from app.agent_loop_config import (
    AGENT_ALLOWED_RUN_TYPES,
    AGENT_DECISION_TIMEOUT_SECONDS,
)
from app.services.facts import fetch_active_facts

logger = logging.getLogger(__name__)


class ReplyContent(BaseModel):
    """Reply content model."""
    content: str


class RunDecision(BaseModel):
    """Run decision model."""
    type: str
    title: Optional[str] = None
    conversation_id: Optional[str] = None
    input: Dict[str, Any] = Field(default_factory=dict)


class Decision(BaseModel):
    """Agent Decision model."""
    decision: str = Field(..., pattern="^(reply|run|reply_and_run)$")
    reply: Optional[ReplyContent] = None
    run: Optional[RunDecision] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    def validate_decision_logic(self) -> tuple[bool, Optional[str]]:
        """Validate decision logic consistency.
        
        Returns:
            (is_valid, error_message)
        """
        if self.decision == "reply":
            if not self.reply:
                return False, "decision='reply' requires 'reply' field"
            if self.run is not None:
                return False, "decision='reply' should not have 'run' field"
        elif self.decision == "run":
            if not self.run:
                return False, "decision='run' requires 'run' field"
        elif self.decision == "reply_and_run":
            if not self.reply:
                return False, "decision='reply_and_run' requires 'reply' field"
            if not self.run:
                return False, "decision='reply_and_run' requires 'run' field"
        return True, None


class AgentDecision:
    """Agent Decision service."""
    
    def __init__(self):
        """Initialize Agent Decision service."""
        if not AGENT_WORKER_AVAILABLE:
            logger.warning("Agent worker not available, Agent Decision will be disabled")
            self._llm = None
            self._memory_client = None
        else:
            try:
                self._llm = build_gate_llm_from_env()
                self._memory_client = MemoryClient()
            except Exception as e:
                logger.warning(f"Failed to initialize Agent Decision components: {e}")
                self._llm = None
                self._memory_client = None
    
    def decide(
        self,
        user_message: str,
        conversation_id: str,
        history_messages: List[Dict[str, str]],
        active_facts: Optional[List[Dict[str, Any]]] = None,
        recent_runs: Optional[List[Dict[str, Any]]] = None,
    ) -> Decision:
        """Make a decision based on user message and context.
        
        Args:
            user_message: Current user message
            conversation_id: Current conversation ID
            history_messages: Recent conversation history
            active_facts: Active facts from memory (optional, auto-fetched if None)
            recent_runs: Recent runs in this conversation (optional)
        
        Returns:
            Decision object
        
        Raises:
            ValueError: If decision cannot be made (LLM unavailable, invalid response, etc.)
        """
        if not self._llm:
            raise ValueError("Agent Decision LLM is not available")
        
        # Auto-fetch active_facts if not provided
        if active_facts is None:
            if self._memory_client:
                active_facts = fetch_active_facts(
                    self._memory_client,
                    conversation_id=conversation_id,
                )
            else:
                active_facts = []
        
        # Build decision prompt
        prompt = self._build_decision_prompt(
            user_message=user_message,
            conversation_id=conversation_id,
            history_messages=history_messages,
            active_facts=active_facts or [],
            recent_runs=recent_runs or [],
        )
        
        # Call LLM
        try:
            raw_output = self._llm.generate(prompt)
            if not raw_output:
                raise ValueError("LLM returned empty response")
        except Exception as e:
            logger.error(f"Failed to call Decision LLM: {e}", exc_info=True)
            raise ValueError(f"Decision LLM call failed: {e}")
        
        # Parse JSON
        try:
            decision_dict = json.loads(raw_output)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Decision JSON: {e}, raw_output: {raw_output}")
            raise ValueError(f"Invalid JSON response from Decision LLM: {e}")
        
        # Validate schema
        try:
            decision = Decision(**decision_dict)
        except ValidationError as e:
            logger.error(f"Decision validation failed: {e}, decision_dict: {decision_dict}")
            raise ValueError(f"Decision schema validation failed: {e}")
        
        # Validate decision logic
        is_valid, error_msg = decision.validate_decision_logic()
        if not is_valid:
            logger.error(f"Decision logic validation failed: {error_msg}, decision: {decision_dict}")
            raise ValueError(f"Decision logic validation failed: {error_msg}")
        
        # Check run type whitelist
        if decision.run:
            if decision.run.type not in AGENT_ALLOWED_RUN_TYPES:
                logger.warning(
                    f"Run type '{decision.run.type}' not in whitelist {AGENT_ALLOWED_RUN_TYPES}, "
                    f"falling back to reply-only"
                )
                # Fallback to reply-only
                if decision.decision == "run":
                    # Convert run-only to reply-only
                    decision.decision = "reply"
                    decision.reply = ReplyContent(
                        content=f"抱歉，任务类型 '{decision.run.type}' 不在允许列表中。"
                    )
                    decision.run = None
                elif decision.decision == "reply_and_run":
                    # Keep reply but remove run
                    decision.decision = "reply"
                    if decision.reply:
                        decision.reply.content += f"\n\n（注：任务类型 '{decision.run.type}' 不在允许列表中，已跳过任务创建）"
                    decision.run = None
        
        # Ensure conversation_id is set correctly
        # According to spec: if user is in a conversation, must use that conversation_id
        # Only allow null for system/automatic tasks (which Decision should decide)
        # For now, we always use the current conversation_id if provided
        if decision.run:
            # If Decision didn't set conversation_id (or set to null), use current conversation_id
            # This ensures users in a conversation always get runs associated with that conversation
            if decision.run.conversation_id is None:
                decision.run.conversation_id = conversation_id
        
        logger.info(
            f"Decision made: decision={decision.decision}, "
            f"confidence={decision.confidence}, reason={decision.reason[:50]}"
        )
        
        return decision
    
    def _build_decision_prompt(
        self,
        user_message: str,
        conversation_id: str,
        history_messages: List[Dict[str, str]],
        active_facts: List[Dict[str, Any]],
        recent_runs: List[Dict[str, Any]],
    ) -> str:
        """Build decision prompt for LLM.
        
        Args:
            user_message: Current user message
            conversation_id: Current conversation ID
            history_messages: Recent conversation history
            active_facts: Active facts from memory
            recent_runs: Recent runs in this conversation
        
        Returns:
            Prompt string
        """
        # System block 1: 目标 + 决策类型 + JSON schema（稳定部分）
        system_prompt_schema = """You are an AI assistant that decides how to respond to user messages.

You can choose one of three actions:
1. "reply" - Only reply to the user (normal conversation)
2. "run" - Create a background task without replying immediately
3. "reply_and_run" - Reply to the user AND create a background task

Available task types (whitelist):
{allowed_types}

Decision rules:
- Use "reply" for normal chat, subjective opinions, or when no task is needed (e.g. greetings, "推荐一款游戏").
- Use "run" when the user wants a background task and doesn't need immediate response.
- Use "reply_and_run" when you should acknowledge the request AND start a task.
- **Research / lookup**: When the user asks to 查/查一下/查下/搜索/查查 (e.g. "帮我查下现在估值最高的公司", "查一下最畅销的手机", "搜索当前某某"), use "run" with type "research_report". Put the user's question or topic in run.input.query (and optionally run.title). Do NOT use "reply" for such lookup requests—they need real-time or factual data via research_report.
- Always set conversation_id to the current conversation_id (unless it's a system/automatic task).
- Only use task types from the whitelist above.

Return ONLY a valid JSON object with this exact structure:
{{
  "decision": "reply" | "run" | "reply_and_run",
  "reply": {{
    "content": "string"
  }},
  "run": {{
    "type": "string",
    "title": "string?",
    "conversation_id": "string|null",
    "input": {{"any": "json"}}
  }},
  "confidence": 0.0-1.0,
  "reason": "string"
}}

Rules:
- If decision="reply": must provide reply.content, must NOT provide run
- If decision="run": must provide run, reply can be empty/null
- If decision="reply_and_run": must provide BOTH reply and run
- conversation_id: use "{conversation_id}" if user is in a conversation, null for system/automatic tasks
- For research_report: run.input must include "query" with the user's lookup question (e.g. "现在估值最高的公司是哪个")

Examples (user -> decision):
- "帮我查下现在估值最高的公司" -> decision=run, type=research_report, run.input.query="现在估值最高的公司是哪个"
- "查一下最畅销的手机品牌" -> decision=run, type=research_report, run.input.query="最畅销的手机品牌"
- "你好" -> decision=reply
""".format(
            allowed_types=", ".join(AGENT_ALLOWED_RUN_TYPES),
            conversation_id=conversation_id,
        )
        
        # System block 2: Facts (动态部分)
        # Include facts that are active or have no status (e.g. minimal test payloads)
        facts_block = ""
        if active_facts:
            facts_list = []
            for fact in active_facts:
                status = fact.get("status")
                if status in ("revoked", "archived"):
                    continue
                key = fact.get("key", "")
                value = fact.get("value", "")
                if not key:
                    continue
                if isinstance(value, (dict, list)):
                    value_str = json.dumps(value, sort_keys=True, ensure_ascii=False)
                else:
                    value_str = str(value)
                facts_list.append(f"- {key}: {value_str}")
            
            if facts_list:
                facts_text = "\n".join(facts_list)
                facts_block = f"""

[KNOWN FACTS]
{facts_text}
[/KNOWN FACTS]

Rules:
- Use KNOWN FACTS when relevant.
- Do not ask for info already in KNOWN FACTS.
- If user contradicts a fact, ask for confirmation and propose an update."""
        
        # Context blocks (动态部分)
        context_parts = []
        
        # Add history messages (last 10 messages)
        if history_messages:
            recent_history = history_messages[-10:]
            context_parts.append("Recent conversation history:")
            for msg in recent_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                context_parts.append(f"{role}: {content}")
        
        # Add recent runs (optional, for avoiding duplicates)
        if recent_runs:
            runs_summary = []
            for run in recent_runs[:5]:  # Last 5 runs
                run_type = run.get("type", "unknown")
                run_status = run.get("status", "unknown")
                runs_summary.append(f"- {run_type} ({run_status})")
            if runs_summary:
                context_parts.append(f"\nRecent runs in this conversation:\n" + "\n".join(runs_summary))
        
        # Current user message
        context_parts.append(f"\nCurrent user message:\n{user_message}")
        
        # Combine: system blocks + context
        prompt = f"{system_prompt_schema}{facts_block}\n\n" + "\n".join(context_parts)
        
        return prompt
    
    def get_active_facts(self, conversation_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get active facts from memory.
        
        Args:
            conversation_id: Optional conversation ID for session scope facts
        
        Returns:
            List of active facts (global + session scope, deduplicated)
        """
        if not self._memory_client:
            return []
        
        try:
            return fetch_active_facts(
                self._memory_client,
                conversation_id=conversation_id,
            )
        except Exception as e:
            logger.warning(f"Failed to fetch active facts: {e}", exc_info=True)
            logger.warning(f"Error type: {type(e).__name__}")
            return []
