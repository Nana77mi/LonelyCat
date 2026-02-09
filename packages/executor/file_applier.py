"""
File Applier - Applies file changes from ChangeSet

Handles:
- CREATE: Create new file
- UPDATE: Modify existing file
- DELETE: Remove file

Safety:
- Atomic operations (temp file + rename)
- Parent directory creation
- Permission preservation
- Dry-run mode support
"""

from pathlib import Path
from typing import List
import tempfile
import shutil

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from governance import ChangeSet, FileChange, Operation


class FileApplier:
    """Applies file changes to the filesystem."""

    def __init__(self, workspace_root: Path, dry_run: bool = False):
        """
        Initialize file applier.

        Args:
            workspace_root: Root directory for file operations
            dry_run: If True, simulate without actual changes
        """
        self.workspace_root = workspace_root
        self.dry_run = dry_run

    def apply_changeset(self, changeset: ChangeSet) -> List[str]:
        """
        Apply all changes in a ChangeSet.

        Args:
            changeset: ChangeSet to apply

        Returns:
            List of applied file paths

        Raises:
            Exception: If any change fails
        """
        applied = []

        for change in changeset.changes:
            try:
                self._apply_change(change)
                applied.append(change.path)
            except Exception as e:
                # If any change fails, stop (already applied changes will be rolled back by executor)
                raise Exception(f"Failed to apply change to {change.path}: {e}")

        return applied

    def _apply_change(self, change: FileChange):
        """
        Apply a single file change.

        Args:
            change: FileChange to apply

        Raises:
            Exception: If operation fails
        """
        file_path = self.workspace_root / change.path

        if change.operation == Operation.CREATE:
            self._create_file(file_path, change)

        elif change.operation == Operation.UPDATE:
            self._update_file(file_path, change)

        elif change.operation == Operation.DELETE:
            self._delete_file(file_path, change)

        else:
            raise ValueError(f"Unknown operation: {change.operation}")

    def _create_file(self, file_path: Path, change: FileChange):
        """
        Create a new file.

        Args:
            file_path: Path to create
            change: FileChange with new_content

        Raises:
            Exception: If file already exists or creation fails
        """
        if file_path.exists() and not self.dry_run:
            raise Exception(f"File already exists: {file_path}")

        if self.dry_run:
            print(f"[DRY RUN] Would create: {file_path}")
            return

        # Create parent directories
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write atomically using temp file
        temp_fd, temp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
        try:
            with open(temp_fd, 'w', encoding='utf-8') as f:
                f.write(change.new_content or "")

            # Move temp file to target (atomic on POSIX, best-effort on Windows)
            shutil.move(temp_path, file_path)

        except Exception as e:
            # Clean up temp file on failure
            try:
                Path(temp_path).unlink(missing_ok=True)
            except:
                pass
            raise e

    def _update_file(self, file_path: Path, change: FileChange):
        """
        Update an existing file.

        Args:
            file_path: Path to update
            change: FileChange with old_content and new_content

        Raises:
            Exception: If file doesn't exist or content mismatch
        """
        if not file_path.exists() and not self.dry_run:
            raise Exception(f"File does not exist: {file_path}")

        if self.dry_run:
            print(f"[DRY RUN] Would update: {file_path}")
            return

        # Verify old_content matches (safety check)
        if change.old_content is not None:
            current_content = file_path.read_text(encoding='utf-8')
            if current_content != change.old_content:
                raise Exception(
                    f"Content mismatch for {file_path}: "
                    f"expected old_content does not match current file content"
                )

        # Preserve file permissions
        original_stat = file_path.stat()

        # Write atomically using temp file
        temp_fd, temp_path = tempfile.mkstemp(dir=file_path.parent, suffix=".tmp")
        try:
            with open(temp_fd, 'w', encoding='utf-8') as f:
                f.write(change.new_content or "")

            # Preserve permissions
            Path(temp_path).chmod(original_stat.st_mode)

            # Move temp file to target (atomic)
            shutil.move(temp_path, file_path)

        except Exception as e:
            # Clean up temp file on failure
            try:
                Path(temp_path).unlink(missing_ok=True)
            except:
                pass
            raise e

    def _delete_file(self, file_path: Path, change: FileChange):
        """
        Delete a file.

        Args:
            file_path: Path to delete
            change: FileChange

        Raises:
            Exception: If file doesn't exist
        """
        if not file_path.exists() and not self.dry_run:
            raise Exception(f"File does not exist: {file_path}")

        if self.dry_run:
            print(f"[DRY RUN] Would delete: {file_path}")
            return

        # Verify old_content matches (safety check)
        if change.old_content is not None:
            current_content = file_path.read_text(encoding='utf-8')
            if current_content != change.old_content:
                raise Exception(
                    f"Content mismatch for {file_path}: "
                    f"expected old_content does not match current file content"
                )

        # Delete file
        file_path.unlink()
