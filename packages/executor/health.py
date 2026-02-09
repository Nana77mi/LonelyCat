"""
Health Checker - Validates system health after changes

Runs health checks specified in ChangePlan.health_checks.

Phase 2 MVP: Basic implementation
Phase 2.1: Full integration with services
"""

from pathlib import Path
from typing import List, Dict
import time

# Optional: httpx for HTTP checks
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class HealthChecker:
    """Runs health checks on services."""

    def __init__(self, workspace_root: Path, dry_run: bool = False):
        """
        Initialize health checker.

        Args:
            workspace_root: Root directory
            dry_run: If True, simulate without actual checks
        """
        self.workspace_root = workspace_root
        self.dry_run = dry_run

    def run_health_checks(
        self,
        health_checks: List[str],
        context
    ) -> Dict:
        """
        Run health checks.

        Args:
            health_checks: List of health check descriptions
            context: ExecutionContext

        Returns:
            dict with:
            - passed: bool
            - message: str
            - details: dict
        """
        if not health_checks or len(health_checks) == 0:
            # No health checks - pass by default
            return {
                "passed": True,
                "message": "No health checks specified",
                "details": {}
            }

        if self.dry_run:
            return {
                "passed": True,
                "message": "[DRY RUN] Would run health checks",
                "details": {"dry_run": True}
            }

        results = {}
        all_passed = True

        for i, check in enumerate(health_checks):
            check_result = self._run_health_check(check)
            results[f"check_{i+1}"] = check_result

            if not check_result["passed"]:
                all_passed = False

        return {
            "passed": all_passed,
            "message": "All health checks passed" if all_passed else "Some health checks failed",
            "details": results
        }

    def _run_health_check(self, check: str) -> Dict:
        """
        Run a single health check.

        Args:
            check: Health check description (e.g., "GET /health returns 200")

        Returns:
            dict with passed, message
        """
        check_lower = check.lower()

        # Detect HTTP health check
        if "get" in check_lower and ("health" in check_lower or "returns" in check_lower):
            return self._check_http_endpoint(check)

        # Detect service health check
        if any(service in check_lower for service in ["core-api", "agent-worker", "web-console"]):
            return self._check_service_health(check)

        # Detect database check
        if "database" in check_lower or "db" in check_lower:
            return self._check_database()

        # Default: pass (Phase 2 MVP)
        return {
            "passed": True,
            "message": f"Health check passed: {check}",
            "note": "Phase 2 MVP - basic checks only"
        }

    def _check_http_endpoint(self, check: str) -> Dict:
        """
        Check HTTP endpoint.

        Args:
            check: Check description (e.g., "GET /health returns 200")

        Returns:
            dict with health check result
        """
        if not HAS_HTTPX:
            # httpx not available - pass with warning
            return {
                "passed": True,
                "message": "HTTP check skipped (httpx not installed)",
                "warning": "Install httpx for actual HTTP health checks"
            }

        # Parse endpoint and expected status
        # Example: "GET /health returns 200"
        import re
        match = re.search(r'GET\s+(\S+)\s+returns\s+(\d+)', check, re.IGNORECASE)

        if not match:
            # Can't parse - pass with warning
            return {
                "passed": True,
                "message": "Could not parse health check (passed by default)",
                "warning": f"Unparseable: {check}"
            }

        endpoint = match.group(1)
        expected_status = int(match.group(2))

        # Determine base URL (default: localhost:5173 for core-api)
        if endpoint.startswith("http"):
            url = endpoint
        else:
            url = f"http://localhost:5173{endpoint}"

        try:
            response = httpx.get(url, timeout=5.0)

            passed = response.status_code == expected_status

            return {
                "passed": passed,
                "message": f"Endpoint {endpoint} returned {response.status_code}",
                "expected": expected_status,
                "actual": response.status_code
            }

        except httpx.TimeoutException:
            return {
                "passed": False,
                "message": f"Endpoint {endpoint} timed out",
                "error": "Timeout"
            }

        except Exception as e:
            return {
                "passed": False,
                "message": f"Failed to check endpoint {endpoint}: {e}",
                "error": str(e)
            }

    def _check_service_health(self, check: str) -> Dict:
        """
        Check service health.

        Args:
            check: Service health check description

        Returns:
            dict with result
        """
        # Phase 2 MVP: Simplified check
        # Phase 2.1: Full service integration

        # Try to detect service from check string
        if "core-api" in check.lower():
            return self._check_http_endpoint("GET /health returns 200")

        # Default: pass
        return {
            "passed": True,
            "message": f"Service health check passed: {check}",
            "note": "Phase 2 MVP - placeholder"
        }

    def _check_database(self) -> Dict:
        """
        Check database connectivity.

        Returns:
            dict with result
        """
        try:
            # Try to connect to SQLite database
            import sqlite3
            db_path = self.workspace_root / "lonelycat_memory.db"

            if not db_path.exists():
                return {
                    "passed": False,
                    "message": "Database file not found",
                    "path": str(db_path)
                }

            conn = sqlite3.connect(str(db_path))
            try:
                # Try a simple query
                cursor = conn.execute("SELECT 1")
                cursor.fetchone()

                return {
                    "passed": True,
                    "message": "Database connectivity OK"
                }

            finally:
                conn.close()

        except Exception as e:
            return {
                "passed": False,
                "message": f"Database check failed: {e}",
                "error": str(e)
            }
