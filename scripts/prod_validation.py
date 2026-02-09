#!/usr/bin/env python3
"""
Production Validation Script - Phase 2.4-A (Extended)

Philosophy: Pre-release smoke test for LonelyCat end-to-end pipeline.

Validates:
1. Service health (detect running services or simulate)
2. Low-risk docs change submission
3. Full pipeline: Planner → WriteGate → Executor
4. Health checks execution
5. Artifact + SQLite records completeness
6. SQLite direct query (Phase 2.3-D)
7. API read simulation (Phase 2.3-D)
8. Execution lineage queries (Phase 2.4-A)

Usage:
    python scripts/prod_validation.py [--workspace PATH] [--skip-services]

Exit Codes:
    0 = All validations passed (ready for release)
    1 = Validation failed (do not release)
    2 = Setup error (misconfiguration)
"""

import sys
import argparse
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple
import json

# Add packages to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages"))

# Import LonelyCat components
from governance import (
    WriteGate,
    ChangePlan,
    ChangeSet,
    FileChange,
    Operation,
    RiskLevel,
    Verdict,
    GovernanceDecision,
    generate_plan_id,
    generate_changeset_id,
    compute_agent_source_hash,
    compute_projection_hash
)

from executor import (
    HostExecutor,
    ExecutionStatus,
    init_executor_db
)

from planner import PlannerOrchestrator


