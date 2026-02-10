"""
Case-based Repair MVP - Phase 2.4-E

Given a failed execution, find similar successful executions and produce
a RepairProposal (suggested plan/changeset references, pre-check).
Output: repair.json in execution artifact dir; consumed by Planner → WriteGate → Executor.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, asdict


@dataclass
class RepairProposal:
    """
    Repair suggestion based on similar successful executions.

    - evidence_execution_ids: successful execution(s) used as reference
    - suggested_plan_id: plan_id from best similar success (optional)
    - suggested_changeset_id: changeset_id from best similar success (optional)
    - summary: human-readable suggestion
    - pre_check: optional command or check to run before applying
    """
    evidence_execution_ids: List[str]
    suggested_plan_id: Optional[str] = None
    suggested_changeset_id: Optional[str] = None
    summary: str = ""
    pre_check: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepairProposal":
        return cls(
            evidence_execution_ids=data.get("evidence_execution_ids", []),
            suggested_plan_id=data.get("suggested_plan_id"),
            suggested_changeset_id=data.get("suggested_changeset_id"),
            summary=data.get("summary", ""),
            pre_check=data.get("pre_check"),
        )


def load_repair(artifact_path: Path) -> Optional[RepairProposal]:
    """Load repair.json from execution artifact dir. Returns None if missing."""
    repair_file = artifact_path / "repair.json"
    if not repair_file.exists():
        return None
    try:
        data = json.loads(repair_file.read_text(encoding="utf-8"))
        return RepairProposal.from_dict(data)
    except Exception:
        return None


def save_repair(artifact_path: Path, proposal: RepairProposal) -> Path:
    """Write repair.json to execution artifact dir."""
    artifact_path = Path(artifact_path)
    artifact_path.mkdir(parents=True, exist_ok=True)
    repair_file = artifact_path / "repair.json"
    repair_file.write_text(json.dumps(proposal.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return repair_file
