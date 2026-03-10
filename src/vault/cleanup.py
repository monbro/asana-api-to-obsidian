"""
Vault and Asana cleanup operations.

``VaultCleanup`` consolidates the functionality of the former standalone scripts:

  - cleanup_vault_structure.py   (file categorisation + move/delete)
  - vault_cleanup_local.py       (local-only vault reorganisation)
  - cleanup_clients_project.py   (Asana API: delete/move tasks)
  - cleanup_client_files.py      (merge extracted items in-place)
  - vault_cleanup_final.py       (interactive status + move/delete)
  - reorganize_clients_by_section.py (group tasks → single client file)
  - analyze_clients_structure.py (read-only Asana analysis)
  - check_misplaced_files.py     (identify misplaced files)
  - show_problem_sections.py     (read-only: show Asana sections)
  - find_files.py                (read-only: list vault files)

All destructive methods default to ``dry_run=True``.  Pass ``dry_run=False``
only when you have reviewed what will be changed.  Every file deletion goes
through ``safe_delete()`` from ``src.utils.files`` — the only place in the
codebase allowed to call ``Path.unlink()``.
"""

import logging
import re
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.api.client import AsanaApiClient
from src.utils.files import safe_delete, sanitize_filename

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Patterns used across multiple methods
# ---------------------------------------------------------------------------

# Filenames considered genuine instruction/documentation files (not client items)
_ANLEITUNG_WHITELIST: frozenset = frozenset(
    {
        "Anleitung digitale Zusammenarbeit.md",
        "Anleitung Onlinekurs Zugang.md",
        "Business Profiling.md",
        "Coaching Contract.md",
        "Onboarding Checkliste.md",
        "Willkommensinfo Coaching.md",
    }
)

# Title-keyword patterns that identify instruction/guide files
_ANLEITUNG_PATTERNS: Tuple[str, ...] = (
    "anleitung",
    "leitfaden",
    "checkliste",
    "template",
    "vorlage",
    "willkommens",
    "onboarding",
    "contract",
    "profiling",
)

# Keywords suggesting a file is an archived individual client record
_ARCHIVED_KEYWORDS: Tuple[str, ...] = (
    "archived",
    "archiviert",
    "abgeschlossen",
    "inactive",
    "inaktiv",
)

# Keywords suggesting a misplaced client-session file inside an Anleitung folder
_SESSION_PATTERNS: Tuple[str, ...] = (
    "agenda",
    "session",
    "protokoll",
    "coaching call",
    "follow-up",
    "followup",
)


