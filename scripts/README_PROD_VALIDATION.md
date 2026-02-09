# Production Validation Script

**Phase 2.2-D: 生产验证脚本 (Production Validation Script)**

## Overview

`prod_validation.py` is a comprehensive smoke test script that validates the entire LonelyCat pipeline before each release. It runs through the complete Planner → WriteGate → Executor workflow and verifies that all components are working correctly.

## Purpose

This script serves as a **pre-release smoke test** to ensure:
1. **Environment** is correctly configured
2. **Services** are healthy (optional)
3. **Low-risk changes** can be submitted and approved
4. **Full pipeline** executes without errors
5. **Artifacts** are created and stored correctly
6. **Database records** are complete and queryable

## Usage

### Basic Usage

```bash
# Run with temporary workspace (recommended for testing)
python scripts/prod_validation.py --skip-services

# Run with specific workspace
python scripts/prod_validation.py --workspace /path/to/workspace

# Run with real service health checks (requires services running)
python scripts/prod_validation.py
```

### Options

- `--workspace PATH`: Specify workspace directory (default: creates temp directory)
- `--skip-services`: Skip service health checks (recommended for local testing)

### Exit Codes

- `0`: All validations passed ✅ (safe to release)
- `1`: Some validations failed ❌ (do NOT release)
- `2`: Setup error ⚠️ (misconfiguration)

## What It Tests

### 1. Environment Setup
- Workspace directory creation
- `.lonelycat` directory initialization
- SQLite database initialization

### 2. Service Health (Optional)
- Service infrastructure availability
- HTTP health check capability (requires `httpx`)
- Real service endpoint checks (if services running)

### 3. Low-Risk Docs Change
- Creates test documentation file (`TEST_SMOKE.md`)
- Generates `ChangePlan` with low risk level
- Generates `ChangeSet` with CREATE operation
- Computes and verifies checksum

### 4. WriteGate Governance Check
- Evaluates plan against policies
- Validates risk assessment
- Expects `ALLOW` verdict for low-risk docs
- Records audit hashes

### 5. Change Execution
- Executes approved changeset
- Applies file changes atomically
- Runs verification commands
- Runs health checks (if configured)
- Records execution status

### 6. Artifact Verification
- Checks artifact directory exists: `.lonelycat/executions/{exec_id}/`
- Validates **4件套** (4-piece set):
  - `plan.json` - Complete plan specification
  - `changeset.json` - File changes
  - `decision.json` - Governance decision
  - `execution.json` - Execution results
- Verifies JSON files are parseable
- Checks step logs directory
- Verifies stdout/stderr logs

### 7. SQLite Record Verification
- Queries execution record from database
- Validates execution status (`completed`)
- Checks execution metadata (duration, files changed)
- Verifies execution steps (if recorded)
- Validates database statistics

### 8. Cleanup
- Removes test file (`TEST_SMOKE.md`)
- Optionally cleans up artifacts (for testing)

## Sample Output

```
[22:31:56] [i] ============================================================
[22:31:56] [i] LonelyCat Production Validation - Phase 2.2-D
[22:31:56] [i] ============================================================
[22:31:56] >>> Step 1: Environment Setup
[22:31:56] [OK] Environment Setup: PASSED - Workspace: /tmp/lonelycat_validation_xyz
[22:31:56] [!] Step 2: Service Health Checks (SKIPPED)
[22:31:56] >>> Step 3: Create Low-Risk Docs Change
[22:31:56] [OK] Docs Change Creation: PASSED - Created plan plan_abc with 1 change
[22:31:56] >>> Step 4: WriteGate Governance Check
[22:31:56] [OK] WriteGate Evaluation: PASSED - Verdict: allow, Risk: low
[22:31:56] >>> Step 5: Execute Change
[22:31:56] [OK] Change Execution: PASSED - Status: completed, Files: 1
[22:31:56] >>> Step 6: Verify Artifacts
[22:31:56] [OK] Artifact 4件套: PASSED - All 4 JSON artifacts valid in exec_123
[22:31:56] [i] Found 7 step logs in steps
[22:31:56] [i] stdout.log and stderr.log present
[22:31:56] >>> Step 7: Verify SQLite Records
[22:31:56] [OK] SQLite Execution Record: PASSED - Record exists with status 'completed'
[22:31:56] [i] Found 0 step records in database
[22:31:56] [i] Database stats: 1 total, 100.0% success rate
[22:31:56] >>> Step 8: Cleanup
[22:31:56] [i] Cleanup completed
[22:31:56] [i] ============================================================
[22:31:56] [i] VALIDATION SUMMARY
[22:31:56] [i] ============================================================
[22:31:56] [i] [OK] PASS: Environment Setup
[22:31:56] [i] [OK] PASS: Docs Change Creation
[22:31:56] [i] [OK] PASS: WriteGate Evaluation
[22:31:56] [i] [OK] PASS: Change Execution
[22:31:56] [i] [OK] PASS: Artifact 4件套
[22:31:56] [i] [OK] PASS: SQLite Execution Record
[22:31:56] [i] ============================================================
[22:31:56] [OK] RESULT: 6/6 tests passed
[22:31:56] [i] ============================================================

[OK] All validations passed! Ready for release.
```

