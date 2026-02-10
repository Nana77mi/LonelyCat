"""
Generate reflection_hints.json for Phase 2.4-C.

Scans executions (and optionally events.jsonl) to produce:
- hot_error_steps: steps that fail often
- slow_steps: steps with high average duration
- suggested_policy: brief suggestions

Output: .lonelycat/reflection/hints_7d.json (or --window 24h).

Usage:
    python scripts/generate_reflection_hints.py
    python scripts/generate_reflection_hints.py --workspace /path --window 7d --output .lonelycat/reflection/hints_7d.json
"""

import argparse
import sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

# Repo root
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages"))

from executor.storage import ExecutionStore
from executor.reflection_hints import ReflectionHints, save_hints


def parse_window(window: str) -> timedelta:
    """Parse window like 7d, 24h into timedelta."""
    window = window.strip().lower()
    if window.endswith("d"):
        return timedelta(days=int(window[:-1]))
    if window.endswith("h"):
        return timedelta(hours=int(window[:-1]))
    return timedelta(days=7)


def main():
    parser = argparse.ArgumentParser(description="Generate reflection hints from execution history")
    parser.add_argument("--workspace", type=Path, default=REPO_ROOT, help="Workspace root")
    parser.add_argument("--window", type=str, default="7d", help="Time window: 7d, 24h")
    parser.add_argument("--output", type=Path, default=None, help="Output path (default: .lonelycat/reflection/hints_{window}.json)")
    parser.add_argument("--limit", type=int, default=200, help="Max executions to scan")
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    db_path = workspace / ".lonelycat" / "executor.db"
    if not db_path.exists():
        print(f"No executor DB at {db_path}; writing empty hints.")
        hints = ReflectionHints(window=args.window)
        out_path = args.output or workspace / ".lonelycat" / "reflection" / f"hints_{args.window}.json"
        save_hints(out_path, hints)
        print(f"Wrote {out_path}")
        return 0

    store = ExecutionStore(workspace)
    delta = parse_window(args.window)
    cutoff = (datetime.now(timezone.utc) - delta).isoformat()

    records = store.list_executions(limit=args.limit)
    # Filter by started_at >= cutoff (simple string compare for ISO)
    recent = [r for r in records if r.started_at >= cutoff]
    failed = [r for r in recent if r.status in ("failed", "rolled_back")]

    evidence_ids = [r.execution_id for r in failed[:50]]

    # Hot error steps: count error_step in failed executions
    error_step_counts = Counter()
    for r in failed:
        if r.error_step:
            error_step_counts[r.error_step] += 1
    hot_error_steps = [s for s, _ in error_step_counts.most_common(5)]

    # Slow steps: from execution_steps if available (avg duration per step_name)
    step_durations = defaultdict(list)
    for r in recent[:100]:
        steps = store.get_execution_steps(r.execution_id)
        for st in steps:
            if st.duration_seconds is not None and st.duration_seconds > 0:
                step_durations[st.step_name].append(st.duration_seconds)
    avg_by_step = {name: sum(durs) / len(durs) for name, durs in step_durations.items() if durs}
    slow_steps = sorted(avg_by_step.keys(), key=lambda x: avg_by_step[x], reverse=True)[:5]

    # Suggested policy (simple heuristics)
    suggested_policy = []
    if hot_error_steps:
        suggested_policy.append(f"Recent failures often at: {', '.join(hot_error_steps)}. Consider strengthening verification or rollback for these steps.")
    if not suggested_policy:
        suggested_policy.append("No strong patterns in recent failures.")

    hints = ReflectionHints(
        hot_error_steps=hot_error_steps,
        false_allow_patterns=[],
        slow_steps=slow_steps,
        suggested_policy=suggested_policy,
        evidence_execution_ids=evidence_ids,
        window=args.window,
    )

    out_path = args.output or workspace / ".lonelycat" / "reflection" / f"hints_{args.window}.json"
    save_hints(out_path, hints)
    print(f"Wrote {out_path} (digest={hints.digest()[:16]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
