"""
Vault scanning and task parsing.

``VaultScanner`` provides the shared implementation that was previously
duplicated in both ``enhance_vault.py`` and ``enhance_vault_advanced.py``.
All vault-aware code that needs to read task files goes through this class.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.config import SKIP_FILENAMES

logger = logging.getLogger(__name__)

# Project-category keyword lists used by _generate_tags()
_NEXT_PROJECTS = frozenset(["_ Next", "_ Inbox (Business)", "_ Scheduled"])
_CLIENT_PROJECTS = frozenset(["Clients", "= Resources 4 Clients"])
_METHOD_PROJECTS = frozenset(
    ["Methoden Koffer", "Systemische Methoden", "@ Thought Tank Business", "@ Thought Tank"]
)
_LEARNING_PROJECTS = frozenset(
    ["= How to coach _ Read _ Research", "ICA Ausbildung", "@ Read _ Watch Coaching"]
)


class VaultScanner:
    """Scan an Obsidian vault and parse task markdown files into dicts.

    Usage::

        scanner = VaultScanner(Path("./obsidian-asana-import"))
        tasks = scanner.scan_vault()          # flat list
        by_proj = scanner.scan_vault_by_project()  # {project_name: [tasks]}
    """

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path

    # ------------------------------------------------------------------
    # Public scan methods
    # ------------------------------------------------------------------

    def scan_vault(self) -> List[Dict]:
        """Return all parsed task dicts as a flat list.

        Skips hidden directories (starting with ``"."``) and filenames in
        ``SKIP_FILENAMES``.
        """
        tasks: List[Dict] = []
        for project_dir in self.vault_path.iterdir():
            if not project_dir.is_dir() or project_dir.name.startswith("."):
                continue
            project_name = project_dir.name
            for md_file in project_dir.glob("*.md"):
                if md_file.name in SKIP_FILENAMES:
                    continue
                task = self._parse_task(md_file, project_name)
                if task:
                    tasks.append(task)
        logger.info("Found %d tasks across %d project directories.", len(tasks), len(list(self.vault_path.iterdir())))
        return tasks

    def scan_vault_by_project(self) -> Dict[str, List[Dict]]:
        """Return parsed task dicts grouped by project name.

        Returns:
            ``{project_name: [task_dict, ...]}`` — projects with no parseable
            tasks are omitted.
        """
        by_project: Dict[str, List[Dict]] = defaultdict(list)
        for project_dir in self.vault_path.iterdir():
            if not project_dir.is_dir() or project_dir.name.startswith("."):
                continue
            project_name = project_dir.name
            for md_file in project_dir.glob("*.md"):
                if md_file.name in SKIP_FILENAMES:
                    continue
                task = self._parse_task(md_file, project_name)
                if task:
                    by_project[project_name].append(task)
        return dict(by_project)

    # ------------------------------------------------------------------
    # Internal parsing helpers
    # ------------------------------------------------------------------

    def _parse_task(self, file_path: Path, project_name: str) -> Optional[Dict]:
        """Parse a single markdown task file into a dict.

        Returns ``None`` (and logs a warning) if the file cannot be read
        or parsed rather than raising.

        Keys in the returned dict:
        - ``path``          Path object
        - ``filename``      file name string
        - ``title``         H1 heading or file stem as fallback
        - ``project``       project_name argument
        - ``content``       full file text
        - ``due_date``      ISO date string or ``None``
        - ``assignee``      string or ``None``
        - ``section``       string or ``None``
        - ``custom_fields`` list of ``(name, value)`` tuples
        - ``context``       one of: client/method/learning/template/reference/general
        - ``tags``          list of tag strings (with ``#`` prefix)
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("Could not read %s: %s", file_path, exc)
            return None

        try:
            # Title
            title_match = re.search(r"^# (.+?)$", content, re.MULTILINE)
            title = title_match.group(1) if title_match else file_path.stem

            # Due date
            due_match = re.search(r"\| Due Date \| (.+?) \|", content)
            due_date = due_match.group(1).strip() if due_match else None

            # Assignee
            assignee_match = re.search(
                r"\*\*Assigned to\*\*: (.+?)(?:\n|$)", content
            )
            assignee = assignee_match.group(1).strip() if assignee_match else None

            # Section
            section_match = re.search(
                r"\*\*Section\*\*:\s*(.+?)(?:\n|$)", content
            )
            section = section_match.group(1).strip() if section_match else None

            # Custom fields
            custom_fields = re.findall(
                r"- \*\*(.+?)\*\*: (.+?)(?:\n|$)", content
            )

            context = self._detect_context(content, title)
            tags = self._generate_tags(
                project_name, due_date, content, title, assignee
            )

            return {
                "path": file_path,
                "filename": file_path.name,
                "title": title,
                "project": project_name,
                "content": content,
                "due_date": due_date,
                "assignee": assignee,
                "section": section,
                "custom_fields": custom_fields,
                "context": context,
                "tags": tags,
            }
        except Exception as exc:
            logger.warning("Error parsing %s: %s", file_path, exc)
            return None

    def _detect_context(self, content: str, title: str) -> str:  # noqa: ARG002
        """Return a coarse content category string."""
        lower = content.lower()
        if any(w in lower for w in ("client", "klient", "kundin", "kundencase")):
            return "client"
        if any(w in lower for w in ("methode", "technique", "prozess", "schritt")):
            return "method"
        if any(w in lower for w in ("learn", "lernen", "study", "research", "forschung")):
            return "learning"
        if any(w in lower for w in ("template", "vorlage", "checklist", "checkliste")):
            return "template"
        if any(w in lower for w in ("tool", "resource", "material", "referenz")):
            return "reference"
        return "general"

    def _generate_tags(
        self,
        project_name: str,
        due_date: Optional[str],
        content: str,
        title: str,  # noqa: ARG002
        assignee: Optional[str],  # noqa: ARG002
    ) -> List[str]:
        """Generate smart tags based on project membership and due date."""
        tags: List[str] = []

        if project_name in _NEXT_PROJECTS:
            tags.append("#active")

        if due_date:
            try:
                due = datetime.strptime(due_date, "%Y-%m-%d")
                days = (due - datetime.now()).days
                if 0 <= days <= 7:
                    tags.append("#priority")
                elif days < 0:
                    tags.append("#overdue")
            except ValueError:
                pass

        if any(c in project_name for c in _CLIENT_PROJECTS):
            tags.append("#client")
        if any(m in project_name for m in _METHOD_PROJECTS):
            tags.append("#method")
        if any(lp in project_name for lp in _LEARNING_PROJECTS):
            tags.append("#learning")

        context = self._detect_context(content, "")
        if context != "general":
            tags.append(f"#{context}")

        if "[Outdated]" in project_name or "Archive" in project_name:
            tags.append("#archive")

        return list(set(tags))
