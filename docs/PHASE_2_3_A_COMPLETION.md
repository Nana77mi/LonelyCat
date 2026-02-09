# Phase 2.3-A: Observability API - Implementation Summary

## Overview

Implemented read-only REST API endpoints for execution history observability, built on top of Phase 2.2's SQLite + Artifacts infrastructure.

## Endpoints Implemented

### 1. List Executions
```
GET /executions?limit=20&offset=0&status=&verdict=&risk_level=&since=
```

**Purpose**: Query execution history with filters
**Maps to**: `ExecutionStore.list_executions()`
**Query Parameters**:
- `limit` (1-100, default 20): Number of results
- `offset` (default 0): Pagination offset
- `status`: Filter by status (pending, completed, failed, rolled_back)
- `verdict`: Filter by verdict (allow, need_approval, deny)
- `risk_level`: Filter by risk (low, medium, high, critical)
- `since`: ISO timestamp - only show executions after this time

**Response**:
```json
{
  "executions": [
    {
      "execution_id": "exec_abc123",
      "status": "completed",
      "verdict": "allow",
      "risk_level": "low",
      "started_at": "2024-01-01T12:00:00Z",
      "duration_seconds": 2.5,
      "files_changed": 3,
      "verification_passed": true,
      "health_checks_passed": true,
      "error_step": null,
      "error_message": null
    }
  ],
  "total": 42,
  "limit": 20,
  "offset": 0
}
```

### 2. Get Execution Details
```
GET /executions/{execution_id}
```

**Purpose**: Get full execution details with steps timeline
**Maps to**: `get_execution()` + `get_execution_steps()`
**Response**:
```json
{
  "execution": { /* ExecutionSummary */ },
  "steps": [
    {
      "id": 1,
      "step_num": 1,
      "step_name": "validate",
      "status": "completed",
      "started_at": "2024-01-01T12:00:00Z",
      "ended_at": "2024-01-01T12:00:01Z",
      "duration_seconds": 1.0,
      "error_code": null,
      "error_message": null,
      "log_ref": "steps/01_validate.log"
    }
  ],
  "artifact_path": ".lonelycat/executions/exec_abc123"
}
```

### 3. Get Artifact Metadata
```
GET /executions/{execution_id}/artifacts
```

**Purpose**: Get artifact completeness info (no full content)
**Security**: Path whitelist enforced
**Response**:
```json
{
  "artifact_path": ".lonelycat/executions/exec_abc123",
  "artifacts_complete": true,
  "four_piece_set": {
    "plan.json": true,
    "changeset.json": true,
    "decision.json": true,
    "execution.json": true
  },
  "step_logs": ["01_validate.log", "02_apply.log"],
  "has_stdout": true,
  "has_stderr": true,
  "has_backups": true
}
```

### 4. Replay Execution
```
GET /executions/{execution_id}/replay
```

**Purpose**: Replay execution from artifacts (structured summary)
**Maps to**: `replay_execution()`
**Response**:
```json
{
  "execution_id": "exec_abc123",
  "plan": {
    "id": "plan_xyz",
    "intent": "Add feature X",
    "risk_level": "low",
    "affected_paths": ["file1.py", "file2.py"]
  },
  "changeset": {
    "id": "changeset_xyz",
    "changes_count": 2,
    "checksum": "abc123"
  },
  "decision": {
    "id": "decision_xyz",
    "verdict": "allow",
    "risk_level_effective": "low",
    "reasons": []
  },
  "execution": {
    "status": "completed",
    "success": true,
    "message": "Execution completed successfully",
    "files_changed": 2,
    "verification_passed": true,
    "health_checks_passed": true
  }
}
```

### 5. Get Statistics
```
GET /executions/statistics
```

**Purpose**: Get aggregated execution metrics
**Maps to**: `ExecutionStore.get_statistics()`
**Response**:
```json
{
  "total_executions": 42,
  "by_status": {
    "completed": 35,
    "failed": 5,
    "rolled_back": 2
  },
  "by_verdict": {
    "allow": 40,
    "deny": 2
  },
  "by_risk_level": {
    "low": 30,
    "medium": 10,
    "high": 2
  },
  "success_rate_percent": 83.3,
  "avg_duration_seconds": 2.5
}
```

## Security Boundaries (A2)

