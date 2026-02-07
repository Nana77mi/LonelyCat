"""Conversation orchestrator: enforces max_steps for run_code_snippet (Agent Loop v2).

Only handles run_code_snippet. Loop: create_run -> wait_run_done -> get observation
-> next agent_decision(previous_observation=...) -> reply or next run, until reply or max_steps.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from protocol.run_constants import is_valid_trace_id
from sqlalchemy.orm import Session

from app.agent_loop_config import MAX_AGENT_LOOP_STEPS
from app.api.runs import RunCreateRequest
from app.db import RunModel, RunStatus

logger = logging.getLogger(__name__)

# Terminal statuses for a run
_TERMINAL_STATUSES = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED}


# Default wait cap (avoid blocking worker too long); override via run_code_snippet_loop(max_wait_sec=...)
DEFAULT_ORCHESTRATOR_MAX_WAIT_SEC = 60.0

_TIMEOUT_MESSAGE_SUFFIX = " 任务可能仍在后台执行，请在任务列表中查看。"
_MAX_STEPS_FALLBACK_MESSAGE = "已达最大步数，未得到最终回复。请在任务详情中查看各步输出。"


async def wait_run_done(
    run_id: str,
    db: Session,
    *,
    poll_interval_sec: float = 1.0,
    max_wait_sec: float = DEFAULT_ORCHESTRATOR_MAX_WAIT_SEC,
) -> RunModel:
    """Poll DB until run reaches a terminal status (succeeded/failed/canceled)."""
    import time
    deadline = time.monotonic() + max_wait_sec
    while True:
        run = db.query(RunModel).filter(RunModel.id == run_id).first()
        if run is None:
            raise RuntimeError(f"Run not found: {run_id}")
        if run.status in _TERMINAL_STATUSES:
            return run
        await asyncio.sleep(poll_interval_sec)
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"Run {run_id} 在 {max_wait_sec:.0f}s 内未结束。{_TIMEOUT_MESSAGE_SUFFIX}"
            )


def _extract_observation(output_json: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract observation for next decision from run.output_json. Stable fallback chain."""
    if not output_json:
        return {}
    # Prefer top-level, then result.observation (worker TaskResult v0)
    obs = output_json.get("observation")
    if isinstance(obs, dict):
        return obs
    result = output_json.get("result") or {}
    return result.get("observation") or {}


def _extract_reply(output_json: Optional[Dict[str, Any]]) -> str:
    """Extract final reply for user from run.output_json. Stable fallback chain."""
    if not output_json:
        return ""
    # Priority: reply (UI) -> final_response (compat) -> result.reply
    for key in ("reply", "final_response"):
        s = output_json.get(key)
        if isinstance(s, str) and s.strip():
            return s.strip()
    result = output_json.get("result") or {}
    return (result.get("reply") or result.get("final_response") or "").strip()


def get_orchestration_step(
    agent_decision: Any,
    conversation_id: str,
    user_message: str,
    history_messages: List[Dict[str, str]],
    recent_runs: List[Dict[str, Any]],
    step_index: int,
    previous_output_json: Optional[Dict[str, Any]],
    parent_run_id: Optional[str],
    conversation_id_for_run: Optional[str] = None,
) -> Tuple[str, Any]:
    """计算编排的单步，不创建 run、不等待。供 worker 本地驱动循环、进程内执行子 run 时使用。

    Returns:
        ("reply", final_reply: str) 或 ("create_run", run_request: dict)。
        run_request 可直接用于 POST /runs，含 type, title, conversation_id, input（含 parent_run_id）。
    """
    conv_id = conversation_id_for_run or conversation_id
    max_steps = MAX_AGENT_LOOP_STEPS
    if step_index >= max_steps:
        return ("reply", _MAX_STEPS_FALLBACK_MESSAGE)

    if step_index == 0:
        observation = None
    else:
        observation = _extract_observation(previous_output_json) if previous_output_json else None

    if step_index == 0:
        decision = agent_decision.decide(
            user_message=user_message,
            conversation_id=conversation_id,
            history_messages=history_messages,
            recent_runs=recent_runs,
        )
    else:
        decision = agent_decision.decide(
            user_message=user_message,
            conversation_id=conversation_id,
            history_messages=history_messages,
            recent_runs=recent_runs,
            previous_observation=observation or {},
        )

    if decision.decision == "reply":
        content = (decision.reply.content or "").strip() if decision.reply else ""
        reply_from_prev = _extract_reply(previous_output_json) if previous_output_json else ""
        final = content or reply_from_prev or "任务已完成"
        return ("reply", final)

    if not decision.run or (decision.run.type or "").strip().replace(" ", "_") != "run_code_snippet":
        reply_from_prev = _extract_reply(previous_output_json) if previous_output_json else ""
        return ("reply", reply_from_prev or "任务已完成")

    current_input = dict(decision.run.input) if decision.run.input else {}
    if not current_input.get("conversation_id"):
        current_input["conversation_id"] = conv_id
    if not is_valid_trace_id(current_input.get("trace_id")):
        current_input["trace_id"] = uuid.uuid4().hex
    if parent_run_id:
        current_input["parent_run_id"] = parent_run_id

    run_request = {
        "type": decision.run.type,
        "title": decision.run.title,
        "conversation_id": conv_id,
        "input": current_input,
    }
    return ("create_run", run_request)


