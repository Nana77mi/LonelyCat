"""
LonelyCat Execution History API - Phase 2.4-A (Updated)

Provides read-only observability endpoints for execution history:
- GET /executions - List executions with filters
- GET /executions/{execution_id} - Get execution details with steps
- GET /executions/{execution_id}/artifacts - Get artifact metadata
- GET /executions/{execution_id}/replay - Replay execution from artifacts
- GET /executions/{execution_id}/lineage - Get execution lineage (ancestors, descendants, siblings)

Philosophy:
- Read-only observability (no mutations)
- Security: path whitelist for artifact access
- Performance: pagination and size limits for logs
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
import json

# Add packages to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages"))

from executor import (
    ExecutionStore,
    init_executor_db,
    replay_execution
)
from executor.storage import ExecutionRecord, StepRecord


router = APIRouter(prefix="/executions", tags=["executions"])

# Initialize execution store
# Note: workspace_root should be configurable, default to repo root for now
WORKSPACE_ROOT = Path(__file__).parent.parent.parent.parent
EXECUTOR_DB_PATH = WORKSPACE_ROOT / ".lonelycat" / "executor.db"

# Initialize database if not exists
init_executor_db(EXECUTOR_DB_PATH)

execution_store = ExecutionStore(WORKSPACE_ROOT)


# ==================== Security ====================

def validate_artifact_path(artifact_path: Path) -> bool:
    """
    Validate artifact path is within allowed directory.

    Security boundary: only allow reading from .lonelycat/executions/**
    """
    try:
        executions_dir = WORKSPACE_ROOT / ".lonelycat" / "executions"
        resolved = artifact_path.resolve()
        return resolved.is_relative_to(executions_dir)
    except Exception:
        return False


# ==================== Response Models ====================

class ExecutionSummary(BaseModel):
    """Summary of an execution (list view)."""
    execution_id: str
    plan_id: str
    changeset_id: str
    status: str
    verdict: str
    risk_level: str
    started_at: str
    ended_at: Optional[str]
    duration_seconds: Optional[float]
    files_changed: int
    verification_passed: bool
    health_checks_passed: bool
    rolled_back: bool
    error_step: Optional[str] = None
    error_message: Optional[str] = None


class StepDetail(BaseModel):
    """Execution step detail."""
    id: int
    step_num: int
    step_name: str
    status: str
    started_at: str
    ended_at: Optional[str]
    duration_seconds: Optional[float]
    error_code: Optional[str]
    error_message: Optional[str]
    log_ref: Optional[str]


class ExecutionDetail(BaseModel):
    """Full execution details with steps."""
    execution: ExecutionSummary
    steps: List[StepDetail]
    artifact_path: str


class ArtifactInfo(BaseModel):
    """Artifact metadata (no full content)."""
    artifact_path: str
    artifacts_complete: bool
    four_piece_set: Dict[str, bool]  # plan.json, changeset.json, decision.json, execution.json
    step_logs: List[str]  # List of log filenames
    has_stdout: bool
    has_stderr: bool
    has_backups: bool


class ExecutionListResponse(BaseModel):
    """Response for execution list."""
    executions: List[ExecutionSummary]
    total: int
    limit: int
    offset: int = 0


class LineageExecutionSummary(BaseModel):
    """Execution summary in lineage context (includes graph fields)."""
    execution_id: str
    plan_id: str
    status: str
    verdict: str
    risk_level: str
    started_at: str
    ended_at: Optional[str]
    correlation_id: Optional[str] = None
    parent_execution_id: Optional[str] = None
    trigger_kind: Optional[str] = None
    run_id: Optional[str] = None
    files_changed: int


class ExecutionLineage(BaseModel):
    """Execution lineage response (Phase 2.4-A)."""
    execution: LineageExecutionSummary
    ancestors: List[LineageExecutionSummary]  # From root to immediate parent
    descendants: List[LineageExecutionSummary]  # All children (BFS order)
    siblings: List[LineageExecutionSummary]  # Same parent


class CorrelationChain(BaseModel):
    """Correlation chain response (Phase 2.4-A)."""
    correlation_id: str
    total_executions: int
    root_execution_id: Optional[str]
    executions: List[LineageExecutionSummary]


# ==================== Endpoints ====================

@router.get("", response_model=ExecutionListResponse)
async def list_executions(
    limit: int = Query(20, ge=1, le=100, description="Number of executions to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    status: Optional[str] = Query(None, description="Filter by status (pending, completed, failed, rolled_back)"),
    verdict: Optional[str] = Query(None, description="Filter by verdict (allow, need_approval, deny)"),
    risk_level: Optional[str] = Query(None, description="Filter by risk level (low, medium, high, critical)"),
    since: Optional[str] = Query(None, description="ISO timestamp - only show executions after this time"),
    correlation_id: Optional[str] = Query(None, description="Filter by correlation_id (Phase 2.4-A)")
):
    """
    List executions with optional filters.

    Maps directly to ExecutionStore.list_executions().

    Examples:
        GET /executions?limit=10
        GET /executions?status=failed&risk_level=high
        GET /executions?verdict=allow&since=2024-01-01T00:00:00Z
        GET /executions?correlation_id=corr_abc123  (Phase 2.4-A)
    """
    try:
        # If correlation_id is specified, use specialized query
        if correlation_id:
            records = execution_store.list_executions_by_correlation(correlation_id, limit=limit + offset)
            # Apply offset
            records = records[offset:offset + limit]
        else:
            # Get filtered executions from store
            # Note: ExecutionStore doesn't support offset/since yet in Phase 2.2
            # For MVP, we'll get all matching and slice in memory
            records = execution_store.list_executions(
                limit=limit + offset,  # Get more to account for offset
                status=status,
                verdict=verdict,
                risk_level=risk_level
            )

            # Apply offset
            records = records[offset:offset + limit]

        # Convert to response model
        executions = []
        for record in records:
            executions.append(ExecutionSummary(
                execution_id=record.execution_id,
                plan_id=record.plan_id,
                changeset_id=record.changeset_id,
                status=record.status,
                verdict=record.verdict,
                risk_level=record.risk_level or "unknown",
                started_at=record.started_at,
                ended_at=record.ended_at,
                duration_seconds=record.duration_seconds,
                files_changed=record.files_changed,
                verification_passed=record.verification_passed,
                health_checks_passed=record.health_checks_passed,
                rolled_back=record.rolled_back,
                error_step=record.error_step,
                error_message=record.error_message
            ))

        return ExecutionListResponse(
            executions=executions,
            total=len(executions),  # Note: This is approximate, true total would need COUNT query
            limit=limit,
            offset=offset
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list executions: {str(e)}")


@router.get("/statistics")
async def get_execution_statistics():
    """
    Get overall execution statistics.

    Returns aggregated metrics:
    - Total executions
    - By status breakdown
    - By verdict breakdown
    - By risk level breakdown
    - Success rate
    - Average duration
    """
    try:
        stats = execution_store.get_statistics()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get statistics: {str(e)}")


@router.get("/{execution_id}", response_model=ExecutionDetail)
async def get_execution(execution_id: str):
    """
    Get execution details with steps.

    Combines get_execution() + get_execution_steps().
    """
    try:
        # Get execution record
        record = execution_store.get_execution(execution_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

        # Get execution steps
        steps = execution_store.get_execution_steps(execution_id)

        # Convert to response models
        execution_summary = ExecutionSummary(
            execution_id=record.execution_id,
            plan_id=record.plan_id,
            changeset_id=record.changeset_id,
            status=record.status,
            verdict=record.verdict,
            risk_level=record.risk_level or "unknown",
            started_at=record.started_at,
            ended_at=record.ended_at,
            duration_seconds=record.duration_seconds,
            files_changed=record.files_changed,
            verification_passed=record.verification_passed,
            health_checks_passed=record.health_checks_passed,
            rolled_back=record.rolled_back,
            error_step=record.error_step,
            error_message=record.error_message
        )

        step_details = []
        for step in steps:
            step_details.append(StepDetail(
                id=step.id,
                step_num=step.step_num,
                step_name=step.step_name,
                status=step.status,
                started_at=step.started_at,
                ended_at=step.ended_at,
                duration_seconds=step.duration_seconds,
                error_code=step.error_code,
                error_message=step.error_message,
                log_ref=step.log_ref
            ))

        return ExecutionDetail(
            execution=execution_summary,
            steps=step_details,
            artifact_path=record.artifact_path or "N/A"
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get execution: {str(e)}")


@router.get("/{execution_id}/artifacts", response_model=ArtifactInfo)
async def get_execution_artifacts(execution_id: str):
    """
    Get artifact metadata for an execution.

    Returns:
        - artifact_path
        - 4件套 completeness (plan/changeset/decision/execution.json)
        - List of step logs (filenames only, not full content)
        - stdout/stderr availability

    Security: path whitelist enforced.
    """
    try:
        # Get execution record to get artifact path
        record = execution_store.get_execution(execution_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

        if not record.artifact_path:
            raise HTTPException(status_code=404, detail=f"No artifacts for execution {execution_id}")

        artifact_path = Path(record.artifact_path)

        # Security check
        if not validate_artifact_path(artifact_path):
            raise HTTPException(status_code=403, detail="Access to artifact path forbidden")

        if not artifact_path.exists():
            raise HTTPException(status_code=404, detail="Artifact directory not found")

        # Check 4件套
        four_piece_set = {
            "plan.json": (artifact_path / "plan.json").exists(),
            "changeset.json": (artifact_path / "changeset.json").exists(),
            "decision.json": (artifact_path / "decision.json").exists(),
            "execution.json": (artifact_path / "execution.json").exists()
        }

        artifacts_complete = all(four_piece_set.values())

        # List step logs
        step_logs = []
        steps_dir = artifact_path / "steps"
        if steps_dir.exists():
            step_logs = sorted([f.name for f in steps_dir.glob("*.log")])

        # Check stdout/stderr
        has_stdout = (artifact_path / "stdout.log").exists()
        has_stderr = (artifact_path / "stderr.log").exists()

        # Check backups directory
        backups_dir = artifact_path / "backups"
        has_backups = backups_dir.exists() and any(backups_dir.iterdir())

        return ArtifactInfo(
            artifact_path=str(artifact_path),
            artifacts_complete=artifacts_complete,
            four_piece_set=four_piece_set,
            step_logs=step_logs,
            has_stdout=has_stdout,
            has_stderr=has_stderr,
            has_backups=has_backups
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get artifacts: {str(e)}")


@router.get("/{execution_id}/replay")
async def replay_execution_endpoint(execution_id: str):
    """
    Replay execution from artifacts (read-only).

    Calls replay_execution() and returns structured summary.

    Note: Returns summary only, not full log content to avoid huge responses.
    """
    try:
        # Get execution record to get artifact path
        record = execution_store.get_execution(execution_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

        if not record.artifact_path:
            raise HTTPException(status_code=404, detail=f"No artifacts for execution {execution_id}")

        artifact_path = Path(record.artifact_path)

        # Security check
        if not validate_artifact_path(artifact_path):
            raise HTTPException(status_code=403, detail="Access to artifact path forbidden")

        # Replay execution from artifact directory
        execution_data = replay_execution(artifact_path)

        if not execution_data:
            raise HTTPException(status_code=404, detail="Failed to replay execution (missing artifacts)")

        # Return structured summary (truncate large content)
        summary = {
            "execution_id": execution_id,
            "plan": {
                "id": execution_data["plan"].get("id"),
                "intent": execution_data["plan"].get("intent"),
                "risk_level": execution_data["plan"].get("risk_level_proposed"),
                "affected_paths": execution_data["plan"].get("affected_paths", [])
            },
            "changeset": {
                "id": execution_data["changeset"].get("id"),
                "changes_count": len(execution_data["changeset"].get("changes", [])),
                "checksum": execution_data["changeset"].get("checksum")
            },
            "decision": {
                "id": execution_data["decision"].get("id"),
                "verdict": execution_data["decision"].get("verdict"),
                "risk_level_effective": execution_data["decision"].get("risk_level_effective"),
                "reasons": execution_data["decision"].get("reasons", [])
            },
            "execution": {
                "status": execution_data["execution"].get("status"),
                "success": execution_data["execution"].get("success"),
                "message": execution_data["execution"].get("message"),
                "files_changed": execution_data["execution"].get("files_changed"),
                "verification_passed": execution_data["execution"].get("verification_passed"),
                "health_checks_passed": execution_data["execution"].get("health_checks_passed")
            }
        }

        return summary

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to replay execution: {str(e)}")


@router.get("/{execution_id}/lineage", response_model=ExecutionLineage)
async def get_execution_lineage(
    execution_id: str,
    depth: int = Query(20, ge=1, le=100, description="Maximum traversal depth")
):
    """
    Get execution lineage (Phase 2.4-A).

    Returns:
        - execution: The target execution with graph fields
        - ancestors: List of parent executions (root → immediate parent)
        - descendants: List of child executions (BFS order)
        - siblings: Executions with same parent

    Examples:
        GET /executions/exec_123/lineage
        GET /executions/exec_123/lineage?depth=10
    """
    try:
        # Get lineage from store
        lineage = execution_store.get_execution_lineage(execution_id, depth=depth)

        if not lineage or not lineage.get("execution"):
            raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

        # Helper to convert ExecutionRecord to LineageExecutionSummary
        def to_lineage_summary(record) -> LineageExecutionSummary:
            return LineageExecutionSummary(
                execution_id=record.execution_id,
                plan_id=record.plan_id,
                status=record.status,
                verdict=record.verdict,
                risk_level=record.risk_level or "unknown",
                started_at=record.started_at,
                ended_at=record.ended_at,
                correlation_id=record.correlation_id,
                parent_execution_id=record.parent_execution_id,
                trigger_kind=record.trigger_kind,
                run_id=record.run_id,
                files_changed=record.files_changed
            )

        # Convert to response model
        return ExecutionLineage(
            execution=to_lineage_summary(lineage["execution"]),
            ancestors=[to_lineage_summary(r) for r in lineage.get("ancestors", [])],
            descendants=[to_lineage_summary(r) for r in lineage.get("descendants", [])],
            siblings=[to_lineage_summary(r) for r in lineage.get("siblings", [])]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get lineage: {str(e)}")


@router.get("/correlation/{correlation_id}", response_model=CorrelationChain)
async def get_correlation_chain(
    correlation_id: str,
    limit: int = Query(100, ge=1, le=500, description="Max executions to return")
):
    """
    Get all executions in a correlation chain (Phase 2.4-A).

    A correlation chain represents related executions in the same task context
    (e.g., original execution + retries + repairs).

    Examples:
        GET /executions/correlation/corr_abc123
        GET /executions/correlation/corr_abc123?limit=50
    """
    try:
        # Get all executions with this correlation_id
        executions = execution_store.list_executions_by_correlation(correlation_id, limit=limit)

        if not executions:
            raise HTTPException(status_code=404, detail=f"No executions found for correlation_id {correlation_id}")

        # Get root execution
        root = execution_store.get_root_execution(correlation_id)

        # Convert to response model
        def to_lineage_summary(record) -> LineageExecutionSummary:
            return LineageExecutionSummary(
                execution_id=record.execution_id,
                plan_id=record.plan_id,
                status=record.status,
                verdict=record.verdict,
                risk_level=record.risk_level or "unknown",
                started_at=record.started_at,
                ended_at=record.ended_at,
                correlation_id=record.correlation_id,
                parent_execution_id=record.parent_execution_id,
                trigger_kind=record.trigger_kind,
                run_id=record.run_id,
                files_changed=record.files_changed
            )

        return CorrelationChain(
            correlation_id=correlation_id,
            total_executions=len(executions),
            root_execution_id=root.execution_id if root else None,
            executions=[to_lineage_summary(r) for r in executions]
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get correlation chain: {str(e)}")

