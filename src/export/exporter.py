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

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

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

        projects = self.api.get_projects()
        if not projects:
            logger.warning("No projects found.")
            return False

        if self.settings.project_filter:
            needle = self.settings.project_filter.lower()
            projects = [p for p in projects if p.get("name", "").lower() == needle]
            if not projects:
                logger.error(
                    "No project found matching --project filter: %s",
                    self.settings.project_filter,
                )
                return False
            logger.info(
                "Project filter active: exporting only '%s'.",
                self.settings.project_filter,
            )

        exported_count = 0
        for project in projects:
            try:
                if self.export_project(project):
                    exported_count += 1
            except Exception as exc:
                logger.error(
                    "Failed to export project %s: %s", project.get("name"), exc
                )

        self.state.update_last_sync()
        self.state.save()

        logger.info("=" * 60)
        logger.info("Export complete! Exported %d projects.", exported_count)
        logger.info("Vault location: %s", self.vault_path)
        logger.info("=" * 60)
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
        project_id = project.get("gid")
        project_name = project.get("name", "Untitled")
        logger.info("Exporting project: %s", project_name)

        project_folder = self.vault_path / sanitize_filename(project_name)
        project_folder.mkdir(parents=True, exist_ok=True)

        # README
        readme_content = self.formatter.format_project_readme(project)
        (project_folder / "README.md").write_text(readme_content, encoding="utf-8")

        tasks = self.api.get_project_tasks(project_id)
        logger.info("Found %d tasks in %s.", len(tasks), project_name)

        success_count = 0
        for task in tasks:
            # Subtasks are embedded inside their parent — skip them here
            if task.get("parent"):
                logger.debug("Skipping subtask: %s", task.get("name"))
                continue

            task_id = task.get("gid")
            task_projects = task.get("projects") or []

            # Determine primary project (first listed == owner).
            # When a project filter is active we treat every task as primary
            # so that the filtered folder always gets full exports, not stubs
            # pointing to folders that don't exist in this single-project run.
            is_primary = True
            if task_projects and not self.settings.project_filter:
                is_primary = task_projects[0].get("gid") == project_id

            if is_primary:
                if self.export_task(task, project_name, project_folder):
                    success_count += 1
            else:
                if self._create_reference_file(task, project_name, project_folder):
                    success_count += 1

        sections = self.api.get_project_sections(project_id)
        index_content = self.formatter.format_project_index(project_name, tasks, sections)
        (project_folder / "INDEX.md").write_text(index_content, encoding="utf-8")
        logger.info("Created project index for %s.", project_name)

        root_tasks = [t for t in tasks if not t.get("parent")]
        logger.info(
            "Exported %d/%d root tasks from %s.",
            success_count,
            len(root_tasks),
            project_name,
        )
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

        if task.get("completed", False):
            logger.debug(
                "Skipping completed task %s – %s.", task_id, task.get("name")
            )
            return True

        try:
            full_task = self.api.get_task_details(task_id)
            if not full_task:
                logger.warning("Could not fetch full details for task %s.", task_id)
                return False

            record = self.state.get_task_record(task_id)
            remote_modified_at = full_task.get("modified_at")
            should_update_remote = self._should_update_remote(record, remote_modified_at)
            file_path = self._resolve_task_path(
                task,
                record,
                project_folder,
            )

            if not should_update_remote:
                logger.debug("Task %s unchanged, skipping.", task_id)
                return True

            if file_path and file_path.exists():
                local_modified = self._is_local_modified(file_path, record)
                if local_modified:
                    if self.settings.conflict_policy == "skip":
                        logger.info(
                            "Local edits detected for %s; skipping due to policy.",
                            task.get("name"),
                        )
                        return True
                    if self.settings.conflict_policy == "copy":
                        file_path = self._conflict_copy_path(file_path)

            # Pre-fetch subtasks (up to SUBTASK_FETCH_DEPTH levels)
            subtasks = self._fetch_subtasks_recursive(task_id, depth=1)
            # Flatten: for the formatter we need level-1 subtasks + their children
            level1 = subtasks.get(task_id, [])
            nested: Dict[str, List] = {}
            for sub in level1:
                sub_id = sub.get("gid", "")
                nested[sub_id] = subtasks.get(sub_id, [])

            # Pre-fetch stories
            stories = self.api.get_task_stories(task_id)

            # Download attachments for the main task
            downloaded = []
            for att in (full_task.get("attachments") or []):
                rel_path = self.api.download_attachment(
                    att, project_folder, self.state.downloaded_attachments
                )
                if rel_path:
                    downloaded.append(
                        {"name": att.get("name", "attachment"), "path": rel_path}
                    )

            # Download attachments for every subtask (all fetched levels)
            subtask_attachments: Dict[str, List] = {}
            all_subtasks = [s for subs in subtasks.values() for s in subs]
            for sub in all_subtasks:
                sub_id = sub.get("gid", "")
                sub_downloaded = []
                for att in (sub.get("attachments") or []):
                    rel_path = self.api.download_attachment(
                        att, project_folder, self.state.downloaded_attachments
                    )
                    if rel_path:
                        sub_downloaded.append(
                            {"name": att.get("name", "attachment"), "path": rel_path}
                        )
                if sub_downloaded:
                    subtask_attachments[sub_id] = sub_downloaded

            markdown = self.formatter.format_task_markdown(
                full_task,
                project_name,
                downloaded_attachments=downloaded,
                subtasks=level1,
                nested_subtasks=nested,
                stories=stories,
                subtask_attachments=subtask_attachments,
            )

            if file_path is None:
                filename = sanitize_filename(task.get("name", "untitled"))
                file_path = ensure_unique_path(project_folder / f"{filename}.md")

            file_path.write_text(markdown, encoding="utf-8")
            content_hash = None
            try:
                content_hash = get_file_hash(file_path)
            except OSError as exc:
                logger.warning("Could not hash %s: %s", file_path, exc)

            self.state.mark_task_exported(
                task_id,
                str(file_path),
                asana_modified_at=remote_modified_at,
                content_hash=content_hash,
            )
            logger.info("Exported task: %s", task.get("name", "Untitled"))
            return True

        except Exception as exc:
            logger.error("Failed to export task %s: %s", task_id, exc)
            return False

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
        """Write a .gitignore to the vault root."""
        content = """# Asana Obsidian Export

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
        gitignore_path.write_text(content)
        logger.info("Created .gitignore at %s.", gitignore_path)
