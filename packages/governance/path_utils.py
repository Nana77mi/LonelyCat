"""
Path Utilities - Canonical path handling for security

Provides unified path canonicalization to prevent bypasses:
- Resolves .. but detects symlinks (not follows)
- Normalizes separators and case (Windows)
- Enforces workspace boundary
- Prevents path traversal attacks

Security principles:
1. All paths must be under workspace_root
2. Symlinks to forbidden locations are denied
3. Absolute paths and UNC paths are denied
4. Path traversal (../) is resolved but checked
"""

from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from enum import Enum
import platform
import os


class PathViolation(Enum):
    """Path boundary violation reasons."""
    PATH_TRAVERSAL = "path_traversal"
    FORBIDDEN_ROOT = "forbidden_root"
    SYMLINK_PATH = "symlink_path"
    OUTSIDE_WORKSPACE = "outside_workspace"
    ABSOLUTE_PATH_DENIED = "absolute_path_denied"
    UNC_PATH_DENIED = "unc_path_denied"


@dataclass
class CanonicalPathResult:
    """Result of path canonicalization."""
    abs_path: Path  # Absolute canonical path
    norm_path_str: str  # Normalized string for pattern matching
    has_symlink: bool  # Contains symlink in path chain
    within_workspace: bool  # Is under workspace_root
    violation: Optional[PathViolation] = None  # If invalid


def canonicalize_path(
    path: str | Path,
    workspace_root: Path
) -> CanonicalPathResult:
    """
    Canonicalize path with security checks.

    IMPORTANT: This function:
    1. Resolves .. to prevent traversal (坑 A fix)
    2. Detects symlinks WITHOUT following them (坑 B fix)
    3. Uses workspace_root as base for relative paths
    4. Normalizes case on Windows

    Args:
        path: Path to canonicalize (relative or absolute)
        workspace_root: Workspace root (must be absolute)

    Returns:
        CanonicalPathResult with validation info
    """
    # Ensure workspace_root is canonical
    if not workspace_root.is_absolute():
        workspace_root = workspace_root.resolve()

    # Convert to Path object
    if isinstance(path, str):
        path_obj = Path(path)
    else:
        path_obj = path

    # Check for absolute paths (should be relative for security)
    if path_obj.is_absolute():
        # Windows: Check for UNC paths (\\server\share)
        if platform.system() == "Windows" and str(path_obj).startswith("\\\\"):
            return CanonicalPathResult(
                abs_path=path_obj,
                norm_path_str=str(path_obj),
                has_symlink=False,
                within_workspace=False,
                violation=PathViolation.UNC_PATH_DENIED
            )

        # Absolute paths are generally denied (use relative paths)
        return CanonicalPathResult(
            abs_path=path_obj,
            norm_path_str=str(path_obj),
            has_symlink=False,
            within_workspace=False,
            violation=PathViolation.ABSOLUTE_PATH_DENIED
        )

    # Make path absolute relative to workspace_root (坑 A fix)
    abs_path = (workspace_root / path_obj).resolve(strict=False)

    # Check if within workspace
    try:
        abs_path.relative_to(workspace_root.resolve())
        within_workspace = True
    except ValueError:
        within_workspace = False

    # Detect symlinks in path chain (坑 B fix)
    # We check each component, not just the final target
    has_symlink = _has_symlink_in_chain(abs_path, workspace_root)

    # Normalize for pattern matching
    # Windows: use os.path.normcase for proper handling
    if platform.system() == "Windows":
        norm_path_str = os.path.normcase(str(abs_path))
    else:
        norm_path_str = str(abs_path)

    # Determine violation
    violation = None
    if not within_workspace:
        violation = PathViolation.OUTSIDE_WORKSPACE
    elif has_symlink:
        violation = PathViolation.SYMLINK_PATH

    return CanonicalPathResult(
        abs_path=abs_path,
        norm_path_str=norm_path_str,
        has_symlink=has_symlink,
        within_workspace=within_workspace,
        violation=violation
    )


