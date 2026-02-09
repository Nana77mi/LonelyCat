"""
Health Checker - Phase 2.2-C: Real Service Integration

Validates system health after changes with structured health check specs.

Supported Check Types:
- http_get: HTTP GET request with expected status
- process_alive: Check if process is running
- command: Execute command and check exit code
- tcp_port: Check if TCP port is open

Error Codes (归一化):
- HEALTH_HTTP_XXX: HTTP status codes (e.g., HEALTH_HTTP_500, HEALTH_HTTP_404)
- HEALTH_TIMEOUT: Request timeout
- HEALTH_CONNECTION_REFUSED: Connection refused
- HEALTH_PROCESS_DEAD: Process not running
- HEALTH_COMMAND_FAILED: Command returned non-zero
- HEALTH_PORT_CLOSED: TCP port not listening
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import subprocess
import socket
import platform

# Optional: httpx for HTTP checks
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class HealthCheckType(Enum):
    """Health check types."""
    HTTP_GET = "http_get"
    PROCESS_ALIVE = "process_alive"
    COMMAND = "command"
    TCP_PORT = "tcp_port"


@dataclass
class HealthCheckSpec:
    """Structured health check specification."""
    name: str
    type: HealthCheckType
    config: Dict[str, Any]

    # Common fields
    timeout: int = 5  # seconds
    critical: bool = True  # If False, failure is warning only


@dataclass
class HealthCheckResult:
    """Health check result."""
    name: str
    passed: bool
    message: str
    error_code: Optional[str] = None
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.details is None:
            self.details = {}


class HealthChecker:
    """
    Runs health checks on services.

    Phase 2.2-C: Real service integration with structured specs.
    """

    def __init__(self, workspace_root: Path, dry_run: bool = False):
        """
        Initialize health checker.

        Args:
            workspace_root: Root directory
            dry_run: If True, simulate without actual checks
        """
        self.workspace_root = Path(workspace_root).resolve()
        self.dry_run = dry_run

    def run_health_checks(
        self,
        health_checks: List[str] | List[Dict[str, Any]],
        context
    ) -> Dict:
        """
        Run health checks.

        Args:
            health_checks: List of health check specs (string or dict)
            context: ExecutionContext

        Returns:
            dict with:
            - passed: bool
            - message: str
            - details: dict of HealthCheckResult
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

        # Parse health check specs
        specs = self._parse_health_checks(health_checks)

        # Run each check
        results = {}
        all_passed = True
        critical_failed = False

        for spec in specs:
            result = self._run_health_check_spec(spec)
            results[spec.name] = {
                "passed": result.passed,
                "message": result.message,
                "error_code": result.error_code,
                "details": result.details
            }

            if not result.passed:
                all_passed = False
                if spec.critical:
                    critical_failed = True

        return {
            "passed": all_passed,
            "message": "All health checks passed" if all_passed else "Some health checks failed",
            "details": results,
            "critical_failed": critical_failed
        }

    def _parse_health_checks(
        self,
        health_checks: List[str] | List[Dict[str, Any]]
    ) -> List[HealthCheckSpec]:
        """
        Parse health check specs from strings or dicts.

        Args:
            health_checks: List of health check descriptions

        Returns:
            List of HealthCheckSpec
        """
        specs = []

        for i, check in enumerate(health_checks):
            if isinstance(check, dict):
                # Structured spec
                spec = HealthCheckSpec(
                    name=check.get("name", f"check_{i+1}"),
                    type=HealthCheckType(check["type"]),
                    config=check.get("config", {}),
                    timeout=check.get("timeout", 5),
                    critical=check.get("critical", True)
                )
                specs.append(spec)
            else:
                # String spec - parse for backward compatibility
                spec = self._parse_string_check(check, i)
                specs.append(spec)

        return specs

    def _parse_string_check(self, check: str, index: int) -> HealthCheckSpec:
        """
        Parse string health check for backward compatibility.

        Args:
            check: Check string (e.g., "GET /health returns 200")
            index: Check index

        Returns:
            HealthCheckSpec
        """
        check_lower = check.lower()

        # HTTP check
        if "get" in check_lower and "returns" in check_lower:
            import re
            match = re.search(r'GET\s+(\S+)\s+returns\s+(\d+)', check, re.IGNORECASE)
            if match:
                endpoint = match.group(1)
                status = int(match.group(2))

                # Determine base URL
                if endpoint.startswith("http"):
                    url = endpoint
                else:
                    url = f"http://localhost:5173{endpoint}"

                return HealthCheckSpec(
                    name=f"http_{index+1}",
                    type=HealthCheckType.HTTP_GET,
                    config={"url": url, "expect_status": status}
                )

        # Default: command check
        return HealthCheckSpec(
            name=f"check_{index+1}",
            type=HealthCheckType.COMMAND,
            config={"command": check}
        )

    def _run_health_check_spec(self, spec: HealthCheckSpec) -> HealthCheckResult:
        """
        Run a single health check spec.

        Args:
            spec: HealthCheckSpec

        Returns:
            HealthCheckResult
        """
        if spec.type == HealthCheckType.HTTP_GET:
            return self._check_http_get(spec)
        elif spec.type == HealthCheckType.PROCESS_ALIVE:
            return self._check_process_alive(spec)
        elif spec.type == HealthCheckType.COMMAND:
            return self._check_command(spec)
        elif spec.type == HealthCheckType.TCP_PORT:
            return self._check_tcp_port(spec)
        else:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message=f"Unknown health check type: {spec.type}",
                error_code="HEALTH_UNKNOWN_TYPE"
            )

    def _check_http_get(self, spec: HealthCheckSpec) -> HealthCheckResult:
        """
        Check HTTP GET endpoint.

        Config:
        - url: URL to check
        - expect_status: Expected HTTP status code (default: 200)
        - headers: Optional headers dict

        Returns:
            HealthCheckResult
        """
        if not HAS_HTTPX:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message="httpx not installed (cannot perform HTTP checks)",
                error_code="HEALTH_DEPENDENCY_MISSING",
                details={"hint": "pip install httpx"}
            )

        url = spec.config["url"]
        expect_status = spec.config.get("expect_status", 200)
        headers = spec.config.get("headers", {})

        try:
            response = httpx.get(url, headers=headers, timeout=spec.timeout, follow_redirects=True)

            passed = response.status_code == expect_status

            if passed:
                return HealthCheckResult(
                    name=spec.name,
                    passed=True,
                    message=f"HTTP {url} returned {response.status_code}",
                    details={"status": response.status_code, "url": url}
                )
            else:
                return HealthCheckResult(
                    name=spec.name,
                    passed=False,
                    message=f"HTTP {url} returned {response.status_code}, expected {expect_status}",
                    error_code=f"HEALTH_HTTP_{response.status_code}",
                    details={
                        "status": response.status_code,
                        "expected": expect_status,
                        "url": url
                    }
                )

        except httpx.TimeoutException:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message=f"HTTP {url} timed out after {spec.timeout}s",
                error_code="HEALTH_TIMEOUT",
                details={"url": url, "timeout": spec.timeout}
            )

        except httpx.ConnectError:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message=f"HTTP {url} connection refused",
                error_code="HEALTH_CONNECTION_REFUSED",
                details={"url": url}
            )

        except Exception as e:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message=f"HTTP {url} check failed: {e}",
                error_code="HEALTH_HTTP_ERROR",
                details={"url": url, "error": str(e)}
            )

    def _check_process_alive(self, spec: HealthCheckSpec) -> HealthCheckResult:
        """
        Check if process is running.

        Config:
        - process_name: Process name to check
        - OR pid: Process ID to check

        Returns:
            HealthCheckResult
        """
        process_name = spec.config.get("process_name")
        pid = spec.config.get("pid")

        if pid:
            # Check specific PID
            alive = self._is_process_alive(pid)
            if alive:
                return HealthCheckResult(
                    name=spec.name,
                    passed=True,
                    message=f"Process PID {pid} is running",
                    details={"pid": pid}
                )
            else:
                return HealthCheckResult(
                    name=spec.name,
                    passed=False,
                    message=f"Process PID {pid} is not running",
                    error_code="HEALTH_PROCESS_DEAD",
                    details={"pid": pid}
                )

        elif process_name:
            # Check by process name
            alive = self._is_process_alive_by_name(process_name)
            if alive:
                return HealthCheckResult(
                    name=spec.name,
                    passed=True,
                    message=f"Process '{process_name}' is running",
                    details={"process_name": process_name}
                )
            else:
                return HealthCheckResult(
                    name=spec.name,
                    passed=False,
                    message=f"Process '{process_name}' is not running",
                    error_code="HEALTH_PROCESS_DEAD",
                    details={"process_name": process_name}
                )

        else:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message="process_alive check requires 'process_name' or 'pid'",
                error_code="HEALTH_INVALID_CONFIG"
            )

    def _check_command(self, spec: HealthCheckSpec) -> HealthCheckResult:
        """
        Execute command and check exit code.

        Config:
        - command: Command to execute
        - expect_exit_code: Expected exit code (default: 0)
        - shell: Use shell (default: True)

        Returns:
            HealthCheckResult
        """
        command = spec.config["command"]
        expect_exit_code = spec.config.get("expect_exit_code", 0)
        use_shell = spec.config.get("shell", True)

        try:
            result = subprocess.run(
                command,
                shell=use_shell,
                capture_output=True,
                timeout=spec.timeout,
                text=True
            )

            passed = result.returncode == expect_exit_code

            if passed:
                return HealthCheckResult(
                    name=spec.name,
                    passed=True,
                    message=f"Command exited with {result.returncode}",
                    details={"command": command, "exit_code": result.returncode}
                )
            else:
                return HealthCheckResult(
                    name=spec.name,
                    passed=False,
                    message=f"Command exited with {result.returncode}, expected {expect_exit_code}",
                    error_code="HEALTH_COMMAND_FAILED",
                    details={
                        "command": command,
                        "exit_code": result.returncode,
                        "expected": expect_exit_code,
                        "stdout": result.stdout[:200] if result.stdout else "",
                        "stderr": result.stderr[:200] if result.stderr else ""
                    }
                )

        except subprocess.TimeoutExpired:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message=f"Command timed out after {spec.timeout}s",
                error_code="HEALTH_TIMEOUT",
                details={"command": command, "timeout": spec.timeout}
            )

        except Exception as e:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message=f"Command failed: {e}",
                error_code="HEALTH_COMMAND_ERROR",
                details={"command": command, "error": str(e)}
            )

    def _check_tcp_port(self, spec: HealthCheckSpec) -> HealthCheckResult:
        """
        Check if TCP port is listening.

        Config:
        - host: Hostname (default: localhost)
        - port: Port number

        Returns:
            HealthCheckResult
        """
        host = spec.config.get("host", "localhost")
        port = spec.config["port"]

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(spec.timeout)

            result = sock.connect_ex((host, port))
            sock.close()

            if result == 0:
                return HealthCheckResult(
                    name=spec.name,
                    passed=True,
                    message=f"TCP port {host}:{port} is listening",
                    details={"host": host, "port": port}
                )
            else:
                return HealthCheckResult(
                    name=spec.name,
                    passed=False,
                    message=f"TCP port {host}:{port} is not listening",
                    error_code="HEALTH_PORT_CLOSED",
                    details={"host": host, "port": port}
                )

        except socket.timeout:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message=f"TCP port {host}:{port} check timed out",
                error_code="HEALTH_TIMEOUT",
                details={"host": host, "port": port, "timeout": spec.timeout}
            )

        except Exception as e:
            return HealthCheckResult(
                name=spec.name,
                passed=False,
                message=f"TCP port check failed: {e}",
                error_code="HEALTH_PORT_ERROR",
                details={"host": host, "port": port, "error": str(e)}
            )

    def _is_process_alive(self, pid: int) -> bool:
        """
        Check if process with PID is alive.

        Args:
            pid: Process ID

        Returns:
            True if alive
        """
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                return str(pid) in result.stdout
            except Exception:
                return False
        else:
            # Unix-like systems
            try:
                import os
                import errno
                os.kill(pid, 0)  # Signal 0 checks if process exists
                return True
            except OSError as e:
                return e.errno != errno.ESRCH  # ESRCH = no such process

    def _is_process_alive_by_name(self, process_name: str) -> bool:
        """
        Check if process with name is running.

        Args:
            process_name: Process name

        Returns:
            True if running
        """
        if platform.system() == "Windows":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {process_name}*", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                return process_name.lower() in result.stdout.lower()
            except Exception:
                return False
        else:
            # Unix-like systems
            try:
                result = subprocess.run(
                    ["pgrep", "-x", process_name],
                    capture_output=True,
                    timeout=2
                )
                return result.returncode == 0
            except Exception:
                return False
