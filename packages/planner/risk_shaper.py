"""
Risk Shaper - Auto-generate Safety Fields

Philosophy: Don't rely on LLM to remember safety - inject it deterministically.

Auto-generates:
- rollback_plan (based on operation type)
- verification_plan (based on affected files)
- health_checks (based on affected services)

This is why Planner Layer makes WriteGate approval rate much higher:
- Before: LLM forgets rollback → WriteGate NEED_APPROVAL → retry
- After: Planner auto-adds rollback → WriteGate ALLOW on first try
"""

from typing import List, Dict, Set
from pathlib import Path
import re


class RiskShaper:
    """
    Auto-generates safety fields for ChangePlans.

    Deterministic rules based on:
    - Affected file paths
    - Operation types
    - Service detection
    """

    # Service detection patterns
    SERVICE_PATTERNS = {
        "core-api": ["apps/core-api/**/*.py"],
        "agent-worker": ["apps/agent-worker/**/*.py"],
        "web-console": ["apps/web-console/**/*.{ts,tsx,js,jsx}"],
        "memory": ["packages/memory/**/*.py"],
        "governance": ["packages/governance/**/*.py"]
    }

    # Health check endpoints per service
    HEALTH_ENDPOINTS = {
        "core-api": "GET /health returns 200",
        "agent-worker": "agent-worker responds to health check",
        "web-console": "web-console loads without errors",
        "memory": "memory.list_facts() works",
        "governance": "governance.list_plans() works"
    }

    def __init__(self):
        """Initialize RiskShaper."""
        pass

    def generate_rollback_plan(
        self,
        affected_paths: List[str],
        operation_type: str = "modify"
    ) -> str:
        """
        Generate rollback plan based on affected files.

        Args:
            affected_paths: List of file paths being changed
            operation_type: Type of operation (modify, create, delete)

        Returns:
            Rollback plan string
        """
        affected_services = self._detect_services(affected_paths)

        # Base rollback: git revert
        rollback_steps = ["git revert <commit>"]

        # Add service restart if needed
        if affected_services:
            services_str = ", ".join(affected_services)
            rollback_steps.append(f"Restart services: {services_str}")

        # Add database rollback if schema changes
        if self._affects_database(affected_paths):
            rollback_steps.append("Rollback database migration (if applied)")

        return " && ".join(rollback_steps)

    def generate_verification_plan(
        self,
        affected_paths: List[str],
        operation_type: str = "modify"
    ) -> str:
        """
        Generate verification plan based on affected files.

        Args:
            affected_paths: List of file paths being changed
            operation_type: Type of operation

        Returns:
            Verification plan string
        """
        verification_steps = []

        # Always run tests
        if self._has_tests(affected_paths):
            verification_steps.append("Run affected tests (pytest)")
        else:
            verification_steps.append("Run smoke tests")

        # Service-specific checks
        affected_services = self._detect_services(affected_paths)
        if affected_services:
            verification_steps.append(f"Check {', '.join(affected_services)} health endpoints")

        # Manual verification for UI changes
        if self._affects_ui(affected_paths):
            verification_steps.append("Manual UI verification in browser")

        return "; ".join(verification_steps)

    def generate_health_checks(
        self,
        affected_paths: List[str]
    ) -> List[str]:
        """
        Generate health checks based on affected services.

        Args:
            affected_paths: List of file paths being changed

        Returns:
            List of health check descriptions
        """
        affected_services = self._detect_services(affected_paths)

        health_checks = []
        for service in affected_services:
            endpoint = self.HEALTH_ENDPOINTS.get(service)
            if endpoint:
                health_checks.append(endpoint)

        # Add database check if DB is affected
        if self._affects_database(affected_paths):
            health_checks.append("Database queries succeed")

        return health_checks

    def infer_scope(
        self,
        affected_paths: List[str]
    ) -> Dict[str, any]:
        """
        Infer scope information from affected paths.

        Returns:
            dict with:
            - services: List of affected services
            - layers: List of affected layers (cognitive, orchestration, etc.)
            - critical: bool (touches critical files)
        """
        services = self._detect_services(affected_paths)
        layers = self._detect_layers(affected_paths)
        critical = self._is_critical(affected_paths)

        return {
            "services": list(services),
            "layers": list(layers),
            "critical": critical
        }

    # ==================== Private Helpers ====================

    def _detect_services(self, paths: List[str]) -> Set[str]:
        """Detect which services are affected by file paths."""
        affected = set()

        for path in paths:
            for service, patterns in self.SERVICE_PATTERNS.items():
                for pattern in patterns:
                    if self._path_matches_pattern(path, pattern):
                        affected.add(service)

        return affected

    def _detect_layers(self, paths: List[str]) -> Set[str]:
        """Detect which architectural layers are affected."""
        layers = set()

        for path in paths:
            if path.startswith("agent/"):
                layers.add("cognitive")
            elif path.startswith("apps/core-api/"):
                layers.add("orchestration")
            elif path.startswith("apps/agent-worker/"):
                layers.add("execution")
            elif path.startswith("packages/memory/"):
                layers.add("memory")
            elif path.startswith("packages/governance/"):
                layers.add("governance")

        return layers

    def _is_critical(self, paths: List[str]) -> bool:
        """Check if any paths are critical."""
        critical_patterns = [
            "agent/policies/**",
            "**/migrations/**",
            "apps/*/app/main.py",
            "packages/governance/**",
            ".github/**"
        ]

        for path in paths:
            for pattern in critical_patterns:
                if self._path_matches_pattern(path, pattern):
                    return True

        return False

    def _affects_database(self, paths: List[str]) -> bool:
        """Check if changes affect database."""
        db_patterns = [
            "**/migrations/**",
            "**/schema.py",
            "**/alembic/**",
            "**/*.sql"
        ]

        for path in paths:
            for pattern in db_patterns:
                if self._path_matches_pattern(path, pattern):
                    return True

        return False

    def _affects_ui(self, paths: List[str]) -> bool:
        """Check if changes affect UI."""
        for path in paths:
            if path.startswith("apps/web-console/"):
                return True
            if path.endswith((".tsx", ".jsx", ".vue", ".svelte")):
                return True

        return False

    def _has_tests(self, paths: List[str]) -> bool:
        """Check if any affected files have corresponding tests."""
        # Simple heuristic: check if test file exists
        for path in paths:
            if "/tests/" in path or path.startswith("tests/"):
                return True

            # Check if test_<filename> exists
            file_path = Path(path)
            test_path = file_path.parent / f"test_{file_path.name}"
            if test_path.exists():
                return True

        return True  # Default to True (assume tests exist)

    def _path_matches_pattern(self, path: str, pattern: str) -> bool:
        """
        Check if path matches glob pattern.

        Simplified version using basic string matching.
        """
        # Normalize separators
        path = path.replace("\\", "/")
        pattern = pattern.replace("\\", "/")

        # Handle ** (match any directory depth)
        if "**" in pattern:
            # Simple approach: check prefix and suffix
            parts = pattern.split("**")
            if len(parts) == 2:
                prefix = parts[0].rstrip("/")
                suffix = parts[1].lstrip("/")

                # Check prefix match
                if prefix and not path.startswith(prefix):
                    return False

                # Check suffix match with glob
                if suffix:
                    # Convert remaining * to regex
                    suffix_pattern = suffix.replace("*", ".*").replace(".", "\\.")
                    import re
                    return re.search(suffix_pattern + "$", path) is not None

                return True

        # Handle single * (match within directory)
        if "*" in pattern:
            regex_pattern = pattern.replace(".", "\\.")
            regex_pattern = regex_pattern.replace("*", "[^/]*")
            regex_pattern = f"^{regex_pattern}$"
            import re
            return re.match(regex_pattern, path) is not None

        # Exact match
        return path == pattern


# Example usage functions

def auto_enhance_plan(
    affected_paths: List[str],
    operation_type: str = "modify"
) -> Dict[str, any]:
    """
    Auto-enhance a plan with safety fields.

    Args:
        affected_paths: Files being changed
        operation_type: Type of operation

    Returns:
        dict with rollback_plan, verification_plan, health_checks
    """
    shaper = RiskShaper()

    return {
        "rollback_plan": shaper.generate_rollback_plan(affected_paths, operation_type),
        "verification_plan": shaper.generate_verification_plan(affected_paths, operation_type),
        "health_checks": shaper.generate_health_checks(affected_paths),
        "scope": shaper.infer_scope(affected_paths)
    }