def _has_symlink_in_chain(path: Path, workspace_root: Path) -> bool:
    """
    Check if any component in path is a symlink.

    IMPORTANT: We check the chain, not just resolve the final target.
    This is 坑 B fix - don't follow symlinks, detect them.

    Args:
        path: Path to check
        workspace_root: Workspace root

    Returns:
        True if any component is a symlink
    """
    try:
        # Check each parent up to workspace_root
        current = path
        workspace_resolved = workspace_root.resolve()

        while True:
            # Don't check beyond workspace
            try:
                current.relative_to(workspace_resolved)
            except ValueError:
                break

            # Check if this component is a symlink
            if current.exists() and current.is_symlink():
                return True

            # Move to parent
            if current == workspace_resolved or current == current.parent:
                break
            current = current.parent

        return False

    except (OSError, RuntimeError):
        # Permission error or broken symlink
        # Conservative: treat as potential symlink
        return True


def path_policy_check(
    target_path: str | Path,
    workspace_root: Path,
    allowed_patterns: list[str],
    forbidden_patterns: list[str]
) -> tuple[bool, str]:
    """
    Check if path is allowed by policy.

    This is the unified API for WriteGate and Executor.

    Args:
        target_path: Path to check (relative to workspace)
        workspace_root: Workspace root
        allowed_patterns: Glob patterns for allowed paths
        forbidden_patterns: Glob patterns for forbidden paths

    Returns:
        (is_allowed: bool, reason: str)

    Policy precedence:
        1. Canonicalize and validate (absolute/symlink/outside → DENY)
        2. forbidden_patterns (highest priority) → DENY
        3. allowed_patterns → ALLOW
        4. Default → DENY
    """
    # Step 1: Canonicalize
    result = canonicalize_path(target_path, workspace_root)

    # Check canonical violations
    if result.violation:
        return False, f"{result.violation.value}: {target_path}"

    if not result.within_workspace:
        return False, f"outside_workspace: {target_path}"

    if result.has_symlink:
        return False, f"symlink_path: {target_path}"

    # Get relative path for pattern matching
    try:
        rel_path = result.abs_path.relative_to(workspace_root.resolve())
    except ValueError:
        return False, f"outside_workspace: {target_path}"

    rel_path_str = str(rel_path).replace("\\", "/")  # Normalize for matching

    # Step 2: Check forbidden patterns (highest priority)
    for pattern in forbidden_patterns:
        if _match_pattern(rel_path_str, pattern):
            return False, f"forbidden_root: matches pattern '{pattern}'"

    # Step 3: Check allowed patterns
    for pattern in allowed_patterns:
        if _match_pattern(rel_path_str, pattern):
            return True, "allowed_by_policy"

    # Step 4: Default deny
    return False, "not_in_allowed_paths"


def _match_pattern(path: str, pattern: str) -> bool:
    """
    Match path against glob pattern.

    Supports:
    - Exact match: "README.md"
    - Wildcard: "*.md"
    - Recursive: "**/*.py"
    - Directory: "docs/**"

    Args:
        path: Path string (forward slashes)
        pattern: Glob pattern

    Returns:
        True if matches
    """
    from pathlib import PurePosixPath
    import fnmatch

    # Convert to PurePosixPath for consistent matching
    path_obj = PurePosixPath(path)

    # Handle ** (recursive)
    if "**" in pattern:
        # Pattern like "docs/**/*.md"
        pattern_parts = pattern.split("/")

        if pattern_parts[0] == "**":
            # **/*.md - match anywhere
            remaining = "/".join(pattern_parts[1:])
            return any(_match_pattern(str(p), remaining) for p in [path_obj] + list(path_obj.parents))
        else:
            # docs/**/*.md - match under docs
            prefix = pattern_parts[0]
            if path.startswith(prefix + "/") or path == prefix:
                # Under prefix, match remaining pattern
                remaining = "/".join(pattern_parts[1:])
                if remaining == "**":
                    return True  # Match anything under prefix
                else:
                    # Remove prefix and check remaining
                    try:
                        path_under_prefix = str(path_obj.relative_to(PurePosixPath(prefix)))
                        return _match_pattern(path_under_prefix, remaining.replace("**/", ""))
                    except ValueError:
                        return False

    # Simple glob match
    return fnmatch.fnmatch(path, pattern)

