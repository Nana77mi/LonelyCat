"""
Tests for Phase 2.2-C: Real Service Health Checks

Validates:
- HTTP GET health checks with error codes
- Process alive checks (by name and PID)
- Command execution checks
- TCP port checks
- Error code normalization
- Structured health check specs
"""

import pytest
import tempfile
import subprocess
import time
from pathlib import Path

# Import health checker
from executor import HealthChecker


@pytest.fixture
def temp_workspace():
    """Create temporary workspace for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def health_checker(temp_workspace):
    """Create HealthChecker instance."""
    return HealthChecker(temp_workspace)


# ========== Test 1: HTTP GET Check (Success) ==========

def test_http_get_check_success(health_checker):
    """Test HTTP GET check passes when status matches."""
    # Mock HTTP server would be needed for real test
    # For now, test against public endpoint or skip if no httpx
    try:
        import httpx
    except ImportError:
        pytest.skip("httpx not installed")

    # Test against httpbin or similar
    check_spec = {
        "name": "httpbin_test",
        "type": "http_get",
        "config": {
            "url": "https://httpbin.org/status/200",
            "expect_status": 200
        },
        "timeout": 10
    }

    result = health_checker.run_health_checks([check_spec], None)

    assert result["passed"] is True
    assert "httpbin_test" in result["details"]
    print(f"[OK] HTTP GET check passed: {result['details']['httpbin_test']}")


# ========== Test 2: HTTP GET Check (Status Mismatch) ==========

def test_http_get_check_status_mismatch(health_checker):
    """Test HTTP GET check fails with error code when status doesn't match."""
    try:
        import httpx
    except ImportError:
        pytest.skip("httpx not installed")

    # Expect 200 but get 404
    check_spec = {
        "name": "http_404_test",
        "type": "http_get",
        "config": {
            "url": "https://httpbin.org/status/404",
            "expect_status": 200
        },
        "timeout": 10
    }

    result = health_checker.run_health_checks([check_spec], None)

    assert result["passed"] is False
    check_result = result["details"]["http_404_test"]
    assert check_result["error_code"] == "HEALTH_HTTP_404"
    print(f"[OK] HTTP 404 detected with error code: {check_result['error_code']}")


# ========== Test 3: HTTP Timeout ==========

def test_http_timeout(health_checker):
    """Test HTTP check times out with HEALTH_TIMEOUT error code."""
    try:
        import httpx
    except ImportError:
        pytest.skip("httpx not installed")

    # Use a non-routable IP to trigger timeout
    check_spec = {
        "name": "timeout_test",
        "type": "http_get",
        "config": {
            "url": "http://10.255.255.1:80/health",  # Non-routable
            "expect_status": 200
        },
        "timeout": 1  # Short timeout
    }

    result = health_checker.run_health_checks([check_spec], None)

    assert result["passed"] is False
    check_result = result["details"]["timeout_test"]
    assert check_result["error_code"] in ["HEALTH_TIMEOUT", "HEALTH_CONNECTION_REFUSED"]
    print(f"[OK] Timeout detected with error code: {check_result['error_code']}")


# ========== Test 4: Process Alive Check (Self) ==========

def test_process_alive_check_self(health_checker):
    """Test process alive check passes for current process."""
    import os
    current_pid = os.getpid()

    check_spec = {
        "name": "self_process",
        "type": "process_alive",
        "config": {
            "pid": current_pid
        }
    }

    result = health_checker.run_health_checks([check_spec], None)

    assert result["passed"] is True
    print(f"[OK] Current process PID {current_pid} detected as alive")


# ========== Test 5: Process Alive Check (Dead Process) ==========

def test_process_alive_check_dead(health_checker):
    """Test process alive check fails for non-existent PID."""
    # Use a very high PID that's unlikely to exist
    fake_pid = 999999

    check_spec = {
        "name": "dead_process",
        "type": "process_alive",
        "config": {
            "pid": fake_pid
        }
    }

    result = health_checker.run_health_checks([check_spec], None)

    assert result["passed"] is False
    check_result = result["details"]["dead_process"]
    assert check_result["error_code"] == "HEALTH_PROCESS_DEAD"
    print(f"[OK] Dead process detected with error code: {check_result['error_code']}")


# ========== Test 6: Process Alive by Name (Python) ==========

def test_process_alive_by_name_python(health_checker):
    """Test process alive check by name for Python process."""
    import platform

    # Python process should be running (this test itself)
    process_name = "python.exe" if platform.system() == "Windows" else "python"

    check_spec = {
        "name": "python_process",
        "type": "process_alive",
        "config": {
            "process_name": process_name
        }
    }

    result = health_checker.run_health_checks([check_spec], None)

    assert result["passed"] is True
    print(f"[OK] Python process '{process_name}' detected as running")


# ========== Test 7: Command Check (Success) ==========

