"""
Artifact Manager - 2.2-A: Artifact规范与落盘

Provides unified, indexed, and cleanable directory structure for execution evidence.

Directory Structure:
    .lonelycat/
      executions/
        exec_abc123/
          plan.json           # ChangePlan
          changeset.json      # ChangeSet
          decision.json       # GovernanceDecision
          execution.json      # ExecutionResult
          steps/              # Step-by-step logs
            01_validate.log
            02_backup.log
            03_apply.log
            04_verify.log
            05_health.log
          backups/            # Rollback evidence
          stdout.log          # Merged stdout
          stderr.log          # Merged stderr

Features:
- Retention: Keep last 7 days or N executions
- Cleanup: LRU (least recently used)
- Append-only: Never modify existing files
- Fast lookup: execution_id → artifact directory
"""

import json
import shutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import os

# Import models
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from governance import ChangePlan, ChangeSet, GovernanceDecision


@dataclass
class ArtifactConfig:
    """Configuration for artifact storage."""
    retention_days: int = 7  # Keep artifacts for 7 days
    retention_count: int = 100  # Or keep last 100 executions
    cleanup_strategy: str = "lru"  # lru, fifo, or manual
    base_dir: Path = Path(".lonelycat/executions")


class ArtifactManager:
    """
    Manages execution artifacts with unified directory structure.

    Responsibilities:
    - Create execution artifact directory
    - Write plan/changeset/decision/execution JSONs
    - Manage step logs (append-only)
    - Link/copy backups
    - Cleanup old artifacts (retention policy)
    - Fast lookup by execution_id
    """

    def __init__(self, workspace_root: Path, config: Optional[ArtifactConfig] = None):
        """
        Initialize artifact manager.

        Args:
            workspace_root: Workspace root directory
            config: Artifact configuration (defaults if None)
        """
        self.workspace_root = Path(workspace_root).resolve()
        self.config = config or ArtifactConfig()

        # Base directory for all executions
        self.base_dir = self.workspace_root / self.config.base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_execution_dir(self, execution_id: str) -> Path:
        """
        Create artifact directory for execution.

        Args:
            execution_id: Unique execution ID

        Returns:
            Path to execution artifact directory
        """
        exec_dir = self.base_dir / execution_id
        exec_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (exec_dir / "steps").mkdir(exist_ok=True)
        (exec_dir / "backups").mkdir(exist_ok=True)

        # Create empty log files
        (exec_dir / "stdout.log").touch(exist_ok=True)
        (exec_dir / "stderr.log").touch(exist_ok=True)

        return exec_dir

    def write_plan(self, execution_id: str, plan: ChangePlan) -> Path:
        """
        Write ChangePlan to plan.json.

        Args:
            execution_id: Execution ID
            plan: ChangePlan object

        Returns:
            Path to plan.json
        """
        exec_dir = self.base_dir / execution_id
        plan_file = exec_dir / "plan.json"

        # Convert to dict (handle datetime serialization)
        plan_dict = self._serialize_dataclass(plan)

        with open(plan_file, 'w', encoding='utf-8') as f:
            json.dump(plan_dict, f, indent=2, ensure_ascii=False)

        return plan_file

    def write_changeset(self, execution_id: str, changeset: ChangeSet) -> Path:
        """
        Write ChangeSet to changeset.json.

        Args:
            execution_id: Execution ID
            changeset: ChangeSet object

        Returns:
            Path to changeset.json
        """
        exec_dir = self.base_dir / execution_id
        changeset_file = exec_dir / "changeset.json"

        changeset_dict = self._serialize_dataclass(changeset)

        with open(changeset_file, 'w', encoding='utf-8') as f:
            json.dump(changeset_dict, f, indent=2, ensure_ascii=False)

        return changeset_file

    def write_decision(self, execution_id: str, decision: GovernanceDecision) -> Path:
        """
        Write GovernanceDecision to decision.json.

        Args:
            execution_id: Execution ID
            decision: GovernanceDecision object

        Returns:
            Path to decision.json
        """
        exec_dir = self.base_dir / execution_id
        decision_file = exec_dir / "decision.json"

        decision_dict = self._serialize_dataclass(decision)

        with open(decision_file, 'w', encoding='utf-8') as f:
            json.dump(decision_dict, f, indent=2, ensure_ascii=False)

        return decision_file

    def write_execution(self, execution_id: str, execution_result: Dict[str, Any]) -> Path:
        """
        Write ExecutionResult to execution.json.

        Args:
            execution_id: Execution ID
            execution_result: ExecutionResult dict (from to_dict())

        Returns:
            Path to execution.json
        """
        exec_dir = self.base_dir / execution_id
        execution_file = exec_dir / "execution.json"

        with open(execution_file, 'w', encoding='utf-8') as f:
            json.dump(execution_result, f, indent=2, ensure_ascii=False)

        return execution_file

    def append_step_log(
        self,
        execution_id: str,
        step_num: int,
        step_name: str,
        content: str
    ) -> Path:
        """
        Append to step log (append-only).

        Args:
            execution_id: Execution ID
            step_num: Step number (1-based)
            step_name: Step name (e.g., "validate", "backup", "apply")
            content: Log content to append

        Returns:
            Path to step log file
        """
        exec_dir = self.base_dir / execution_id
        step_file = exec_dir / "steps" / f"{step_num:02d}_{step_name}.log"

        # Append-only write
        with open(step_file, 'a', encoding='utf-8') as f:
            timestamp = datetime.utcnow().isoformat()
            f.write(f"[{timestamp}] {content}\n")

        return step_file

    def link_backup(self, execution_id: str, backup_source: Path) -> Path:
        """
        Link or copy backup directory to artifact.

        Args:
            execution_id: Execution ID
            backup_source: Source backup directory

        Returns:
            Path to linked backup
        """
        exec_dir = self.base_dir / execution_id
        backup_target = exec_dir / "backups"

        # Copy backup contents to artifact backups/
        if backup_source.exists():
            for item in backup_source.rglob("*"):
                if item.is_file():
                    relative = item.relative_to(backup_source)
                    target = backup_target / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, target)

        return backup_target

    def append_stdout(self, execution_id: str, content: str):
        """Append to stdout.log (append-only)."""
        exec_dir = self.base_dir / execution_id
        with open(exec_dir / "stdout.log", 'a', encoding='utf-8') as f:
            f.write(content)

    def append_stderr(self, execution_id: str, content: str):
        """Append to stderr.log (append-only)."""
        exec_dir = self.base_dir / execution_id
        with open(exec_dir / "stderr.log", 'a', encoding='utf-8') as f:
            f.write(content)

    def get_execution_dir(self, execution_id: str) -> Optional[Path]:
        """
        Get execution artifact directory.

        Args:
            execution_id: Execution ID

        Returns:
            Path if exists, None otherwise
        """
        exec_dir = self.base_dir / execution_id
        return exec_dir if exec_dir.exists() else None

    def list_executions(self, limit: Optional[int] = None) -> List[str]:
        """
        List all execution IDs, sorted by mtime (newest first).

        Args:
            limit: Max number to return

        Returns:
            List of execution IDs
        """
        executions = []

        for item in self.base_dir.iterdir():
            if item.is_dir() and item.name.startswith("exec_"):
                executions.append((item.name, item.stat().st_mtime))

        # Sort by mtime descending (newest first)
        executions.sort(key=lambda x: x[1], reverse=True)

        exec_ids = [name for name, _ in executions]

        if limit:
            return exec_ids[:limit]
        return exec_ids

    def cleanup_old_artifacts(self) -> int:
        """
        Cleanup old artifacts based on retention policy.

        Strategy:
        - Keep last retention_count executions (LRU)
        - AND remove artifacts older than retention_days

        Priority: Always keep retention_count newest, then remove by age.

        Returns:
            Number of artifacts removed
        """
        if self.config.cleanup_strategy == "manual":
            return 0

        all_executions = self.list_executions()
        removed_count = 0

        # Strategy: Keep last retention_count, then check age for older ones
        cutoff_time = datetime.now() - timedelta(days=self.config.retention_days)

        for idx, exec_id in enumerate(all_executions):
            exec_dir = self.base_dir / exec_id

            # Always keep the newest retention_count executions
            if idx < self.config.retention_count:
                continue  # Keep this one

            # For older executions, check if they exceed retention_days
            mtime = datetime.fromtimestamp(exec_dir.stat().st_mtime)
            is_old = mtime < cutoff_time

            if is_old:
                shutil.rmtree(exec_dir)
                removed_count += 1

        return removed_count

    def _serialize_dataclass(self, obj: Any) -> Dict[str, Any]:
        """
        Serialize dataclass to dict (handle datetime, enums).

        Args:
            obj: Dataclass instance

        Returns:
            Serializable dict
        """
        def convert(value):
            if isinstance(value, datetime):
                return value.isoformat()
            elif hasattr(value, 'value'):  # Enum
                return value.value
            elif isinstance(value, list):
                return [convert(item) for item in value]
            elif hasattr(value, '__dict__'):  # Nested dataclass
                return {k: convert(v) for k, v in value.__dict__.items()}
            else:
                return value

        return {k: convert(v) for k, v in obj.__dict__.items()}


