"""
Reflection API - Phase 2.5-C2

GET /reflection/hints - Return current reflection hints (e.g. hints_7d.json).
Used by UI to show Suggestions and false-allow evidence links.
"""

from fastapi import APIRouter, HTTPException
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "packages"))

from executor.reflection_hints import load_hints

router = APIRouter(prefix="/reflection", tags=["reflection"])

REPO_ROOT = Path(__file__).parent.parent.parent.parent
HINTS_PATH = REPO_ROOT / ".lonelycat" / "reflection" / "hints_7d.json"


@router.get("/hints")
async def get_reflection_hints():
    """
    Return current reflection hints (Phase 2.5-C2).
    Reads .lonelycat/reflection/hints_7d.json. Returns empty structure if file missing.
    """
    hints = load_hints(HINTS_PATH)
    if hints is None:
        return {
            "hot_error_steps": [],
            "false_allow_patterns": [],
            "slow_steps": [],
            "suggested_policy": [],
            "evidence_execution_ids": [],
            "window": None,
        }
    return hints.to_dict()
