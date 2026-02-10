"""
Suggest repair for a failed execution (Phase 2.4-E).

Finds similar successful executions and writes repair.json to the failed
execution's artifact dir. Does NOT execute the repair.

Usage:
    python scripts/suggest_repair.py <execution_id>
    python scripts/suggest_repair.py --workspace /path exec_abc123
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages"))

from executor.storage import ExecutionStore
from executor.repair import RepairProposal, save_repair


def main():
    parser = argparse.ArgumentParser(description="Suggest repair for failed execution (writes repair.json)")
    parser.add_argument("execution_id", help="Failed execution ID")
    parser.add_argument("--workspace", type=Path, default=REPO_ROOT, help="Workspace root")
    parser.add_argument("--limit", type=int, default=10, help="Max similar executions to consider")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    store = ExecutionStore(workspace)

    target = store.get_execution(args.execution_id)
    if not target:
        print(f"Execution {args.execution_id} not found", file=sys.stderr)
        return 1
    if target.status not in ("failed", "rolled_back"):
        print(f"Execution {args.execution_id} is not failed (status={target.status}). Repair suggestion is for failures.", file=sys.stderr)
        return 1

    pairs = store.find_similar_executions(args.execution_id, limit=args.limit, exclude_same_correlation=True)
    # Filter to successful (completed) executions
    successful = [(rec, score) for rec, score in pairs if rec.status == "completed"]
    if not successful:
        print("No similar successful executions found.")
        proposal = RepairProposal(
            evidence_execution_ids=[],
            summary="No similar successful execution found. Consider manual fix or retry with different approach."
        )
    else:
        best_rec, best_score = successful[0]
        artifact_path = Path(best_rec.artifact_path) if best_rec.artifact_path else None
        suggested_plan_id = None
        suggested_changeset_id = None
        if artifact_path and artifact_path.exists():
            plan_file = artifact_path / "plan.json"
            changeset_file = artifact_path / "changeset.json"
            if plan_file.exists():
                try:
                    plan = json.loads(plan_file.read_text(encoding="utf-8"))
                    suggested_plan_id = plan.get("id")
                except Exception:
                    pass
            if changeset_file.exists():
                try:
                    cs = json.loads(changeset_file.read_text(encoding="utf-8"))
                    suggested_changeset_id = cs.get("id")
                except Exception:
                    pass

        proposal = RepairProposal(
            evidence_execution_ids=[best_rec.execution_id],
            suggested_plan_id=suggested_plan_id,
            suggested_changeset_id=suggested_changeset_id,
            summary=f"Similar successful execution {best_rec.execution_id} (score={best_score.total_score:.2f}). Consider reusing its plan/changeset as reference.",
            pre_check=None
        )

    # Write to failed execution's artifact dir
    target_artifact = Path(target.artifact_path) if target.artifact_path else workspace / ".lonelycat" / "executions" / args.execution_id
    target_artifact.mkdir(parents=True, exist_ok=True)
    save_repair(target_artifact, proposal)
    print(f"Wrote repair.json to {target_artifact / 'repair.json'}")
    print(f"Summary: {proposal.summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
