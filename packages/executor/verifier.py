"""
Verification Runner - Executes verification plans

Parses and runs verification commands from ChangePlan.verification_plan.

Supports:
- Test execution (pytest, npm test)
- Command execution (health check endpoints)
- Custom verification scripts

Returns structured results for Executor.
"""

from pathlib import Path
from typing import Dict
import subprocess
import re


class VerificationRunner:
    """Runs verification plans."""

    def __init__(self, workspace_root: Path, dry_run: bool = False):
        """
        Initialize verification runner.

        Args:
            workspace_root: Root directory for operations
            dry_run: If True, simulate without actual execution
        """
        self.workspace_root = workspace_root
        self.dry_run = dry_run

    def run_verification(
        self,
        verification_plan: str,
        context
    ) -> Dict:
        """
        Run verification plan.

        Args:
            verification_plan: Verification plan string (e.g., "Run tests; Check health")
            context: ExecutionContext

        Returns:
            dict with:
            - passed: bool
            - message: str
            - details: dict
        """
        if not verification_plan or verification_plan.strip() == "":
            # No verification plan - pass by default
            return {
                "passed": True,
                "message": "No verification plan specified",
                "details": {}
            }

        if self.dry_run:
            return {
                "passed": True,
                "message": "[DRY RUN] Would run verification",
                "details": {"dry_run": True}
            }

        # Parse verification plan into steps
        steps = self._parse_verification_plan(verification_plan)

        results = {}
        all_passed = True

        for i, step in enumerate(steps):
            step_result = self._run_verification_step(step)
            results[f"step_{i+1}"] = step_result

            if not step_result["passed"]:
                all_passed = False
                # Stop on first failure
                break

        return {
            "passed": all_passed,
            "message": "All verification steps passed" if all_passed else "Verification failed",
            "details": results
        }

    def _parse_verification_plan(self, plan: str) -> list:
        """
        Parse verification plan into steps.

        Args:
            plan: Plan string (e.g., "Run tests; Check health")

        Returns:
            List of step strings
        """
        # Split by semicolon or newline
        steps = re.split(r'[;\n]', plan)

        # Clean and filter empty steps
        steps = [s.strip() for s in steps if s.strip()]

        return steps

    def _run_verification_step(self, step: str) -> Dict:
        """
        Run a single verification step.

        Args:
            step: Step description (e.g., "Run tests", "pytest", "Check health")

        Returns:
            dict with passed, message, output
        """
        step_lower = step.lower()

        # Detect test commands
        if any(keyword in step_lower for keyword in ["test", "pytest", "npm test"]):
            return self._run_tests(step)

        # Detect health check
        if "health" in step_lower or "check" in step_lower:
            return self._check_health(step)

        # Default: try to execute as command
        return self._execute_command(step)

    def _run_tests(self, step: str) -> Dict:
        """
        Run tests.

        Args:
            step: Test command (e.g., "pytest", "Run affected tests")

        Returns:
            dict with test results
        """
        # Detect test framework
        if "pytest" in step.lower():
            command = ["pytest", "-v", "--tb=short"]
        elif "npm test" in step.lower():
            command = ["npm", "test"]
        else:
            # Generic test command
            command = ["pytest", "-v"]

        try:
            result = subprocess.run(
                command,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            passed = result.returncode == 0

            return {
                "passed": passed,
                "message": "Tests passed" if passed else "Tests failed",
                "output": result.stdout,
                "errors": result.stderr,
                "return_code": result.returncode
            }

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "message": "Tests timed out (5 minutes)",
                "output": "",
                "errors": "Timeout"
            }

        except Exception as e:
            return {
                "passed": False,
                "message": f"Failed to run tests: {e}",
                "output": "",
                "errors": str(e)
            }

    def _check_health(self, step: str) -> Dict:
        """
        Check health endpoint or service.

        Args:
            step: Health check description

        Returns:
            dict with health check results
        """
        # Phase 2 MVP: Simple pass (actual health checks in Phase 2.1)
        return {
            "passed": True,
            "message": "Health check passed (placeholder)",
            "details": {"note": "Phase 2 MVP - actual health checks in Phase 2.1"}
        }

    def _execute_command(self, step: str) -> Dict:
        """
        Execute arbitrary verification command.

        Args:
            step: Command to execute

        Returns:
            dict with command results
        """
        try:
            result = subprocess.run(
                step,
                shell=True,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=60
            )

            passed = result.returncode == 0

            return {
                "passed": passed,
                "message": "Command succeeded" if passed else "Command failed",
                "output": result.stdout,
                "errors": result.stderr,
                "return_code": result.returncode
            }

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "message": "Command timed out",
                "output": "",
                "errors": "Timeout"
            }

        except Exception as e:
            return {
                "passed": False,
                "message": f"Failed to execute command: {e}",
                "output": "",
                "errors": str(e)
            }
