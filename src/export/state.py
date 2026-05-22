"""
Export state management for incremental backups.

Tracks which tasks and attachments have already been exported so subsequent
runs skip already-processed items.  The state is persisted as JSON in the
vault root at ``STATE_FILENAME``.

Backward-compatible: the JSON schema matches existing ``.asana_export_state.json``
files.  Any missing top-level keys are silently added with empty defaults on
load (migration-safe).
"""

import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.config import STATE_FILENAME

logger = logging.getLogger(__name__)

# Default schema — must match the structure of existing state files
_DEFAULT_STATE: Dict[str, Any] = {
    "exported_tasks": {},
    "downloaded_attachments": {},
    "last_run": None,
    "last_sync": None,
}


class ExportState:
    """Persistent state for incremental Asana exports.

    Usage::

        state = ExportState(vault_path)
        if not state.is_task_exported(task_id):
            # ... export the task ...
            state.mark_task_exported(task_id, str(file_path))
        state.save()
    """

    def __init__(self, vault_path: Path) -> None:
        self._path: Path = vault_path / STATE_FILENAME
        self._data: Dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load state from disk, falling back to defaults on any error."""
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # Merge loaded data onto the default schema so old files that
                # are missing newer keys still work correctly.
                self._data = copy.deepcopy(_DEFAULT_STATE)
                self._data.update(loaded)
                return
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load state file (%s), using defaults.", exc)

        self._data = copy.deepcopy(_DEFAULT_STATE)

    def save(self) -> None:
        """Persist state to disk.  Logs an error but does not raise on failure."""
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError as exc:
            logger.error("Could not save state file: %s", exc)

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    def is_task_exported(self, task_id: str) -> bool:
        """Return ``True`` if *task_id* has been exported in a previous run."""
        return task_id in self._data["exported_tasks"]

    def get_task_record(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Return the stored record for *task_id*, or ``None`` if not present."""
        return self._data["exported_tasks"].get(task_id)

    def get_task_path(self, task_id: str) -> Optional[str]:
        """Return the stored file path for *task_id*, or ``None``."""
        record = self.get_task_record(task_id)
        if not record:
            return None
        return record.get("file")

    def mark_task_exported(
        self,
        task_id: str,
        file_path: str,
        asana_modified_at: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> None:
        """Record that *task_id* was exported to *file_path*."""
        record: Dict[str, Any] = {
            "file": file_path,
            "exported_at": datetime.now().isoformat(),
        }
        if asana_modified_at:
            record["asana_modified_at"] = asana_modified_at
        if content_hash:
            record["content_hash"] = content_hash
        self._data["exported_tasks"][task_id] = record

    # ------------------------------------------------------------------
    # Attachments
    # ------------------------------------------------------------------

    def is_attachment_downloaded(self, attachment_id: str) -> bool:
        """Return ``True`` if *attachment_id* was downloaded in a previous run."""
        return attachment_id in self._data["downloaded_attachments"]

    def get_attachment_path(self, attachment_id: str) -> Optional[str]:
        """Return the stored relative path for *attachment_id*, or ``None``."""
        return self._data["downloaded_attachments"].get(attachment_id)

    def mark_attachment_downloaded(
        self, attachment_id: str, relative_path: str
    ) -> None:
        """Record the *relative_path* for a downloaded attachment."""
        self._data["downloaded_attachments"][attachment_id] = relative_path

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def update_last_sync(self) -> None:
        """Set ``last_sync`` to the current UTC ISO-8601 timestamp."""
        self._data["last_sync"] = datetime.now().isoformat()

    def update_last_run(self) -> None:
        """Set ``last_run`` to the current UTC ISO-8601 timestamp."""
        self._data["last_run"] = datetime.now().isoformat()

    # ------------------------------------------------------------------
    # Direct access (kept for compatibility with legacy code that reads
    # self.state["exported_tasks"] / self.state["downloaded_attachments"])
    # ------------------------------------------------------------------

    @property
    def exported_tasks(self) -> Dict[str, Any]:
        """Direct access to the exported_tasks dict (read/write)."""
        return self._data["exported_tasks"]

    @property
    def downloaded_attachments(self) -> Dict[str, str]:
        """Direct access to the downloaded_attachments dict (read/write)."""
        return self._data["downloaded_attachments"]