### Path Whitelist
```python
def validate_artifact_path(artifact_path: Path) -> bool:
    """Only allow reading from .lonelycat/executions/**"""
    executions_dir = WORKSPACE_ROOT / ".lonelycat" / "executions"
    resolved = artifact_path.resolve()
    return resolved.is_relative_to(executions_dir)
```

**Enforced on**:
- `/executions/{id}/artifacts`
- `/executions/{id}/replay`

**Protection against**:
- Path traversal (`../../../etc/passwd`)
- Access to other directories
- Symlink attacks

### Size Limits (Future Enhancement)
- **TODO**: Add pagination/tail for large logs
- **TODO**: Max response size limit (e.g., 10MB)
- **Current**: Returns metadata only, not full log content

## Testing

Created comprehensive test suite: `apps/core-api/tests/test_executions_api.py`

**Test Coverage**:
1. ✅ List executions
2. ✅ List with filters (status, risk, verdict)
3. ✅ Get execution details with steps
4. ✅ 404 for non-existent execution
5. ✅ Get artifacts metadata
6. ✅ Replay execution
7. ✅ Security - path whitelist validation
8. ✅ Statistics endpoint
9. ✅ Pagination (limit/offset)

**Run tests**:
```bash
cd apps/core-api
pytest tests/test_executions_api.py -v
```

## Integration

### Added to main.py
```python
from app.api.executions import router as executions_router
app.include_router(executions_router)  # Phase 2.3-A
```

### Database Initialization
```python
# Automatically initializes executor.db on startup
EXECUTOR_DB_PATH = WORKSPACE_ROOT / ".lonelycat" / "executor.db"
init_executor_db(EXECUTOR_DB_PATH)
execution_store = ExecutionStore(WORKSPACE_ROOT)
```

## Files Created

1. **`apps/core-api/app/api/executions.py`** (400+ lines)
   - 5 API endpoints
   - Security boundaries
   - Pydantic models for request/response

2. **`apps/core-api/tests/test_executions_api.py`** (300+ lines)
   - 9 comprehensive tests
   - Security testing
   - Integration with HostExecutor

## Usage Examples

### curl Examples
```bash
# List recent 20 executions
curl http://localhost:5173/executions

# Filter by failed status
curl http://localhost:5173/executions?status=failed&limit=10

# Get execution details
curl http://localhost:5173/executions/exec_abc123

# Get artifact metadata
curl http://localhost:5173/executions/exec_abc123/artifacts

# Replay execution
curl http://localhost:5173/executions/exec_abc123/replay

# Get statistics
curl http://localhost:5173/executions/statistics
```

### Python Client Example
```python
import requests

# List failed executions
response = requests.get(
    "http://localhost:5173/executions",
    params={"status": "failed", "risk_level": "high"}
)
executions = response.json()["executions"]

for exec in executions:
    print(f"Failed: {exec['execution_id']} - {exec['error_message']}")

    # Get details
    details = requests.get(
        f"http://localhost:5173/executions/{exec['execution_id']}"
    ).json()

    # Find which step failed
    for step in details["steps"]:
        if step["status"] == "failed":
            print(f"  Failed at step: {step['step_name']}")
            print(f"  Error: {step['error_code']}")
```

## Acceptance Criteria ✅

From Phase 2.3-A spec:

- ✅ **curl 能查最近 20 次**: `GET /executions?limit=20`
- ✅ **按 status/risk/verdict 过滤**: Query parameters supported
- ✅ **单条能查 steps**: `GET /executions/{id}` returns steps timeline
- ✅ **artifact 完整性**: `GET /executions/{id}/artifacts` shows 4件套 completeness
- ✅ **路径白名单**: `validate_artifact_path()` security boundary
- ✅ **最大返回大小**: Returns metadata only, not full logs

## Next Steps (Phase 2.3-B)

With API ready, next is Web Console UI:
1. **Execution List Page** (`/executions`)
   - Table with filtering
   - Sortable columns
   - Pagination controls

2. **Execution Detail Page** (`/executions/{id}`)
   - Summary card
   - Steps timeline
   - Artifacts panel

## Notes

- **MVP完成**: Core API infrastructure ready
- **性能**: Direct SQLite queries, no caching yet (fine for MVP)
- **安全**: Path whitelist enforced, but could add rate limiting
- **可扩展**: Easy to add more filters/endpoints as needed

---

**Status**: Phase 2.3-A Complete ✅
**Ready for**: Phase 2.3-B (Web Console UI)