class VaultCleanup:
    """Analyse and clean up an Obsidian vault exported from Asana.

    Usage::

        cleanup = VaultCleanup(vault_path=Path("./obsidian-asana-import"))

        # Read-only analysis
        report = cleanup.analyze_project_structure()
        files  = cleanup.find_files_by_pattern("Clients", "*.md")
        mis    = cleanup.identify_misplaced_files()

        # Destructive operations (require dry_run=False)
        cleanup.move_files(file_list, destination, dry_run=False)
        cleanup.delete_files(file_list, dry_run=False, backup_dir=Path("./backup"))

    The optional ``api`` parameter is only required for methods that interact
    with the Asana API (``analyze_clients_api``, ``delete_tasks_from_asana``,
    ``remove_tasks_from_project``).
    """

    def __init__(
        self,
        vault_path: Path,
        api: Optional[AsanaApiClient] = None,
    ) -> None:
        self.vault_path = vault_path
        self.api = api

    # ------------------------------------------------------------------
    # READ-ONLY: structure analysis
    # ------------------------------------------------------------------

    def analyze_project_structure(self, project_name: str = "Clients") -> Dict:
        """Return a dict describing the folder structure of *project_name*.

        Args:
            project_name: Sub-folder name inside the vault to analyse.

        Returns:
            Dict with keys ``total``, ``by_section``, ``no_section``,
            ``archived``.
        """
        folder = self.vault_path / project_name
        if not folder.exists():
            logger.warning("Project folder not found: %s", folder)
            return {}

        total = 0
        by_section: Dict[str, List[str]] = defaultdict(list)
        no_section: List[str] = []
        archived: List[str] = []

        for md_file in sorted(folder.glob("*.md")):
            if md_file.name in ("INDEX.md", "README.md"):
                continue
            total += 1
            content = _read_file(md_file)
            title = _extract_title(content) or md_file.stem

            section = _extract_section(content)
            if section:
                by_section[section].append(title)
            else:
                no_section.append(title)

            if any(kw in content.lower() for kw in _ARCHIVED_KEYWORDS):
                archived.append(str(md_file))

        result = {
            "folder": str(folder),
            "total": total,
            "by_section": dict(by_section),
            "no_section": no_section,
            "archived": archived,
        }

        logger.info(
            "Analysed %s: %d files, %d sections, %d archived.",
            project_name,
            total,
            len(by_section),
            len(archived),
        )
        return result

    def find_files_by_pattern(
        self, project_name: str, glob_pattern: str = "*.md"
    ) -> List[Path]:
        """Return all files in *project_name* matching *glob_pattern*.

        Args:
            project_name: Sub-folder name inside the vault.
            glob_pattern: Glob expression (e.g. ``"*.md"``, ``"**/*.png"``).

        Returns:
            Sorted list of matching ``Path`` objects.
        """
        folder = self.vault_path / project_name
        if not folder.exists():
            logger.warning("Folder not found: %s", folder)
            return []
        files = sorted(folder.glob(glob_pattern))
        logger.info(
            "find_files_by_pattern(%s, %s) → %d files.",
            project_name,
            glob_pattern,
            len(files),
        )
        return files

    def identify_misplaced_files(
        self,
        check_folder: str = "Anleitungen & Dokumentation",
    ) -> List[Path]:
        """Return files inside *check_folder* that look like client session records.

        These are files that ended up in the Anleitung folder by accident —
        they match session/agenda patterns but are not in the whitelist of
        genuine documentation files.

        Args:
            check_folder: The folder suspected of containing misplaced files.

        Returns:
            List of ``Path`` objects for misplaced files.
        """
        folder = self.vault_path / check_folder
        if not folder.exists():
            logger.info("Folder %s does not exist, nothing to check.", check_folder)
            return []

        misplaced: List[Path] = []
        for md_file in folder.glob("*.md"):
            if md_file.name in _ANLEITUNG_WHITELIST:
                continue
            name_lower = md_file.name.lower()
            if any(pat in name_lower for pat in _SESSION_PATTERNS):
                misplaced.append(md_file)
                logger.debug("Misplaced: %s", md_file.name)

        logger.info(
            "identify_misplaced_files(%s) → %d misplaced files.",
            check_folder,
            len(misplaced),
        )
        return misplaced

    def identify_anleitungen(self, project_name: str = "Clients") -> List[Path]:
        """Return files in *project_name* that look like instructions/guides.

        Args:
            project_name: Sub-folder to scan.

        Returns:
            List of ``Path`` objects for instruction files.
        """
        folder = self.vault_path / project_name
        result: List[Path] = []
        for md_file in folder.glob("*.md"):
            if md_file.name in ("INDEX.md", "README.md"):
                continue
            name_lower = md_file.name.lower()
            content_lower = _read_file(md_file).lower()
            if any(pat in name_lower or pat in content_lower for pat in _ANLEITUNG_PATTERNS):
                result.append(md_file)
        logger.info("identify_anleitungen(%s) → %d files.", project_name, len(result))
        return result

    def identify_archived_files(self, project_name: str = "Clients") -> List[Path]:
        """Return files in *project_name* that are marked as archived.

        Args:
            project_name: Sub-folder to scan.

        Returns:
            List of ``Path`` objects for archived files.
        """
        folder = self.vault_path / project_name
        result: List[Path] = []
        for md_file in folder.glob("*.md"):
            if md_file.name in ("INDEX.md", "README.md"):
                continue
            content_lower = _read_file(md_file).lower()
            if any(kw in content_lower for kw in _ARCHIVED_KEYWORDS):
                result.append(md_file)
        logger.info("identify_archived_files(%s) → %d files.", project_name, len(result))
        return result

    def show_sections(self, project_name: str = "Clients") -> Dict[str, List[str]]:
        """Return a mapping of section name → list of file titles.

        Args:
            project_name: Sub-folder to scan.

        Returns:
            Dict mapping section names to lists of task titles.
        """
        folder = self.vault_path / project_name
        sections: Dict[str, List[str]] = defaultdict(list)
        for md_file in sorted(folder.glob("*.md")):
            if md_file.name in ("INDEX.md", "README.md"):
                continue
            content = _read_file(md_file)
            section = _extract_section(content)
            title = _extract_title(content) or md_file.stem
            sections[section or "(none)"].append(title)

        for sec, titles in sorted(sections.items()):
            logger.info("Section %r: %d tasks", sec, len(titles))
        return dict(sections)

    # ------------------------------------------------------------------
    # READ-ONLY: file discovery (from find_files.py)
    # ------------------------------------------------------------------

    def list_all_files(
        self,
        project_name: str = "Clients",
        extension: str = ".md",
    ) -> List[Path]:
        """Return all files with *extension* inside *project_name*.

        Args:
            project_name: Sub-folder to list.
            extension:    File extension filter (default ``".md"``).

        Returns:
            Sorted list of matching ``Path`` objects.
        """
        folder = self.vault_path / project_name
        files = sorted(f for f in folder.iterdir() if f.suffix == extension)
        logger.info("list_all_files(%s) → %d files.", project_name, len(files))
        return files

    # ------------------------------------------------------------------
    # DESTRUCTIVE: file operations
    # ------------------------------------------------------------------

    def move_files(
        self,
        files: List[Path],
        destination: Path,
        dry_run: bool = True,
        create_index: bool = True,
    ) -> int:
        """Move *files* into *destination*.

        Args:
            files:        List of ``Path`` objects to move.
            destination:  Target directory (created if absent).
            dry_run:      When ``True`` (default), only log what would happen.
            create_index: When ``True``, regenerate ``INDEX.md`` in destination
                          after moving.

        Returns:
            Number of files actually moved (0 in dry-run mode).
        """
        if dry_run:
            for f in files:
                logger.info("[DRY RUN] Would move: %s → %s", f.name, destination)
            return 0

        destination.mkdir(parents=True, exist_ok=True)
        moved = 0
        for f in files:
            target = destination / f.name
            try:
                shutil.move(str(f), str(target))
                logger.info("Moved: %s → %s", f.name, destination.name)
                moved += 1
            except Exception as exc:
                logger.error("Could not move %s: %s", f.name, exc)

        if create_index and moved:
            self._create_folder_index(destination)

        logger.info("Moved %d/%d files to %s.", moved, len(files), destination.name)
        return moved

    def delete_files(
        self,
        files: List[Path],
        dry_run: bool = True,
        backup_dir: Optional[Path] = None,
    ) -> int:
        """Delete *files* from the vault.

        Args:
            files:      List of ``Path`` objects to delete.
            dry_run:    When ``True`` (default), only log what would happen.
            backup_dir: If provided, copy each file here before deleting.
                        Directory is created if absent.

        Returns:
            Number of files actually deleted (0 in dry-run mode).
        """
        if dry_run:
            for f in files:
                logger.info("[DRY RUN] Would delete: %s", f)
            return 0

        if backup_dir:
            backup_dir.mkdir(parents=True, exist_ok=True)

        deleted = 0
        for f in files:
            if safe_delete(f, backup_dir=backup_dir, dry_run=False):
                deleted += 1

        logger.info("Deleted %d/%d files.", deleted, len(files))
        return deleted

    # ------------------------------------------------------------------
    # DESTRUCTIVE: reorganise by section (from reorganize_clients_by_section.py)
    # ------------------------------------------------------------------

    def reorganize_by_section(
        self,
        project_name: str = "Clients",
        dry_run: bool = True,
        backup_dir: Optional[Path] = None,
    ) -> int:
        """Group individual task files by their Section field into merged files.

        Each unique Section gets one merged markdown file containing all its
        tasks as ``## Item N`` blocks.  After merging, the original individual
        files are deleted.

        Args:
            project_name: Sub-folder to reorganise.
            dry_run:      When ``True`` (default), logs what would change.
            backup_dir:   If provided, originals are backed up before deletion.

        Returns:
            Number of merged output files created (0 in dry-run mode).
        """
        folder = self.vault_path / project_name

        # Group files by section
        by_section: Dict[str, List[Dict]] = defaultdict(list)
        for md_file in sorted(folder.glob("*.md")):
            if md_file.name in ("INDEX.md", "README.md"):
                continue
            content = _read_file(md_file)
            section = _extract_section(content) or "(Unsectioned)"
            title = _extract_title(content) or md_file.stem
            by_section[section].append({"file": md_file, "title": title, "content": content})

        if dry_run:
            for section, items in sorted(by_section.items()):
                logger.info(
                    "[DRY RUN] Section %r: would merge %d files.", section, len(items)
                )
            return 0

        if backup_dir:
            backup_dir.mkdir(parents=True, exist_ok=True)

        created = 0
        for section, items in sorted(by_section.items()):
            if len(items) < 2:
                continue  # No benefit merging a single item
            merged_title = sanitize_filename(section)
            merged_path = folder / f"{merged_title}.md"
            lines = [f"# {section}", "", f"_Merged from {len(items)} tasks_", ""]
            for i, item in enumerate(items, start=1):
                lines += [f"## Item {i}: {item['title']}", "", item["content"], ""]
            merged_path.write_text("\n".join(lines), encoding="utf-8")
            logger.info("Created merged file: %s (%d items).", merged_path.name, len(items))

            # Delete original component files
            originals = [item["file"] for item in items]
            self.delete_files(originals, dry_run=False, backup_dir=backup_dir)
            created += 1

        if created:
            self._update_project_index(project_name)

        logger.info("reorganize_by_section: created %d merged files.", created)
        return created

    # ------------------------------------------------------------------
    # DESTRUCTIVE: client file restructuring (from cleanup_client_files.py)
    # ------------------------------------------------------------------

    def restructure_client_files(
        self,
        project_name: str = "Clients",
        dry_run: bool = True,
        backup_dir: Optional[Path] = None,
    ) -> int:
        """Parse and re-categorise ``## Item`` blocks inside merged client files.

        Items are sorted into four categories:
        - **Session Protokolle** — session/protokoll/call keywords
        - **Coaching Agenda & Ziele** — agenda/ziele/goal keywords
        - **Client Overview & References** — overview/referenz/reference keywords
        - **Archive** — archived/abgeschlossen keywords

        Args:
            project_name: Sub-folder to process.
            dry_run:      When ``True`` (default), logs what would change.
            backup_dir:   If provided, original files are backed up first.

        Returns:
            Number of files restructured (0 in dry-run mode).
        """
        folder = self.vault_path / project_name
        processed = 0

        for md_file in sorted(folder.glob("*.md")):
            if md_file.name in ("INDEX.md", "README.md"):
                continue
            content = _read_file(md_file)
            items = _extract_items(content)
            if not items:
                continue

            categorised = self._categorise_items(items)
            new_content = self._build_restructured_content(md_file.stem, categorised)

            if dry_run:
                logger.info(
                    "[DRY RUN] Would restructure %s (%d items).", md_file.name, len(items)
                )
                continue

            if backup_dir:
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(md_file), str(backup_dir / md_file.name))

            md_file.write_text(new_content, encoding="utf-8")
            processed += 1
            logger.info("Restructured: %s", md_file.name)

        logger.info("restructure_client_files: processed %d files.", processed)
        return processed

    # ------------------------------------------------------------------
    # Asana API: read-only analysis
    # ------------------------------------------------------------------

    def analyze_clients_api(self) -> Optional[Dict]:
        """Fetch the Clients project from Asana and categorise its tasks.

        Requires an ``AsanaApiClient`` to be passed to the constructor.

        Returns:
            Dict with keys ``sections``, ``by_category``, ``statistics``,
            or ``None`` if the API client is not available.
        """
        if not self.api:
            logger.error("No AsanaApiClient provided; cannot query Asana API.")
            return None

        workspace_id = self.api.get_workspace_id()
        if not workspace_id:
            return None

        projects = self.api.get_projects()
        clients_project = next(
            (p for p in projects if p.get("name") == "Clients"), None
        )
        if not clients_project:
            logger.warning("Could not find 'Clients' project in Asana.")
            return None

        project_id = clients_project["gid"]
        sections = self.api.get_project_sections(project_id)
        tasks = self.api.get_project_tasks(project_id)

        by_category: Dict[str, List[Dict]] = defaultdict(list)
        for task in tasks:
            name_lower = task.get("name", "").lower()
            if task.get("completed"):
                by_category["completed"].append(task)
            elif any(pat in name_lower for pat in _ANLEITUNG_PATTERNS):
                by_category["anleitung"].append(task)
            elif any(kw in name_lower for kw in _ARCHIVED_KEYWORDS):
                by_category["archived"].append(task)
            else:
                memberships = task.get("memberships") or []
                section_name = None
                if memberships:
                    section_name = (memberships[0].get("section") or {}).get("name")
                by_category[section_name or "unsectioned"].append(task)

        statistics = {
            "total": len(tasks),
            "sections": len(sections),
            **{cat: len(items) for cat, items in by_category.items()},
        }

        logger.info(
            "analyze_clients_api: %d tasks, %d categories.",
            len(tasks),
            len(by_category),
        )
        return {
            "sections": sections,
            "by_category": dict(by_category),
            "statistics": statistics,
        }

    def show_problem_sections_api(
        self, problem_section_names: Optional[List[str]] = None
    ) -> Dict[str, List[Dict]]:
        """Return tasks in specified Asana sections for manual review.

        Requires an ``AsanaApiClient``.

        Args:
            problem_section_names: List of section names to inspect. Defaults
                                   to ``["Einzelpersonen", "Untitled Section"]``.

        Returns:
            Dict mapping section name → list of task dicts.
        """
        if not self.api:
            logger.error("No AsanaApiClient provided.")
            return {}

        problem_section_names = problem_section_names or [
            "Einzelpersonen",
            "Untitled Section",
        ]

        projects = self.api.get_projects()
        clients_project = next(
            (p for p in projects if p.get("name") == "Clients"), None
        )
        if not clients_project:
            return {}

        project_id = clients_project["gid"]
        sections = self.api.get_project_sections(project_id)

        result: Dict[str, List[Dict]] = {}
        for section in sections:
            sec_name = section.get("name", "")
            if sec_name not in problem_section_names:
                continue
            tasks = self.api.get_project_tasks(project_id)
            sec_tasks = [
                t for t in tasks
                if any(
                    (m.get("section") or {}).get("gid") == section["gid"]
                    for m in (t.get("memberships") or [])
                )
            ]
            result[sec_name] = sec_tasks
            logger.info("Section %r: %d tasks.", sec_name, len(sec_tasks))

        return result

    # ------------------------------------------------------------------
    # Asana API: destructive
    # ------------------------------------------------------------------

    def delete_tasks_from_asana(
        self,
        task_ids: List[str],
        dry_run: bool = True,
    ) -> int:
        """Permanently delete tasks from Asana.

        Requires an ``AsanaApiClient``.

        Args:
            task_ids: List of Asana task GIDs to delete.
            dry_run:  When ``True`` (default), only logs what would happen.

        Returns:
            Number of tasks successfully deleted (0 in dry-run mode).
        """
        if not self.api:
            logger.error("No AsanaApiClient provided; cannot delete from Asana.")
            return 0

        if dry_run:
            for tid in task_ids:
                logger.info("[DRY RUN] Would delete Asana task %s.", tid)
            return 0

        deleted = 0
        for tid in task_ids:
            if self.api.delete_task(tid):
                deleted += 1
        logger.info("delete_tasks_from_asana: deleted %d/%d tasks.", deleted, len(task_ids))
        return deleted

    def remove_tasks_from_project(
        self,
        task_ids: List[str],
        project_id: str,
        dry_run: bool = True,
    ) -> int:
        """Remove tasks from an Asana project without deleting them.

        Requires an ``AsanaApiClient``.

        Args:
            task_ids:   List of task GIDs to remove.
            project_id: Asana project GID to remove them from.
            dry_run:    When ``True`` (default), only logs.

        Returns:
            Number of tasks successfully removed (0 in dry-run mode).
        """
        if not self.api:
            logger.error("No AsanaApiClient provided.")
            return 0

        if dry_run:
            for tid in task_ids:
                logger.info(
                    "[DRY RUN] Would remove task %s from project %s.", tid, project_id
                )
            return 0

        removed = 0
        for tid in task_ids:
            if self.api.remove_task_from_project(tid, project_id):
                removed += 1
        logger.info(
            "remove_tasks_from_project: removed %d/%d tasks.", removed, len(task_ids)
        )
        return removed

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _create_folder_index(self, folder: Path) -> None:
        """Write a simple INDEX.md listing all .md files in *folder*."""
        files = sorted(folder.glob("*.md"))
        lines = [f"# {folder.name}", "", f"_{len(files)} items_", ""]
        for f in files:
            if f.name in ("INDEX.md", "README.md"):
                continue
            stem = f.stem
            lines.append(f"- [[{stem}]]")
        lines.append(f"\n_Last updated: {datetime.now().strftime('%Y-%m-%d')}_")
        (folder / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")
        logger.debug("Created INDEX.md for %s.", folder.name)

    def _update_project_index(self, project_name: str) -> None:
        """Regenerate the INDEX.md for *project_name* after structural changes."""
        folder = self.vault_path / project_name
        if folder.exists():
            self._create_folder_index(folder)

    def _categorise_items(
        self, items: List[Dict]
    ) -> Dict[str, List[Dict]]:
        """Sort extracted ``## Item`` blocks into categories."""
        cats: Dict[str, List[Dict]] = {
            "Session Protokolle": [],
            "Coaching Agenda & Ziele": [],
            "Client Overview & References": [],
            "Archive": [],
        }
        for item in items:
            text = (item.get("title", "") + " " + item.get("content", "")).lower()
            if any(kw in text for kw in _ARCHIVED_KEYWORDS):
                cats["Archive"].append(item)
            elif any(kw in text for kw in ("session", "protokoll", "coaching call")):
                cats["Session Protokolle"].append(item)
            elif any(kw in text for kw in ("agenda", "ziele", "goal")):
                cats["Coaching Agenda & Ziele"].append(item)
            else:
                cats["Client Overview & References"].append(item)
        return cats

    def _build_restructured_content(
        self, stem: str, categorised: Dict[str, List[Dict]]
    ) -> str:
        """Build restructured markdown content from categorised items."""
        lines = [
            f"# {stem}",
            "",
            f"_Restructured: {datetime.now().strftime('%Y-%m-%d')}_",
            "",
        ]
        for cat_name, items in categorised.items():
            if not items:
                continue
            lines += [f"## {cat_name}", ""]
            for item in items:
                lines += [f"### {item['title']}", "", item["content"], ""]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions; no side-effects)
# ---------------------------------------------------------------------------


def _read_file(path: Path) -> str:
    """Return file content as string, or empty string on read error."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return ""


def _extract_title(content: str) -> Optional[str]:
    """Return the first H1 heading from *content*, or ``None``."""
    m = re.search(r"^#\s+(.+)", content, re.MULTILINE)
    return m.group(1).strip() if m else None


def _extract_section(content: str) -> Optional[str]:
    """Return the **Section** metadata field from *content*, or ``None``."""
    m = re.search(r"\*\*Section\*\*:\s*(.+)", content)
    return m.group(1).strip() if m else None


def _extract_items(content: str) -> List[Dict]:
    """Split a merged file into its ``## Item N`` blocks."""
    parts = re.split(r"\n## Item \d+", content)
    items: List[Dict] = []
    for i, part in enumerate(parts[1:], start=1):
        lines = part.strip().splitlines()
        title = lines[0].lstrip(":").strip() if lines else f"Item {i}"
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        items.append({"title": title, "content": body})
    return items
