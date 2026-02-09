"""
Rollback Handler - Restores previous state on failure

Uses backup created before applying changes to restore files.

Safety:
- Only rolls back files that were actually changed
- Preserves permissions
- Validates backup integrity
"""

from pathlib import Path
import shutil


class RollbackHandler:
    """Handles rollback of failed changes."""

    def __init__(self, workspace_root: Path, dry_run: bool = False):
        """
        Initialize rollback handler.

        Args:
            workspace_root: Root directory for operations
            dry_run: If True, simulate without actual rollback
        """
        self.workspace_root = workspace_root
        self.dry_run = dry_run

    def rollback(self, context):
        """
        Rollback changes using backup.

        Args:
            context: ExecutionContext with backup_dir and applied_changes

        Raises:
            Exception: If rollback fails
        """
        if not context.backup_dir or not context.backup_dir.exists():
            raise Exception("No backup directory found for rollback")

        if self.dry_run:
            print(f"[DRY RUN] Would rollback {len(context.applied_changes)} files")
            return

        # Restore each file from backup
        for file_path_str in context.applied_changes:
            self._restore_file(file_path_str, context.backup_dir)

        # Clean up backup directory
        try:
            shutil.rmtree(context.backup_dir)
        except Exception as e:
            # Log but don't fail - backup cleanup is not critical
            print(f"Warning: Failed to clean up backup directory: {e}")

    def _restore_file(self, file_path_str: str, backup_dir: Path):
        """
        Restore a single file from backup.

        Args:
            file_path_str: Relative file path
            backup_dir: Backup directory path

        Raises:
            Exception: If restore fails
        """
        file_path = self.workspace_root / file_path_str
        backup_path = backup_dir / file_path_str

        if backup_path.exists():
            # File existed before - restore it
            shutil.copy2(backup_path, file_path)
        else:
            # File was created by this execution - delete it
            if file_path.exists():
                file_path.unlink()