## Integration with CI/CD

### Pre-Release Check

Add to your release workflow:

```yaml
# .github/workflows/release.yml
jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
      - name: Run production validation
        run: |
          python scripts/prod_validation.py --skip-services
```

### Local Pre-Commit Hook

Add to `.git/hooks/pre-push`:

```bash
#!/bin/bash
echo "Running production validation..."
python scripts/prod_validation.py --skip-services
if [ $? -ne 0 ]; then
    echo "Production validation failed. Push aborted."
    exit 1
fi
```

## Architecture Validation

This script validates the complete LonelyCat architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                    Production Validation                     │
│                                                              │
│  1. User Intent: "Add docs"                                 │
│           ↓                                                  │
│  2. Planner Layer: Decompose → State Machine → Risk Shape   │
│           ↓                                                  │
│  3. ChangePlan + ChangeSet (structured)                      │
│           ↓                                                  │
│  4. WriteGate: Policy Evaluation → ALLOW                     │
│           ↓                                                  │
│  5. Host Executor:                                           │
│      - Validate approval                                     │
│      - Create backup                                         │
│      - Apply changes (atomic)                                │
│      - Run verification                                      │
│      - Run health checks                                     │
│      - Record artifacts (4件套)                              │
│      - Record database (SQLite)                              │
│           ↓                                                  │
│  6. Validation: Artifacts + Database complete ✅             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Troubleshooting

### Common Issues

**Issue**: `WriteGate evaluation failed`
- **Cause**: Policies file not found or invalid
- **Fix**: Ensure `agent/policies/default.yaml` exists

**Issue**: `Execution failed: Verification failed`
- **Cause**: Verification command not compatible with OS
- **Fix**: Check verification_plan uses cross-platform commands

**Issue**: `Artifact directory not found`
- **Cause**: Executor not creating artifact directory
- **Fix**: Check ArtifactManager initialization

**Issue**: `SQLite record not found`
- **Cause**: Database not initialized or execution not recorded
- **Fix**: Check ExecutionStore initialization and record_execution_start

### Windows-Specific Notes

- **Encoding**: Console may show `����` instead of Chinese characters (cosmetic only)
- **Verification commands**: Use `exit 0` instead of Unix `true`
- **Path separators**: Script handles Windows paths correctly

## Development

### Adding New Validation Tests

1. Add test method to `ProductionValidator` class:

```python
def _validate_new_feature(self) -> bool:
    """Validate new feature."""
    try:
        # Test logic here
        self.record_result(
            "New Feature",
            True,
            "Feature works correctly"
        )
        return True
    except Exception as e:
        self.record_result(
            "New Feature",
            False,
            f"Feature failed: {e}"
        )
        return False
```

2. Add call in `run_all_validations()`:

```python
# Step N: New Feature
self.log("Step N: New Feature", "STEP")
if not self._validate_new_feature():
    return False
```

### Running Individual Components

The script can be imported and individual validators run:

```python
from scripts.prod_validation import ProductionValidator

validator = ProductionValidator(workspace_root, skip_services=True)

# Run just environment setup
validator._validate_environment()

# Check results
for test_name, passed, message in validator.results:
    print(f"{test_name}: {'PASS' if passed else 'FAIL'} - {message}")
```

## Related Documentation

- [Phase 2.2-A: Artifact Management](../packages/executor/artifacts.py)
- [Phase 2.2-B: Execution History Storage](../packages/executor/storage.py)
- [Phase 2.2-C: Real Service Health Checks](../packages/executor/health.py)
- [Phase 2 Acceptance Tests](../packages/executor/tests/test_acceptance.py)

## Version History

- **v1.0.0** (Phase 2.2-D): Initial release
  - 6 core validation tests
  - End-to-end pipeline validation
  - Artifact and database verification
  - Windows and Unix compatibility

## Success Criteria

✅ **验收 (Acceptance)**: 你每次发版前跑它，能当'冒烟测试'

This script is now the **official pre-release smoke test** for LonelyCat. Run it before every release to ensure the entire pipeline is working correctly.
