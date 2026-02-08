"""Internal API endpoints for cross-service communication.

These endpoints are used by worker and other internal services.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

# parent 处于 WAITING_CHILD 超过此时长视为超时，orchestration-step 返回 reply 兜底（需配合定时将 WAITING_CHILD 置为 QUEUED 的 job 才会被拉取到）
_WAITING_CHILD_TIMEOUT_SECONDS = 600  # 10 min

# parent 处于 WAITING_CHILD 超过此时长视为超时，orchestration-step 返回 reply 兜底（需配合定时将 WAITING_CHILD 置为 QUEUED 的 job 才会被拉取到）
WAITING_CHILD_TIMEOUT_SECONDS = 600  # 10 min

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.runs import _create_run, _list_conversation_runs
from app.db import ConversationModel, MessageModel, MessageRole, RunModel, RunStatus, SessionLocal
from app.services.conversation_orchestrator import get_orchestration_step, run_code_snippet_loop
from app.services.run_messages import emit_run_message

try:
    from app.services.agent_decision import AgentDecision
    _AGENT_DECISION_AVAILABLE = True
except ImportError:
    AgentDecision = None  # type: ignore
    _AGENT_DECISION_AVAILABLE = False

router = APIRouter(prefix="/internal", tags=["internal"])


def get_db():
    """获取数据库会话（依赖注入）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/runs/{run_id}/emit-message", status_code=204)
async def emit_run_completion_message(
    run_id: str,
    db: Session = Depends(get_db),
) -> None:
    """内部 API：为完成的 run 发送消息到对应的 conversation
    
    这个端点由 worker 在 run 完成时调用。
    幂等性由 emit_run_message 函数保证。
    
    Args:
        run_id: Run ID
        db: 数据库会话
    """
    # 查询 run
    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    
    # 只处理终态（succeeded/failed/canceled）
    if run.status not in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED):
        raise HTTPException(
            status_code=400,
            detail=f"Run {run_id} is not in a final state (current: {run.status.value})"
        )
    
    # 调用服务函数发送消息
    try:
        emit_run_message(db, run)
    except Exception as e:
        # 记录错误但不抛出异常（避免影响 run 的完成状态）
        print(f"Error: Failed to emit run message for run {run_id}: {e}")
        # 返回 500 但记录错误（可选：也可以返回 200 表示"已尝试"）
        raise HTTPException(
            status_code=500,
            detail=f"Failed to emit run message: {str(e)}"
        )