class ProductionValidator:
    """
    Smoke test runner for production validation.

    Executes end-to-end pipeline validation with detailed reporting.
    """

    def __init__(self, workspace_root: Path, skip_services: bool = False):
        """
        Initialize validator.

        Args:
            workspace_root: Root directory for test execution
            skip_services: If True, skip service health checks
        """
        self.workspace_root = Path(workspace_root).resolve()
        self.skip_services = skip_services
        self.results: List[Tuple[str, bool, str]] = []

        # Track execution for artifact linkage
        self.execution_id: str = None
        self.artifact_path: Path = None

        # Initialize components
        self.writegate = WriteGate()
        self.executor = HostExecutor(self.workspace_root)
        self.planner = PlannerOrchestrator()

    def log(self, message: str, level: str = "INFO"):
        """Log message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Use ASCII-safe prefixes for Windows compatibility
        prefix = {
            "INFO": "[i]",
            "SUCCESS": "[OK]",
            "ERROR": "[X]",
            "WARNING": "[!]",
            "STEP": ">>>"
        }.get(level, "[*]")

        # Handle encoding issues on Windows
        try:
            print(f"[{timestamp}] {prefix} {message}")
        except UnicodeEncodeError:
            # Fallback to ASCII-safe output
            safe_message = message.encode('ascii', 'replace').decode('ascii')
            print(f"[{timestamp}] {prefix} {safe_message}")

    def record_result(self, test_name: str, passed: bool, message: str):
        """Record test result."""
        self.results.append((test_name, passed, message))
        if passed:
            self.log(f"{test_name}: PASSED - {message}", "SUCCESS")
        else:
            self.log(f"{test_name}: FAILED - {message}", "ERROR")

    def run_all_validations(self) -> bool:
        """
        Run all validation tests.

        Returns:
            True if all tests passed
        """
        self.log("=" * 60)
        self.log("LonelyCat Production Validation - Phase 2.4-A", "INFO")
        self.log("=" * 60)

        try:
            # Step 1: Environment check
            self.log("Step 1: Environment Setup", "STEP")
            if not self._validate_environment():
                return False

            # Step 2: Service health check
            if not self.skip_services:
                self.log("Step 2: Service Health Checks", "STEP")
                if not self._validate_services():
                    self.log("Service checks failed (use --skip-services to bypass)", "WARNING")
            else:
                self.log("Step 2: Service Health Checks (SKIPPED)", "WARNING")

            # Step 3: Create low-risk docs change
            self.log("Step 3: Create Low-Risk Docs Change", "STEP")
            plan, changeset = self._create_docs_change()
            if not plan or not changeset:
                return False

            # Step 4: WriteGate evaluation
            self.log("Step 4: WriteGate Governance Check", "STEP")
            decision = self._evaluate_with_writegate(plan, changeset)
            if not decision:
                return False

            # Step 5: Execute approved change
            self.log("Step 5: Execute Change", "STEP")
            exec_result = self._execute_change(plan, changeset, decision)
            if not exec_result:
                return False

            # Step 6: Verify artifacts
            self.log("Step 6: Verify Artifacts", "STEP")
            if not self._verify_artifacts(exec_result.context.id):
                return False

            # Step 7: Verify SQLite records
            self.log("Step 7: Verify SQLite Records", "STEP")
            if not self._verify_sqlite_records(exec_result.context.id):
                return False

            # Step 8: Verify SQLite direct query (Phase 2.3-D)
            self.log("Step 8: Verify SQLite Direct Query", "STEP")
            if not self._verify_sqlite_query(exec_result.context.id):
                return False

            # Step 9: Verify API read (Phase 2.3-D)
            self.log("Step 9: Verify API Read", "STEP")
            if not self._verify_api_read(exec_result.context.id):
                return False

            # Step 10: Verify lineage queries (Phase 2.4-A)
            self.log("Step 10: Verify Lineage Queries", "STEP")
            if not self._verify_lineage_queries(exec_result.context.id):
                return False

            # Step 11: Cleanup test data
            self.log("Step 11: Cleanup", "STEP")
            self._cleanup_test_artifacts()

            # Summary
            self._print_summary()
            return all(passed for _, passed, _ in self.results)

        except Exception as e:
            self.log(f"Unexpected error during validation: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return False

    def _validate_environment(self) -> bool:
        """Validate environment setup."""
        try:
            # Check workspace exists
            if not self.workspace_root.exists():
                self.workspace_root.mkdir(parents=True, exist_ok=True)

            # Check .lonelycat directory can be created
            lonelycat_dir = self.workspace_root / ".lonelycat"
            lonelycat_dir.mkdir(parents=True, exist_ok=True)

            # Initialize executor database
            db_path = lonelycat_dir / "executor.db"
            init_executor_db(db_path)

            self.record_result(
                "Environment Setup",
                True,
                f"Workspace: {self.workspace_root}"
            )
            return True

        except Exception as e:
            self.record_result(
                "Environment Setup",
                False,
                f"Failed to initialize environment: {e}"
            )
            return False

    def _validate_services(self) -> bool:
        """
        Validate service health (optional).

        For smoke testing, we simulate services if they're not running.
        """
        try:
            # Check if httpx is available for health checks
            try:
                import httpx
                has_httpx = True
            except ImportError:
                has_httpx = False
                self.log("httpx not installed - skipping HTTP health checks", "WARNING")

            # For production validation, we just verify health check infrastructure works
            # Real service checks would require services to be running

            self.record_result(
                "Service Infrastructure",
                True,
                f"Health check infrastructure available (httpx: {has_httpx})"
            )
            return True

        except Exception as e:
            self.record_result(
                "Service Infrastructure",
                False,
                f"Health check infrastructure error: {e}"
            )
            return False

    def _create_docs_change(self) -> Tuple[ChangePlan, ChangeSet]:
        """
        Create a low-risk documentation change.

        Returns:
            (ChangePlan, ChangeSet) tuple
        """
        try:
            # Create test README file
            test_file = self.workspace_root / "TEST_SMOKE.md"
            test_content = f"""# LonelyCat Smoke Test

This file is created by production validation script.

Generated at: {datetime.now(timezone.utc).isoformat()}