def test_command_check_success(health_checker):
    """Test command check passes when command succeeds."""
    import platform

    # Use a command that always succeeds
    command = "exit 0" if platform.system() == "Windows" else "true"

    check_spec = {
        "name": "success_command",
        "type": "command",
        "config": {
            "command": command,
            "expect_exit_code": 0
        }
    }

    result = health_checker.run_health_checks([check_spec], None)

    assert result["passed"] is True
    print(f"[OK] Command '{command}' executed successfully")


# ========== Test 8: Command Check (Failure) ==========

def test_command_check_failure(health_checker):
    """Test command check fails with HEALTH_COMMAND_FAILED error code."""
    import platform

    # Use a command that always fails
    command = "exit 1" if platform.system() == "Windows" else "false"

    check_spec = {
        "name": "failed_command",
        "type": "command",
        "config": {
            "command": command,
            "expect_exit_code": 0
        }
    }

    result = health_checker.run_health_checks([check_spec], None)

    assert result["passed"] is False
    check_result = result["details"]["failed_command"]
    assert check_result["error_code"] == "HEALTH_COMMAND_FAILED"
    assert check_result["details"]["exit_code"] == 1
    print(f"[OK] Failed command detected with error code: {check_result['error_code']}")


# ========== Test 9: TCP Port Check (Open) ==========

def test_tcp_port_check_open(health_checker):
    """Test TCP port check passes for open port."""
    # Start a simple TCP server
    import socket
    import threading

    def start_server(port, stop_event):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("localhost", port))
        sock.listen(1)
        sock.settimeout(1)

        while not stop_event.is_set():
            try:
                conn, addr = sock.accept()
                conn.close()
            except socket.timeout:
                continue

        sock.close()

    port = 18765  # Random high port
    stop_event = threading.Event()

    server_thread = threading.Thread(target=start_server, args=(port, stop_event))
    server_thread.start()

    time.sleep(0.5)  # Wait for server to start

    try:
        check_spec = {
            "name": "tcp_port_test",
            "type": "tcp_port",
            "config": {
                "host": "localhost",
                "port": port
            }
        }

        result = health_checker.run_health_checks([check_spec], None)

        assert result["passed"] is True
        print(f"[OK] TCP port {port} detected as open")

    finally:
        stop_event.set()
        server_thread.join(timeout=2)


# ========== Test 10: TCP Port Check (Closed) ==========

def test_tcp_port_check_closed(health_checker):
    """Test TCP port check fails with HEALTH_PORT_CLOSED error code."""
    # Use a port that's very unlikely to be open
    port = 19876

    check_spec = {
        "name": "closed_port_test",
        "type": "tcp_port",
        "config": {
            "host": "localhost",
            "port": port
        }
    }

    result = health_checker.run_health_checks([check_spec], None)

    assert result["passed"] is False
    check_result = result["details"]["closed_port_test"]
    assert check_result["error_code"] == "HEALTH_PORT_CLOSED"
    print(f"[OK] Closed port detected with error code: {check_result['error_code']}")


# ========== Test 11: Backward Compatibility (String Checks) ==========

def test_backward_compatibility_string_checks(health_checker):
    """Test backward compatibility with string-based health checks."""
    # String format: "GET /health returns 200"
    string_checks = [
        "GET http://httpbin.org/status/200 returns 200"
    ]

    try:
        import httpx
    except ImportError:
        pytest.skip("httpx not installed")

    result = health_checker.run_health_checks(string_checks, None)

    # Should parse and run successfully
    assert result["passed"] is True
    print(f"[OK] String-based health check parsed and executed")


# ========== Test 12: Critical vs Non-Critical Checks ==========

def test_critical_vs_non_critical(health_checker):
    """Test that non-critical failures don't fail overall check."""
    checks = [
        {
            "name": "critical_check",
            "type": "command",
            "config": {"command": "true" if __import__('platform').system() != "Windows" else "exit 0"},
            "critical": True
        },
        {
            "name": "non_critical_check",
            "type": "command",
            "config": {"command": "false" if __import__('platform').system() != "Windows" else "exit 1"},
            "critical": False  # Non-critical
        }
    ]

    result = health_checker.run_health_checks(checks, None)

    # Overall should fail (at least one check failed)
    assert result["passed"] is False

    # But critical_failed should be False (only non-critical check failed)
    assert result["critical_failed"] is False

    print(f"[OK] Non-critical failure handled correctly")


# ========== Test 13: Multiple Check Types ==========

def test_multiple_check_types(health_checker):
    """Test running multiple check types together."""
    import os

    checks = [
        {
            "name": "command_test",
            "type": "command",
            "config": {"command": "echo ok"}
        },
        {
            "name": "process_test",
            "type": "process_alive",
            "config": {"pid": os.getpid()}
        }
    ]

    result = health_checker.run_health_checks(checks, None)

    assert result["passed"] is True
    assert len(result["details"]) == 2
    assert "command_test" in result["details"]
    assert "process_test" in result["details"]

    print(f"[OK] Multiple check types executed successfully")


# ========== Run All Tests ==========

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