def _load_history_messages(db: Session, conversation_id: str, limit: int = 60) -> List[Dict[str, str]]:
    """从对话加载历史消息，转为 LLM 格式 [{\"role\": \"user\"|\"assistant\", \"content\": ...}]"""
    messages = (
        db.query(MessageModel)
        .filter(MessageModel.conversation_id == conversation_id)
        .order_by(MessageModel.created_at.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()
    out: List[Dict[str, str]] = []
    for msg in messages:
        if msg.role == MessageRole.USER:
            out.append({"role": "user", "content": msg.content or ""})
        elif msg.role == MessageRole.ASSISTANT:
            out.append({"role": "assistant", "content": msg.content or ""})
    return out


@router.post("/runs/{run_id}/execute-orchestration", response_model=Dict[str, Any])
async def execute_orchestration(
    run_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """内部 API：执行 agent_loop_turn 编排（run_code_snippet_loop），不更新 run 状态。

    Worker 在拉取到 type=agent_loop_turn 的 run 后调用此接口执行编排，再将返回的 final_reply/run_ids
    交给 complete_success，最后调用 emit-message 由 core-api 写 task_done。

    校验：run 存在且 type == \"agent_loop_turn\"；input 含 conversation_id、user_message。
    """
    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run_type_norm = (run.type or "").strip().replace(" ", "_")
    if run_type_norm != "agent_loop_turn":
        raise HTTPException(
            status_code=400,
            detail=f"Run {run_id} is not agent_loop_turn (type={run.type!r})",
        )
    inp = run.input_json or {}
    conversation_id = inp.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise HTTPException(
            status_code=400,
            detail="agent_loop_turn input must contain non-empty conversation_id",
        )
    user_message = (inp.get("user_message") or "").strip() or ""
    conv = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if not _AGENT_DECISION_AVAILABLE or AgentDecision is None:
        raise HTTPException(
            status_code=503,
            detail="AgentDecision service not available",
        )

    history_messages = _load_history_messages(db, conversation_id)
    recent_runs: List[Dict[str, Any]] = []
    try:
        runs_result = await _list_conversation_runs(conversation_id, db, limit=5, offset=0)
        recent_runs = runs_result.get("items", [])
    except Exception:
        recent_runs = []

    agent_decision = AgentDecision()
    final_reply, run_ids = await run_code_snippet_loop(
        conversation_id=conversation_id,
        user_message=user_message,
        history_messages=history_messages,
        db=db,
        agent_decision=agent_decision,
        create_run_fn=_create_run,
        recent_runs=recent_runs,
        conversation_id_for_run=conversation_id,
        initial_decision=None,
        parent_run_id=run_id,
    )
    return {
        "final_reply": (final_reply or "").strip() or "任务已完成",
        "run_ids": run_ids or [],
    }


class YieldWaitingChildRequest(BaseModel):
    """yield-waiting-child 请求体：父 run 让出 worker，等待子 run 完成后被唤醒"""
    child_run_id: str
    step_index: int = 0
    run_ids: Optional[List[str]] = None  # 当前已创建的子 run id 列表，供唤醒后合并到 input


class OrchestrationStepRequest(BaseModel):
    """orchestration-step 请求体"""
    step_index: int = 0
    previous_output_json: Optional[Dict[str, Any]] = None


# 强幂等：父已 WAITING_CHILD 且已有 waiting_child_run_id 时，同 id 视为 no-op，不同 id 拒绝
_WAITING_CHILD_CONFLICT_MSG = "parent already waiting for a different child run"

@router.post("/runs/{run_id}/yield-waiting-child", status_code=204)
async def yield_waiting_child(
    run_id: str,
    body: YieldWaitingChildRequest,
    db: Session = Depends(get_db),
) -> None:
    """内部 API：父 run 等待子 run 时让出 worker。将 parent 置为 WAITING_CHILD（不可被 worker 拉取），output_json 写入等待状态。
    强幂等：若 parent 已 status=WAITING_CHILD 且已有 waiting_child_run_id，同一 child_run_id → 204 no-op；不同 → 409。"""
    parent = db.query(RunModel).filter(RunModel.id == run_id).first()
    if parent is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run_type_norm = (parent.type or "").strip().replace(" ", "_")
    if run_type_norm != "agent_loop_turn":
        raise HTTPException(status_code=400, detail=f"Run {run_id} is not agent_loop_turn")
    now = datetime.now(UTC)
    # 统一真源结构：output_json.waiting = { child_run_id, step_index, run_ids, since_ts }
    waiting = {
        "child_run_id": body.child_run_id,
        "step_index": body.step_index,
        "run_ids": list(body.run_ids) if body.run_ids else [body.child_run_id],
        "since_ts": now.isoformat(),
    }
    # 幂等：已 waiting 且 child_run_id 一致则 no-op；不一致则 409
    existing_waiting = _read_waiting_info(parent.output_json)
    if existing_waiting and existing_waiting.get("child_run_id") == body.child_run_id:
        return
    if existing_waiting:
        raise HTTPException(status_code=409, detail=_WAITING_CHILD_CONFLICT_MSG)
    parent.status = RunStatus.WAITING_CHILD
    # 清空旧字段并写入新结构，避免混乱
    parent.output_json = {
        "waiting": waiting,
    }
    parent.worker_id = None
    parent.lease_expires_at = None
    parent.updated_at = now
    db.commit()


def _read_waiting_info(parent_output_json: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """从 parent.output_json 读取等待信息的真源结构（兼容旧字段）。
    优先使用新的 output_json.waiting 结构；若不存在，则兼容读取顶层字段。
    """
    if not parent_output_json or not isinstance(parent_output_json, dict):
        return None
    if "waiting" in parent_output_json:
        w = parent_output_json["waiting"]
        if isinstance(w, dict):
            return w
    # 兼容旧字段
    child_run_id = parent_output_json.get("waiting_child_run_id") or parent_output_json.get("child_run_id")
    if child_run_id:
        return {
            "child_run_id": child_run_id,
            "step_index": parent_output_json.get("waiting_step_index", parent_output_json.get("step_index", 0)),
            "run_ids": parent_output_json.get("run_ids") or [],
            "since_ts": None,
        }
    return None
    # 清空租约，避免被 worker 当作“过期 RUNNING”重拉
    parent.worker_id = None
    parent.lease_expires_at = None
    parent.updated_at = now
    db.commit()


@router.post("/runs/{run_id}/orchestration-step", response_model=Dict[str, Any])
async def orchestration_step(
    run_id: str,
    body: OrchestrationStepRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """内部 API：返回编排的下一步（不创建 run、不等待），供 worker 单步推进状态机。

    若 parent 处于 WAIT_CHILD 且 step_index 与 waiting_step_index 一致，返回 action=wait，防并发/重放重复创建子 run。
    """
    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    run_type_norm = (run.type or "").strip().replace(" ", "_")
    if run_type_norm != "agent_loop_turn":
        raise HTTPException(
            status_code=400,
            detail=f"Run {run_id} is not agent_loop_turn (type={run.type!r})",
        )
    out = run.output_json or {}
    waiting = _read_waiting_info(out)
    if waiting and body.step_index == waiting.get("step_index", 0):
        now = datetime.now(UTC)
        updated = run.updated_at
        if updated is not None and getattr(updated, "tzinfo", None) is None:
            updated = updated.replace(tzinfo=UTC)
        if updated is not None and (now - updated).total_seconds() > WAITING_CHILD_TIMEOUT_SECONDS:
            # 兜底：waiting 超时，清空等待状态并返回 reply，由 worker 完成 parent
            _wait_keys = ("state", "child_run_id", "waiting_child_run_id", "waiting_step_index", "run_ids", "waiting")
            run.output_json = {k: v for k, v in (run.output_json or {}).items() if k not in _wait_keys}
            if not run.output_json:
                run.output_json = None
            run.updated_at = now
            db.commit()
            return {"action": "reply", "final_reply": "子任务超时/失败，请重试。"}
        return {"action": "wait", "child_run_id": waiting["child_run_id"]}
    inp = run.input_json or {}
    conversation_id = inp.get("conversation_id")
    if not isinstance(conversation_id, str) or not conversation_id.strip():
        raise HTTPException(
            status_code=400,
            detail="agent_loop_turn input must contain non-empty conversation_id",
        )
    user_message = (inp.get("user_message") or "").strip() or ""
    if not _AGENT_DECISION_AVAILABLE or AgentDecision is None:
        raise HTTPException(status_code=503, detail="AgentDecision service not available")

    history_messages = _load_history_messages(db, conversation_id)
    recent_runs: List[Dict[str, Any]] = []
    try:
        runs_result = await _list_conversation_runs(conversation_id, db, limit=5, offset=0)
        recent_runs = runs_result.get("items", [])
    except Exception:
        recent_runs = []

    agent_decision = AgentDecision()
    action, value = get_orchestration_step(
        agent_decision=agent_decision,
        conversation_id=conversation_id,
        user_message=user_message,
        history_messages=history_messages,
        recent_runs=recent_runs,
        step_index=body.step_index,
        previous_output_json=body.previous_output_json,
        parent_run_id=run_id,
        conversation_id_for_run=conversation_id,
    )
    if action == "reply":
        return {"action": "reply", "final_reply": value}
    return {"action": "create_run", "run_request": value}