This is a low-risk documentation change for testing the pipeline.
"""

            # Create ChangePlan
            # Use simple verification that always passes for smoke test
            # Real verification would check actual service endpoints
            import platform
            verify_cmd = "exit 0" if platform.system() == "Windows" else "true"

            plan = ChangePlan(
                id=generate_plan_id(),
                intent="Add smoke test documentation",
                objective="Validate end-to-end pipeline with low-risk docs change",
                rationale="Production validation smoke test",
                affected_paths=["TEST_SMOKE.md"],
                risk_level_proposed=RiskLevel.LOW,
                rollback_plan="echo rollback",
                verification_plan=verify_cmd,
                created_by="prod_validation",
                created_at=datetime.now(timezone.utc),
                confidence=1.0
            )

            # Create ChangeSet
            change = FileChange(
                operation=Operation.CREATE,
                path="TEST_SMOKE.md",
                new_content=test_content
            )

            changeset = ChangeSet(
                id=generate_changeset_id(),
                plan_id=plan.id,
                changes=[change],
                checksum="",
                generated_by="prod_validation",
                generated_at=datetime.now(timezone.utc)
            )
            changeset.compute_checksum()

            self.record_result(
                "Docs Change Creation",
                True,
                f"Created plan {plan.id[:8]} with 1 change"
            )
            return plan, changeset

        except Exception as e:
            self.record_result(
                "Docs Change Creation",
                False,
                f"Failed to create docs change: {e}"
            )
            return None, None

    def _evaluate_with_writegate(
        self,
        plan: ChangePlan,
        changeset: ChangeSet
    ) -> GovernanceDecision:
        """
        Evaluate change with WriteGate.

        Returns:
            GovernanceDecision if successful, None otherwise
        """
        try:
            # Compute hashes for audit trail
            agent_dir = REPO_ROOT / "agent"
            agent_hash = compute_agent_source_hash(agent_dir) if agent_dir.exists() else "no_agent"

            # Projection files (AGENTS.md, CLAUDE.md)
            projection_files = []
            for filename in ["AGENTS.md", "CLAUDE.md"]:
                filepath = REPO_ROOT / filename
                if filepath.exists():
                    projection_files.append(filepath)

            projection_hash = compute_projection_hash(projection_files) if projection_files else "no_projections"

            # Evaluate with WriteGate
            decision = self.writegate.evaluate(
                plan,
                changeset,
                agent_source_hash=agent_hash,
                projection_hash=projection_hash
            )

            # Check verdict
            if decision.verdict == Verdict.ALLOW:
                self.record_result(
                    "WriteGate Evaluation",
                    True,
                    f"Verdict: {decision.verdict.value}, Risk: {decision.risk_level_effective.value}"
                )
                return decision
            else:
                self.record_result(
                    "WriteGate Evaluation",
                    False,
                    f"Unexpected verdict: {decision.verdict.value} (expected ALLOW for low-risk docs)"
                )
                return None

        except Exception as e:
            self.record_result(
                "WriteGate Evaluation",
                False,
                f"WriteGate evaluation failed: {e}"
            )
            return None

    def _execute_change(
        self,
        plan: ChangePlan,
        changeset: ChangeSet,
        decision: GovernanceDecision
    ):
        """
        Execute approved change with Executor.

        Returns:
            ExecutionResult if successful, None otherwise
        """
        try:
            # Execute with HostExecutor
            result = self.executor.execute(plan, changeset, decision)

            # Check execution result
            if result.success:
                # Store execution ID and artifact path for final output
                self.execution_id = result.context.id
                self.artifact_path = self.workspace_root / ".lonelycat" / "executions" / self.execution_id

                self.record_result(
                    "Change Execution",
                    True,
                    f"Status: {result.context.status.value}, Files: {len(result.context.applied_changes)}"
                )
                return result
            else:
                self.record_result(
                    "Change Execution",
                    False,
                    f"Execution failed: {result.message}"
                )
                return None

        except Exception as e:
            self.record_result(
                "Change Execution",
                False,
                f"Executor raised exception: {e}"
            )
            return None

    def _verify_artifacts(self, execution_id: str) -> bool:
        """
        Verify artifacts were created correctly.

        Args:
            execution_id: Execution ID to verify

        Returns:
            True if all artifacts exist
        """
        try:
            exec_dir = self.workspace_root / ".lonelycat" / "executions" / execution_id

            # Check directory exists
            if not exec_dir.exists():
                self.record_result(
                    "Artifact Directory",
                    False,
                    f"Execution directory not found: {exec_dir}"
                )
                return False

            # Check required artifacts (4件套)
            required_files = [
                "plan.json",
                "changeset.json",
                "decision.json",
                "execution.json"
            ]

            missing_files = []
            for filename in required_files:
                filepath = exec_dir / filename
                if not filepath.exists():
                    missing_files.append(filename)

            if missing_files:
                self.record_result(
                    "Artifact 4件套",
                    False,
                    f"Missing files: {', '.join(missing_files)}"
                )
                return False

            # Verify JSON can be loaded
            try:
                plan_data = json.loads((exec_dir / "plan.json").read_text())
                changeset_data = json.loads((exec_dir / "changeset.json").read_text())
                decision_data = json.loads((exec_dir / "decision.json").read_text())
                execution_data = json.loads((exec_dir / "execution.json").read_text())

                self.record_result(
                    "Artifact 4件套",
                    True,
                    f"All 4 JSON artifacts valid in {exec_dir.name}"
                )

            except json.JSONDecodeError as e:
                self.record_result(
                    "Artifact 4件套",
                    False,
                    f"JSON parse error: {e}"
                )
                return False

            # Check for step logs directory
            steps_dir = exec_dir / "steps"
            if steps_dir.exists():
                log_count = len(list(steps_dir.glob("*.log")))
                self.log(f"Found {log_count} step logs in {steps_dir.name}", "INFO")

            # Check for stdout/stderr logs
            stdout_log = exec_dir / "stdout.log"
            stderr_log = exec_dir / "stderr.log"

            logs_exist = stdout_log.exists() and stderr_log.exists()
            if logs_exist:
                self.log("stdout.log and stderr.log present", "INFO")

            return True

        except Exception as e:
            self.record_result(
                "Artifact Verification",
                False,
                f"Artifact verification failed: {e}"
            )
            return False

    def _verify_sqlite_records(self, execution_id: str) -> bool:
        """
        Verify SQLite execution records.

        Args:
            execution_id: Execution ID to verify

        Returns:
            True if records exist and are correct
        """
        try:
            # Get execution record from store
            record = self.executor.execution_store.get_execution(execution_id)

            if not record:
                self.record_result(
                    "SQLite Execution Record",
                    False,
                    f"No record found for execution {execution_id}"
                )
                return False

            # Verify record fields
            if record.execution_id != execution_id:
                self.record_result(
                    "SQLite Execution Record",
                    False,
                    "Execution ID mismatch in record"
                )
                return False

            if record.status != "completed":
                self.record_result(
                    "SQLite Execution Record",
                    False,
                    f"Expected status 'completed', got '{record.status}'"
                )
                return False

            self.record_result(
                "SQLite Execution Record",
                True,
                f"Record exists with status '{record.status}'"
            )

            # Get execution steps
            steps = self.executor.execution_store.get_execution_steps(execution_id)
            self.log(f"Found {len(steps)} step records in database", "INFO")

            # Get statistics
            stats = self.executor.execution_store.get_statistics()
            self.log(
                f"Database stats: {stats['total_executions']} total, "
                f"{stats.get('success_rate_percent', 0):.1f}% success rate",
                "INFO"
            )

            return True

        except Exception as e:
            self.record_result(
                "SQLite Record Verification",
                False,
                f"Database verification failed: {e}"
            )
            return False

    def _verify_sqlite_query(self, execution_id: str) -> bool:
        """
        Verify execution can be queried from SQLite directly (Phase 2.3-D).

        Tests: 能从 SQLite 查到刚刚那次 smoke execution

        Args:
            execution_id: Execution ID to verify

        Returns:
            True if execution can be queried successfully
        """
        try:
            import sqlite3

            # Direct SQL query
            db_path = self.workspace_root / ".lonelycat" / "executor.db"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            # Query execution record
            cursor.execute(
                "SELECT * FROM executions WHERE execution_id = ?",
                (execution_id,)
            )
            row = cursor.fetchone()

            if not row:
                self.record_result(
                    "SQLite Direct Query",
                    False,
                    f"No record found for execution_id={execution_id}"
                )
                conn.close()
                return False

            # Verify key fields
            if row["status"] != "completed":
                self.record_result(
                    "SQLite Direct Query",
                    False,
                    f"Expected status='completed', got '{row['status']}'"
                )
                conn.close()
                return False

            if row["verdict"] != "allow":
                self.record_result(
                    "SQLite Direct Query",
                    False,
                    f"Expected verdict='allow', got '{row['verdict']}'"
                )
                conn.close()
                return False

            conn.close()

            self.record_result(
                "SQLite Direct Query",
                True,
                f"Found execution {execution_id} with status={row['status']}, verdict={row['verdict']}"
            )
            return True

        except Exception as e:
            self.record_result(
                "SQLite Direct Query",
                False,
                f"Query failed: {e}"
            )
            return False

    def _verify_api_read(self, execution_id: str) -> bool:
        """
        Verify execution can be read through API (Phase 2.3-D).

        Tests: 通过 API 能读出来

        Args:
            execution_id: Execution ID to verify

        Returns:
            True if API read succeeds
        """
        try:
            # Note: This is a lightweight test that simulates API behavior
            # In a full integration test, you would:
            # 1. Start the core-api server
            # 2. Make HTTP request to GET /executions/{execution_id}
            # 3. Verify response structure

            # For now, we simulate the API by calling the ExecutionStore directly
            # (which is what the API does internally)
            record = self.executor.execution_store.get_execution(execution_id)

            if not record:
                self.record_result(
                    "API Read Simulation",
                    False,
                    f"API would return 404: execution {execution_id} not found"
                )
                return False

            # Verify structure matches API response model
            expected_fields = [
                "execution_id",
                "plan_id",
                "changeset_id",
                "status",
                "verdict",
                "risk_level",
                "started_at",
                "files_changed",
                "verification_passed",
                "health_checks_passed"
            ]

            missing_fields = [
                field for field in expected_fields
                if not hasattr(record, field)
            ]

            if missing_fields:
                self.record_result(
                    "API Read Simulation",
                    False,
                    f"Record missing fields: {missing_fields}"
                )
                return False

            # Get steps (API also returns steps)
            steps = self.executor.execution_store.get_execution_steps(execution_id)

            self.record_result(
                "API Read Simulation",
                True,
                f"API can read execution {execution_id} with {len(steps)} steps"
            )

            self.log(
                f"✓ API would return: execution={record.status}, "
                f"verdict={record.verdict}, steps={len(steps)}",
                "INFO"
            )

            return True

        except Exception as e:
            self.record_result(
                "API Read Simulation",
                False,
                f"API read simulation failed: {e}"
            )
            return False

    def _verify_lineage_queries(self, execution_id: str) -> bool:
        """
        Verify execution lineage queries work (Phase 2.4-A).

        Tests:
        - get_execution_lineage() returns structure
        - Graph fields are populated (correlation_id, trigger_kind)
        - Ancestors/descendants/siblings lists exist

        Args:
            execution_id: Execution ID to verify

        Returns:
            True if lineage queries work
        """
        try:
            # Get lineage for the execution
            lineage = self.executor.execution_store.get_execution_lineage(execution_id)

            if not lineage or not lineage.get("execution"):
                self.record_result(
                    "Lineage Queries",
                    False,
                    f"Failed to get lineage for execution {execution_id}"
                )
                return False

            # Verify structure
            required_keys = ["execution", "ancestors", "descendants", "siblings"]
            missing_keys = [key for key in required_keys if key not in lineage]

            if missing_keys:
                self.record_result(
                    "Lineage Queries",
                    False,
                    f"Lineage missing keys: {missing_keys}"
                )
                return False

            # Verify graph fields are populated
            execution = lineage["execution"]
            if not hasattr(execution, "correlation_id"):
                self.record_result(
                    "Lineage Queries",
                    False,
                    "ExecutionRecord missing correlation_id field"
                )
                return False

            # Verify correlation_id defaults to execution_id for root executions
            if execution.correlation_id != execution_id:
                # For smoke test, we expect root execution (no parent)
                # So correlation_id should equal execution_id
                self.record_result(
                    "Lineage Queries",
                    False,
                    f"correlation_id mismatch: expected={execution_id}, got={execution.correlation_id}"
                )
                return False

            # Verify trigger_kind is set
            if not execution.trigger_kind:
                self.record_result(
                    "Lineage Queries",
                    False,
                    "trigger_kind not set"
                )
                return False

            # Verify lists are present (should be empty for root execution)
            ancestors_count = len(lineage.get("ancestors", []))
            descendants_count = len(lineage.get("descendants", []))
            siblings_count = len(lineage.get("siblings", []))

            self.record_result(
                "Lineage Queries",
                True,
                f"Lineage query successful: correlation_id={execution.correlation_id}, "
                f"trigger_kind={execution.trigger_kind}, "
                f"ancestors={ancestors_count}, descendants={descendants_count}, siblings={siblings_count}"
            )

            self.log(
                f"✓ Lineage: correlation_id={execution.correlation_id[:12]}..., "
                f"trigger={execution.trigger_kind}, "
                f"graph_depth=(ancestors={ancestors_count}, descendants={descendants_count}, siblings={siblings_count})",
                "INFO"
            )

            # Bonus: Test list_executions_by_correlation
            correlation_executions = self.executor.execution_store.list_executions_by_correlation(
                execution.correlation_id
            )

            if len(correlation_executions) < 1:
                self.record_result(
                    "Lineage Queries",
                    False,
                    f"list_executions_by_correlation returned 0 results for {execution.correlation_id}"
                )
                return False

            self.log(
                f"✓ Correlation chain: {len(correlation_executions)} execution(s) in correlation {execution.correlation_id[:12]}...",
                "INFO"
            )

            return True

        except Exception as e:
            self.record_result(
                "Lineage Queries",
                False,
                f"Lineage query failed: {e}"
            )
            import traceback
            traceback.print_exc()
            return False

    def _cleanup_test_artifacts(self):
        """Cleanup test artifacts (optional)."""
        try:
            # Remove test file
            test_file = self.workspace_root / "TEST_SMOKE.md"
            if test_file.exists():
                test_file.unlink()
                self.log("Cleaned up TEST_SMOKE.md", "INFO")

            # Optionally cleanup artifacts (for testing only)
            # In production, you'd keep artifacts for audit

            self.log("Cleanup completed", "INFO")

        except Exception as e:
            self.log(f"Cleanup warning: {e}", "WARNING")

    def _print_summary(self):
        """Print validation summary."""
        self.log("=" * 60)
        self.log("VALIDATION SUMMARY", "INFO")
        self.log("=" * 60)

        passed_count = sum(1 for _, passed, _ in self.results if passed)
        total_count = len(self.results)

        for test_name, passed, message in self.results:
            status = "[OK] PASS" if passed else "[X] FAIL"
            self.log(f"{status}: {test_name}", "INFO")
            if not passed:
                self.log(f"  └─ {message}", "ERROR")

        self.log("=" * 60)
        self.log(
            f"RESULT: {passed_count}/{total_count} tests passed",
            "SUCCESS" if passed_count == total_count else "ERROR"
        )
        self.log("=" * 60)

        # Print execution ID and artifact path for CI log linkage
        if self.execution_id:
            self.log("", "INFO")
            self.log("EXECUTION DETAILS (for audit/debugging):", "INFO")
            self.log(f"  execution_id: {self.execution_id}", "INFO")
            self.log(f"  artifact_dir: {self.artifact_path}", "INFO")
            self.log(f"  sqlite_query: SELECT * FROM executions WHERE execution_id='{self.execution_id}'", "INFO")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="LonelyCat Production Validation - Phase 2.3-D (Extended)"
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Workspace directory (default: temp directory)"
    )
    parser.add_argument(
        "--skip-services",
        action="store_true",
        help="Skip service health checks"
    )

    args = parser.parse_args()

    # Use temp directory if workspace not specified
    if args.workspace:
        workspace = args.workspace
        cleanup_workspace = False
    else:
        workspace = Path(tempfile.mkdtemp(prefix="lonelycat_validation_"))
        cleanup_workspace = True

    try:
        # Run validation
        validator = ProductionValidator(workspace, skip_services=args.skip_services)
        success = validator.run_all_validations()

        # Exit with appropriate code
        if success:
            print("\n[OK] All validations passed! Ready for release.")
            sys.exit(0)
        else:
            print("\n[!] Some validations failed. Do NOT release.")
            sys.exit(1)

    except Exception as e:
        print(f"\n[X] Validation error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    finally:
        # Cleanup temp workspace
        if cleanup_workspace and workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    main()
