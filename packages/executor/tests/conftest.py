"""
Pytest configuration for executor tests.

Detects and reports test capabilities to avoid confusion between
"skipped tests" and "missing capabilities".
"""

import pytest


def pytest_configure(config):
    """
    Detect and report test capabilities at the start of the test session.

    This makes it clear what features are available vs unavailable,
    preventing "skipped tests" from being misread as "incomplete testing".
    """
    # Detect HTTP health check capability
    try:
        import httpx
        has_httpx = True
    except ImportError:
        has_httpx = False

    # Print capability flags
    print("\n" + "=" * 60)
    print("TEST CAPABILITIES")
    print("=" * 60)
    print(f"capability.http_health_checks = {str(has_httpx).lower()}")
    print(f"capability.process_checks      = true")
    print(f"capability.command_checks      = true")
    print(f"capability.tcp_port_checks     = true")
    print("=" * 60)

    if not has_httpx:
        print("\nNOTE: HTTP health check tests will be skipped (httpx not installed)")
        print("      Install httpx to enable: pip install httpx")
        print("=" * 60)

    print()


@pytest.fixture(scope="session")
def capabilities():
    """
    Provide test capabilities as a fixture.

    Returns:
        dict: Capability flags indicating what features are available
    """
    try:
        import httpx
        has_httpx = True
    except ImportError:
        has_httpx = False

    return {
        "http_health_checks": has_httpx,
        "process_checks": True,
        "command_checks": True,
        "tcp_port_checks": True
    }