def replay_execution(artifact_dir: Path) -> Dict[str, Any]:
    """
    Replay/audit execution from artifact directory.

    Loads all JSONs and returns comprehensive audit record.

    Args:
        artifact_dir: Path to execution artifact directory

    Returns:
        Dict with plan, changeset, decision, execution, step_logs
    """
    result = {}

    # Load JSONs
    for json_file in ["plan.json", "changeset.json", "decision.json", "execution.json"]:
        file_path = artifact_dir / json_file
        if file_path.exists():
            with open(file_path, 'r', encoding='utf-8') as f:
                key = json_file.replace('.json', '')
                result[key] = json.load(f)

    # Load step logs
    step_logs = {}
    steps_dir = artifact_dir / "steps"
    if steps_dir.exists():
        for log_file in sorted(steps_dir.glob("*.log")):
            step_logs[log_file.stem] = log_file.read_text(encoding='utf-8')
    result['step_logs'] = step_logs

    # Load stdout/stderr
    stdout_file = artifact_dir / "stdout.log"
    stderr_file = artifact_dir / "stderr.log"

    if stdout_file.exists():
        result['stdout'] = stdout_file.read_text(encoding='utf-8')
    if stderr_file.exists():
        result['stderr'] = stderr_file.read_text(encoding='utf-8')

    return result
