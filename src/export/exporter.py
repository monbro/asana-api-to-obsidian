"""
Export orchestration: coordinates the API client, state manager, and formatter.

``AsanaExporter`` is responsible only for the high-level workflow:
- verifying auth
- iterating projects and tasks
- pre-fetching all data that the formatter needs
- writing files to disk
- updating export state

It does **not** contain any markdown string-building logic (→ formatter)
or HTTP code (→ api client).
"""

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.api.client import AsanaApiClient
from src.config import ExporterSettings, SUBTASK_FETCH_DEPTH
from src.export.formatter import MarkdownFormatter
from src.export.state import ExportState
from src.utils.files import ensure_unique_path, get_file_hash, sanitize_filename

logger = logging.getLogger(__name__)


class AsanaExporter:
    """Orchestrates a full Asana workspace export to an Obsidian vault.

    Dependencies are injected so each layer can be tested independently.

    Usage::

        from pathlib import Path
        from src.config import ExporterSettings
        from src.export.exporter import AsanaExporter

        settings = ExporterSettings(token="...", vault_path=Path("./vault"))
        exporter = AsanaExporter(settings)
        exporter.export_workspace()
    """

    def __init__(self, settings: ExporterSettings) -> None:
        self.settings = settings
        self.vault_path: Path = settings.vault_path
        self.api = AsanaApiClient(settings.token)
        self.state = ExportState(settings.vault_path)
        self.formatter = MarkdownFormatter()
        self.vault_path.mkdir(parents=True, exist_ok=True)
        self._stats = self._init_stats()
        self._stats_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._attachment_lock = threading.Lock()
        self._run_started_at: Optional[datetime] = None
        logger.info("Initialized exporter for vault at: %s", self.vault_path)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def export_workspace(self) -> bool:
        """Export the entire Asana workspace to the vault.

        Returns:
            ``True`` if all projects exported without fatal error.
        """
        logger.info("=" * 60)
        logger.info("Starting Asana to Obsidian Export")
        logger.info("=" * 60)

        user = self.api.get_user_info()
        if not user:
            logger.error("Failed to authenticate with Asana API.")
            return False

        logger.info("Authenticated as: %s", user.get("name", "Unknown"))

        self._create_gitignore()

        self._stats = self._init_stats()
        self._run_started_at = datetime.now(timezone.utc)
        projects = self._get_projects_to_export()
        if not projects:
            logger.warning("No projects found.")
            return False
        exported_count = self._export_projects(projects)
        self._finalize_export(exported_count)
        return True

    # ------------------------------------------------------------------
    # Project-level export
    # ------------------------------------------------------------------

    def export_project(self, project: Dict) -> bool:
        """Export all root tasks from *project* and create INDEX.md.

        Args:
            project: Project dict from Asana API.

        Returns:
            ``True`` on success.
        """
        project_id, project_name = self._get_project_identity(project)
        logger.info("Exporting project: %s", project_name)
        project_folder = self._ensure_project_folder(project_name)
        self._write_project_readme(project, project_folder)

        tasks = self.api.get_project_tasks(project_id)
        logger.info("Found %d tasks in %s.", len(tasks), project_name)

        success_count = self._export_project_tasks(
            tasks,
            project_id,
            project_name,
            project_folder,
        )
        self._write_project_index(project_id, project_name, tasks, project_folder)
        self._log_project_summary(project_name, tasks, success_count)
        return True

    # ------------------------------------------------------------------
    # Task-level export
    # ------------------------------------------------------------------

    def export_task(
        self,
        task: Dict,
        project_name: str,
        project_folder: Path,
    ) -> bool:
        """Export a single root task to a markdown file.

        Fetches full task details, pre-fetches subtasks and stories, downloads
        attachments, then delegates formatting to ``MarkdownFormatter``.

        Args:
            task:           Lightweight task dict from ``get_project_tasks()``.
            project_name:   Human-readable project name.
            project_folder: Directory to write the markdown file in.

        Returns:
            ``True`` on success.
        """
        task_id = task.get("gid")

        if task.get("parent"):
            return True  # Subtasks are embedded in the parent

        if task.get("completed", False) and not self._should_include_completed(task):
            logger.debug(
                "Skipping completed task %s – %s.", task_id, task.get("name")
            )
            self._increment_stat("tasks_skipped_completed")
            return True

        try:
            full_task, record, remote_modified_at = self._prepare_task_export(task_id)
            if not full_task:
                return False

            file_path = self._resolve_task_path(task, record, project_folder)
            if not self._should_update_remote(record, remote_modified_at):
                logger.debug("Task %s unchanged, skipping.", task_id)
                self._increment_stat("tasks_unchanged")
                return True

            file_path, should_skip = self._handle_conflicts(task, file_path, record)
            if should_skip:
                self._increment_stat("tasks_skipped_conflict")
                return True

            subtasks, level1, nested = self._collect_subtasks(task_id)
            stories = self._collect_stories(task_id)
            downloaded = self._download_task_attachments(
                full_task,
                project_folder,
            )
            subtask_attachments = self._download_subtask_attachments(
                subtasks,
                project_folder,
            )

            markdown = self._build_task_markdown(
                full_task,
                project_name,
                downloaded,
                level1,
                nested,
                stories,
                subtask_attachments,
            )

            if file_path is None:
                file_path = self._default_task_path(task, project_folder)

            self._write_task_markdown(file_path, markdown)
            content_hash = self._compute_content_hash(file_path)

            is_new = record is None
            self._mark_task_exported(
                task_id,
                str(file_path),
                remote_modified_at,
                content_hash,
            )
            if is_new:
                self._increment_stat("tasks_new")
            else:
                self._increment_stat("tasks_updated")
            logger.info("Exported task: %s", task.get("name", "Untitled"))
            return True

        except Exception as exc:
            logger.error("Failed to export task %s: %s", task_id, exc)
            self._increment_stat("tasks_failed")
            return False

    def _get_projects_to_export(self) -> List[Dict]:
        projects = self.api.get_projects()
        if not projects:
            return []

        if self.settings.project_filter:
            needle = self.settings.project_filter.lower()
            filtered = [p for p in projects if p.get("name", "").lower() == needle]
            if not filtered:
                logger.error(
                    "No project found matching --project filter: %s",
                    self.settings.project_filter,
                )
                return []
            logger.info(
                "Project filter active: exporting only '%s'.",
                self.settings.project_filter,
            )
            return filtered

        return projects

    def _export_projects(self, projects: List[Dict]) -> int:
        exported_count = 0
        for project in projects:
            try:
                if self.export_project(project):
                    exported_count += 1
            except Exception as exc:
                logger.error(
                    "Failed to export project %s: %s", project.get("name"), exc
                )
                self._increment_stat("projects_failed")
        return exported_count

    def _finalize_export(self, exported_count: int) -> None:
        with self._stats_lock:
            self._stats["projects_exported"] = exported_count
        self._update_state_metadata()
        self._write_summary_json()

        duration_text = self._format_run_duration()

        logger.info("=" * 60)
        logger.info(
            "Export complete! Exported %d projects in %s.",
            exported_count,
            duration_text,
        )
        logger.info("Vault location: %s", self.vault_path)
        self._log_diff_report()
        logger.info("=" * 60)

    def _get_project_identity(self, project: Dict) -> Tuple[str, str]:
        return project.get("gid"), project.get("name", "Untitled")

    def _ensure_project_folder(self, project_name: str) -> Path:
        project_folder = self.vault_path / sanitize_filename(project_name)
        project_folder.mkdir(parents=True, exist_ok=True)
        return project_folder

    def _write_project_readme(self, project: Dict, project_folder: Path) -> None:
        readme_content = self.formatter.format_project_readme(project)
        (project_folder / "README.md").write_text(readme_content, encoding="utf-8")

    def _export_project_tasks(
        self,
        tasks: List[Dict],
        project_id: str,
        project_name: str,
        project_folder: Path,
    ) -> int:
        root_tasks = [t for t in tasks if not t.get("parent")]
        success_count = 0

        with ThreadPoolExecutor(max_workers=self.settings.max_workers) as executor:
            futures = []
            for task in root_tasks:
                futures.append(
                    executor.submit(
                        self._export_project_task,
                        task,
                        project_id,
                        project_name,
                        project_folder,
                    )
                )

            for future in as_completed(futures):
                try:
                    if future.result():
                        success_count += 1
                except Exception as exc:
                    logger.error("Task export failed: %s", exc)

        return success_count

    def _export_project_task(
        self,
        task: Dict,
        project_id: str,
        project_name: str,
        project_folder: Path,
    ) -> bool:
        task_projects = task.get("projects") or []
        is_primary = True
        if task_projects and not self.settings.project_filter:
            is_primary = task_projects[0].get("gid") == project_id

        if is_primary:
            return self.export_task(task, project_name, project_folder)

        if self._create_reference_file(task, project_name, project_folder):
            self._increment_stat("reference_files")
            return True
        return False

    def _write_project_index(
        self,
        project_id: str,
        project_name: str,
        tasks: List[Dict],
        project_folder: Path,
    ) -> None:
        sections = self.api.get_project_sections(project_id)
        index_content = self.formatter.format_project_index(project_name, tasks, sections)
        (project_folder / "INDEX.md").write_text(index_content, encoding="utf-8")
        logger.info("Created project index for %s.", project_name)

    def _log_project_summary(
        self,
        project_name: str,
        tasks: List[Dict],
        success_count: int,
    ) -> None:
        root_tasks = [t for t in tasks if not t.get("parent")]
        logger.info(
            "Exported %d/%d root tasks from %s.",
            success_count,
            len(root_tasks),
            project_name,
        )

    def _prepare_task_export(
        self, task_id: str
    ) -> tuple[Optional[Dict], Optional[Dict], Optional[str]]:
        full_task = self.api.get_task_details(task_id)
        if not full_task:
            logger.warning("Could not fetch full details for task %s.", task_id)
            return None, None, None

        record = self.state.get_task_record(task_id)
        remote_modified_at = full_task.get("modified_at")
        return full_task, record, remote_modified_at

    def _handle_conflicts(
        self,
        task: Dict,
        file_path: Optional[Path],
        record: Optional[Dict],
    ) -> Tuple[Optional[Path], bool]:
        if file_path and file_path.exists():
            local_modified = self._is_local_modified(file_path, record)
            if local_modified:
                if self.settings.conflict_policy == "skip":
                    logger.info(
                        "Local edits detected for %s; skipping due to policy.",
                        task.get("name"),
                    )
                    return file_path, True
                if self.settings.conflict_policy == "copy":
                    return self._conflict_copy_path(file_path), False
        return file_path, False

    def _collect_subtasks(
        self, task_id: str
    ) -> tuple[Dict[str, List[Dict]], List[Dict], Dict[str, List[Dict]]]:
        subtasks = self._fetch_subtasks_recursive(task_id, depth=1)
        level1 = subtasks.get(task_id, [])
        nested: Dict[str, List] = {}
        for sub in level1:
            sub_id = sub.get("gid", "")
            nested[sub_id] = subtasks.get(sub_id, [])
        return subtasks, level1, nested

    def _collect_stories(self, task_id: str) -> List[Dict]:
        return self.api.get_task_stories(task_id)

    def _download_task_attachments(
        self,
        full_task: Dict,
        project_folder: Path,
    ) -> List[Dict[str, str]]:
        downloaded = []
        for att in (full_task.get("attachments") or []):
            rel_path = self._resolve_attachment(att, project_folder)
            if rel_path:
                downloaded.append(
                    {"name": att.get("name", "attachment"), "path": rel_path}
                )
        return downloaded

    def _download_subtask_attachments(
        self,
        subtasks: Dict[str, List[Dict]],
        project_folder: Path,
    ) -> Dict[str, List[Dict[str, str]]]:
        subtask_attachments: Dict[str, List] = {}
        all_subtasks = [s for subs in subtasks.values() for s in subs]
        for sub in all_subtasks:
            sub_id = sub.get("gid", "")
            sub_downloaded = []
            for att in (sub.get("attachments") or []):
                rel_path = self._resolve_attachment(att, project_folder)
                if rel_path:
                    sub_downloaded.append(
                        {"name": att.get("name", "attachment"), "path": rel_path}
                    )
            if sub_downloaded:
                subtask_attachments[sub_id] = sub_downloaded
        return subtask_attachments

    def _resolve_attachment(self, attachment: Dict, project_folder: Path) -> Optional[str]:
        attachment_id = attachment.get("gid")
        if attachment_id:
            cached = self._get_attachment_path(attachment_id)
            if cached:
                self._increment_stat("attachments_skipped")
                return cached

        with self._attachment_lock:
            rel_path = self.api.download_attachment(
                attachment,
                project_folder,
                self.state.downloaded_attachments,
            )
        if rel_path:
            self._increment_stat("attachments_downloaded")
        return rel_path

    def _build_task_markdown(
        self,
        full_task: Dict,
        project_name: str,
        downloaded: List[Dict[str, str]],
        level1: List[Dict],
        nested: Dict[str, List[Dict]],
        stories: List[Dict],
        subtask_attachments: Dict[str, List[Dict[str, str]]],
    ) -> str:
        return self.formatter.format_task_markdown(
            full_task,
            project_name,
            downloaded_attachments=downloaded,
            subtasks=level1,
            nested_subtasks=nested,
            stories=stories,
            subtask_attachments=subtask_attachments,
        )

    def _default_task_path(self, task: Dict, project_folder: Path) -> Path:
        filename = sanitize_filename(task.get("name", "untitled"))
        return ensure_unique_path(project_folder / f"{filename}.md")

    def _write_task_markdown(self, file_path: Path, markdown: str) -> None:
        file_path.write_text(markdown, encoding="utf-8")

    def _compute_content_hash(self, file_path: Path) -> Optional[str]:
        try:
            return get_file_hash(file_path)
        except OSError as exc:
            logger.warning("Could not hash %s: %s", file_path, exc)
            return None

    def _update_state_metadata(self) -> None:
        with self._state_lock:
            self.state.update_last_sync()
            self.state.update_last_run()
            self.state.save()

    def _mark_task_exported(
        self,
        task_id: str,
        file_path: str,
        asana_modified_at: Optional[str],
        content_hash: Optional[str],
    ) -> None:
        with self._state_lock:
            self.state.mark_task_exported(
                task_id,
                file_path,
                asana_modified_at=asana_modified_at,
                content_hash=content_hash,
            )

    def _get_attachment_path(self, attachment_id: str) -> Optional[str]:
        with self._state_lock:
            return self.state.get_attachment_path(attachment_id)

    def _increment_stat(self, key: str) -> None:
        with self._stats_lock:
            self._stats[key] += 1

    def _init_stats(self) -> Dict[str, int]:
        return {
            "projects_exported": 0,
            "projects_failed": 0,
            "tasks_new": 0,
            "tasks_updated": 0,
            "tasks_unchanged": 0,
            "tasks_skipped_completed": 0,
            "tasks_skipped_conflict": 0,
            "tasks_failed": 0,
            "reference_files": 0,
            "attachments_downloaded": 0,
            "attachments_skipped": 0,
        }

    def _log_diff_report(self) -> None:
        logger.info("Diff report:")
        logger.info(
            "  Tasks new: %d | updated: %d | unchanged: %d",
            self._stats["tasks_new"],
            self._stats["tasks_updated"],
            self._stats["tasks_unchanged"],
        )
        logger.info(
            "  Skipped completed: %d | skipped conflicts: %d | failed: %d",
            self._stats["tasks_skipped_completed"],
            self._stats["tasks_skipped_conflict"],
            self._stats["tasks_failed"],
        )
        logger.info(
            "  Attachments downloaded: %d | reused: %d",
            self._stats["attachments_downloaded"],
            self._stats["attachments_skipped"],
        )
        if self._stats["reference_files"]:
            logger.info("  Reference files created: %d", self._stats["reference_files"])

    def _format_run_duration(self) -> str:
        if not self._run_started_at:
            return "unknown duration"

        now = datetime.now(timezone.utc)
        total_seconds = max(0, int((now - self._run_started_at).total_seconds()))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _write_summary_json(self) -> None:
        if not self._run_started_at:
            return

        now = datetime.now(timezone.utc)
        duration_seconds = (now - self._run_started_at).total_seconds()
        summary = {
            "started_at": self._run_started_at.isoformat(),
            "finished_at": now.isoformat(),
            "duration_seconds": round(duration_seconds, 2),
            "stats": self._stats,
            "settings": {
                "include_completed": self.settings.include_completed,
                "completed_within_days": self.settings.completed_within_days,
                "project_filter": self.settings.project_filter,
                "conflict_policy": self.settings.conflict_policy,
                "max_workers": self.settings.max_workers,
            },
        }

        summary_path = self.vault_path / ".asana_export_summary.json"
        try:
            summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            logger.info("Wrote summary to %s.", summary_path)
        except OSError as exc:
            logger.error("Could not write summary JSON: %s", exc)

    def _should_include_completed(self, task: Dict) -> bool:
        if not task.get("completed", False):
            return True

        if self.settings.completed_within_days is not None:
            completed_at = task.get("completed_at") or ""
            return self._completed_within_days(completed_at)

        return self.settings.include_completed

    def _completed_within_days(self, completed_at: str) -> bool:
        if not completed_at:
            return False
        try:
            parsed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        now = datetime.now(timezone.utc)
        delta = now - parsed.astimezone(timezone.utc)
        return delta.days <= self.settings.completed_within_days

    def _fetch_subtasks_recursive(
        self, task_id: str, depth: int
    ) -> Dict[str, List[Dict]]:
        """Return a mapping of {task_gid: [subtask_dicts]} up to SUBTASK_FETCH_DEPTH.

        Args:
            task_id: GID of the parent task.
            depth:   Current recursion depth (starts at 1).

        Returns:
            Dict where each key is a task GID and value is its direct subtasks.
        """
        result: Dict[str, List[Dict]] = {}
        subtasks = self.api.get_task_subtasks(task_id)
        result[task_id] = subtasks

        if depth < SUBTASK_FETCH_DEPTH:
            for sub in subtasks:
                sub_id = sub.get("gid", "")
                if sub_id and sub.get("num_subtasks", 0) > 0:
                    child_map = self._fetch_subtasks_recursive(sub_id, depth + 1)
                    result.update(child_map)

        return result

    def _resolve_task_path(
        self,
        task: Dict,
        record: Optional[Dict],
        project_folder: Path,
    ) -> Optional[Path]:
        """Return the existing path for a task if it is still present."""
        if record:
            stored = record.get("file")
            if stored:
                path = Path(stored)
                if path.exists():
                    return path
        return None

    def _should_update_remote(
        self,
        record: Optional[Dict],
        remote_modified_at: Optional[str],
    ) -> bool:
        """Return True when the remote task changed or was never exported."""
        if not record:
            return True
        last_remote = record.get("asana_modified_at")
        if not last_remote:
            return True
        return last_remote != remote_modified_at

    def _is_local_modified(self, file_path: Path, record: Optional[Dict]) -> bool:
        """Return True if the local file content differs from last export."""
        if not record:
            return False
        expected_hash = record.get("content_hash")
        if not expected_hash:
            return False
        try:
            current_hash = get_file_hash(file_path)
        except OSError:
            return False
        return current_hash != expected_hash

    def _conflict_copy_path(self, file_path: Path) -> Path:
        """Return a new path for a conflict copy of *file_path*."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        conflict_name = f"{file_path.stem}_CONFLICT_{timestamp}{file_path.suffix}"
        return ensure_unique_path(file_path.parent / conflict_name)

    # ------------------------------------------------------------------
    # Reference file (task in multiple projects)
    # ------------------------------------------------------------------

    def _create_reference_file(
        self, task: Dict, current_project_name: str, project_folder: Path
    ) -> bool:
        """Write a cross-project reference stub file.

        Args:
            task:                 Lightweight task dict.
            current_project_name: The project this reference lives in.
            project_folder:       Directory to write the file in.

        Returns:
            ``True`` on success.
        """
        try:
            task_projects = task.get("projects") or []
            primary_project_name = (
                task_projects[0].get("name", "Unknown") if task_projects else "Unknown"
            )
            ref_content = self.formatter.format_reference_file(
                task, current_project_name, primary_project_name
            )
            filename = sanitize_filename(task.get("name", "untitled"))
            ref_path = ensure_unique_path(project_folder / f"{filename}.md")
            ref_path.write_text(ref_content, encoding="utf-8")
            logger.debug("Created reference for %s.", task.get("name"))
            return True
        except Exception as exc:
            logger.error(
                "Failed to create reference for task %s: %s", task.get("gid"), exc
            )
            return False

    # ------------------------------------------------------------------
    # Vault setup
    # ------------------------------------------------------------------

    def _create_gitignore(self) -> None:
        """Ensure the vault has the exporter .gitignore entries."""
        block = """# Asana Obsidian Export

# Attachment files and media
attachments/
*.png
*.jpg
*.jpeg
*.gif
*.pdf
*.doc
*.docx
*.xls
*.xlsx
*.zip
*.tar
*.gz

# Obsidian cache
.obsidian/cache
.obsidian/plugins
.obsidian/workspace*

# System files
.DS_Store
Thumbs.db
.gitignore
*.pyc
__pycache__/

# Export state (regenerated on each run)
.asana_export_state.json
"""
        gitignore_path = self.vault_path / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text(block)
            logger.info("Created .gitignore at %s.", gitignore_path)
            return

        existing = gitignore_path.read_text(encoding="utf-8")
        if "# Asana Obsidian Export" in existing:
            logger.debug(".gitignore already contains exporter entries.")
            return

        separator = "\n" if existing.endswith("\n") else "\n\n"
        gitignore_path.write_text(existing + separator + block, encoding="utf-8")
        logger.info("Appended exporter entries to .gitignore at %s.", gitignore_path)