async def run_code_snippet_loop(
    conversation_id: str,
    user_message: str,
    history_messages: List[Dict[str, str]],
    db: Session,
    agent_decision: Any,  # AgentDecision
    create_run_fn: Callable[[RunCreateRequest, Session], Any],  # async (req, db) -> dict
    recent_runs: Optional[List[Dict[str, Any]]] = None,
    conversation_id_for_run: Optional[str] = None,
    initial_decision: Optional[Any] = None,  # Decision already made by caller (avoid duplicate decide)
    parent_run_id: Optional[str] = None,  # 若由 agent_loop_turn 调用，传其 run_id，子 run 的 input 会带此字段，emit 时跳过子 run
    *,
    poll_interval_sec: float = 1.0,
    max_wait_sec: float = DEFAULT_ORCHESTRATOR_MAX_WAIT_SEC,
) -> Tuple[Optional[str], List[str]]:
    """Orchestrate run_code_snippet with max_steps loop.
    
    - If initial_decision is provided and is run/reply_and_run with run_code_snippet, use it for step 0.
    - Otherwise call agent_decision.decide() once; if reply or not run_code_snippet, return.
    - After each run: wait_run_done -> get observation -> decide(previous_observation=...).
    - If decision=reply or steps >= max_steps: return (final_reply, run_ids).
    
    Returns:
        (final_reply, run_ids). final_reply may be None if caller should use something else.
    """
    conv_id = conversation_id_for_run or conversation_id
    recent_runs = recent_runs or []
    
    if initial_decision is not None and initial_decision.run and (initial_decision.run.type or "").strip().replace(" ", "_") == "run_code_snippet":
        decision = initial_decision
    else:
        decision = agent_decision.decide(
            user_message=user_message,
            conversation_id=conversation_id,
            history_messages=history_messages,
            recent_runs=recent_runs,
        )
        if decision.decision == "reply":
            content = (decision.reply.content or "").strip() if decision.reply else ""
            return (content, [])
        if not decision.run or (decision.run.type or "").strip().replace(" ", "_") != "run_code_snippet":
            return (None, [])
    
    # Clamp: min(llm max_steps, system cap)
    llm_steps = getattr(decision.run, "max_steps", None)
    if llm_steps is not None and not isinstance(llm_steps, int):
        llm_steps = 3
    if llm_steps is None:
        llm_steps = 3
    max_steps = min(max(1, llm_steps), MAX_AGENT_LOOP_STEPS)
    
    run_ids: List[str] = []
    current_input = dict(decision.run.input) if decision.run.input else {}
    if not current_input.get("conversation_id"):
        current_input["conversation_id"] = conv_id
    if not is_valid_trace_id(current_input.get("trace_id")):
        current_input["trace_id"] = uuid.uuid4().hex
    if parent_run_id:
        current_input["parent_run_id"] = parent_run_id

    reply = ""
    for step in range(max_steps):
        run_request = RunCreateRequest(
            type=decision.run.type,
            title=decision.run.title,
            conversation_id=conv_id,
            input=current_input,
        )
        run_result = await create_run_fn(run_request, db)
        run_id = run_result.get("id")
        if not run_id:
            logger.warning("create_run did not return id, stopping loop")
            break
        run_ids.append(run_id)
        logger.info(f"Orchestrator step {step + 1}/{max_steps}, run_id={run_id}")
        
        run = await wait_run_done(run_id, db, poll_interval_sec=poll_interval_sec, max_wait_sec=max_wait_sec)
        observation = _extract_observation(run.output_json)
        reply = _extract_reply(run.output_json)
        
        if step + 1 >= max_steps:
            return (reply.strip() if reply else _MAX_STEPS_FALLBACK_MESSAGE, run_ids)
        
        next_decision = agent_decision.decide(
            user_message=user_message,
            conversation_id=conversation_id,
            history_messages=history_messages,
            recent_runs=recent_runs,
            previous_observation=observation,
        )
        
        if next_decision.decision == "reply":
            content = (next_decision.reply.content or "").strip() if next_decision.reply else reply
            return (content, run_ids)
        
        if not next_decision.run or (next_decision.run.type or "").strip().replace(" ", "_") != "run_code_snippet":
            return (reply, run_ids)
        
        decision = next_decision
        current_input = dict(next_decision.run.input) if next_decision.run.input else {}
        if not current_input.get("conversation_id"):
            current_input["conversation_id"] = conv_id
        if not is_valid_trace_id(current_input.get("trace_id")):
            current_input["trace_id"] = uuid.uuid4().hex
        if parent_run_id:
            current_input["parent_run_id"] = parent_run_id

    return (reply.strip() if reply else _MAX_STEPS_FALLBACK_MESSAGE, run_ids)
