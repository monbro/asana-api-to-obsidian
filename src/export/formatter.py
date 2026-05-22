"""
Markdown formatting for Asana tasks and project artefacts.

``MarkdownFormatter`` is **stateless** — it accepts plain Python dicts and
returns strings.  It never calls the API, reads files, or writes to disk.
All data (subtasks, stories, downloaded attachment paths) must be fetched
by the caller and passed in.

This makes the formatter completely testable without any mocks.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.utils.files import sanitize_filename

logger = logging.getLogger(__name__)


class MarkdownFormatter:
    """Convert Asana task dicts into Obsidian-compatible markdown strings.

    All methods are pure: same inputs always produce the same output.
    """

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def format_task_markdown(
        self,
        task: Dict[str, Any],
        project_name: str,
        downloaded_attachments: Optional[List[Dict[str, str]]] = None,
        subtasks: Optional[List[Dict]] = None,
        nested_subtasks: Optional[Dict[str, List[Dict]]] = None,
        stories: Optional[List[Dict]] = None,
        is_reference: bool = False,
        subtask_attachments: Optional[Dict[str, List[Dict[str, str]]]] = None,
    ) -> str:
        """Format a full task as Obsidian markdown.

        Args:
            task:                    Full Asana task dict.
            project_name:            Human-readable project name.
            downloaded_attachments:  List of ``{"name": ..., "path": ...}``
                                     dicts for already-downloaded attachments.
            subtasks:                Pre-fetched direct subtasks (level 1).
            nested_subtasks:         Mapping of subtask GID →
                                     pre-fetched sub-subtasks (level 2).
            stories:                 Pre-fetched story list for this task.
            is_reference:            True when generating a reference stub.
            subtask_attachments:     Mapping of subtask GID →
                                     downloaded attachment dicts for that subtask.

        Returns:
            Complete markdown string ready to write to disk.
        """
        downloaded_attachments = downloaded_attachments or []
        subtasks = subtasks or []
        nested_subtasks = nested_subtasks or {}
        stories = stories or []
        subtask_attachments = subtask_attachments or {}

        title = task.get("name", "Untitled")
        description = task.get("description", "")
        notes = task.get("notes", "")
        completed = task.get("completed", False)
        num_subtasks = task.get("num_subtasks", 0)
        task_gid = task.get("gid", "")
        html_notes = task.get("html_notes")

        lines: List[str] = []

        self._append_title(lines, title)
        self._append_quick_info(lines, task)
        lines.append("---\n")

        if is_reference:
            self._append_reference_note(lines)

        self._append_description_notes(lines, description, notes, html_notes)
        self._append_metadata(lines, task, project_name)
        self._append_raw_json(lines, task)
        self._append_custom_fields(lines, task.get("custom_fields", []))
        self._append_attachments(lines, downloaded_attachments)
        self._append_subtasks(
            lines,
            num_subtasks,
            subtasks,
            nested_subtasks,
            subtask_attachments,
        )
        self._append_stories(lines, stories)

        return "\n".join(lines)

    def format_subtask_markdown(
        self,
        subtask: Dict[str, Any],
        nested_subtasks: Optional[List[Dict]] = None,
        level: int = 3,
        downloaded_attachments: Optional[List[Dict[str, str]]] = None,
        nested_subtask_attachments: Optional[Dict[str, List[Dict[str, str]]]] = None,
    ) -> List[str]:
        """Format one subtask as readable Markdown with full visibility.

        Args:
            subtask:                      Subtask dict from Asana API.
            nested_subtasks:              Pre-fetched sub-subtasks (level 2+).
                                          No recursive API call is made here.
            level:                        Header level (3 = ###, 4 = ####, etc.).
            downloaded_attachments:       Downloaded attachment dicts for this subtask.
            nested_subtask_attachments:   Mapping of GID → attachment dicts for all
                                          subtasks, passed down to child calls.

        Returns:
            List of markdown lines.
        """
        nested_subtasks = nested_subtasks or []
        downloaded_attachments = downloaded_attachments or []
        nested_subtask_attachments = nested_subtask_attachments or {}
        lines: List[str] = []

        title = subtask.get("name", "Untitled")
        completed = subtask.get("completed", False)
        completed_at = subtask.get("completed_at")
        completed_by = subtask.get("completed_by") or {}
        description = subtask.get("description", "")
        notes = subtask.get("notes", "")
        due_on = subtask.get("due_on")
        due_at = subtask.get("due_at")
        start_on = subtask.get("start_on")
        start_at = subtask.get("start_at")
        assignee = subtask.get("assignee") or {}
        assignee_status = subtask.get("assignee_status")
        created_at = subtask.get("created_at")
        modified_at = subtask.get("modified_at")
        resource_type = subtask.get("resource_type")
        resource_subtype = subtask.get("resource_subtype")
        approval_status = subtask.get("approval_status")
        permalink = subtask.get("permalink_url", "")
        task_gid = subtask.get("gid", "")
        num_subtasks = subtask.get("num_subtasks", 0)

        checkbox = "✅" if completed else "⏳"
        header_prefix = "#" * level

        lines.append(f"{header_prefix} {checkbox} {title}")
        lines.append("")

        info_line = self._build_subtask_info_bar(
            due_on,
            due_at,
            start_on,
            start_at,
            assignee,
            assignee_status,
            num_subtasks,
        )
        if info_line:
            lines.append(info_line)
            lines.append("")

        # Description/Notes
        if description:
            lines.append(f"> {description}")
            lines.append("")
        if notes and notes != description:
            lines.append(f"> {notes}")
            lines.append("")

        self._append_subtask_attachments(lines, header_prefix, downloaded_attachments)
        self._append_subtask_metadata(
            lines,
            created_at,
            modified_at,
            completed_at,
            completed_by,
            approval_status,
            resource_subtype,
            task_gid,
            permalink,
        )

        self._append_nested_subtasks(
            lines,
            header_prefix,
            nested_subtasks,
            level,
            nested_subtask_attachments,
        )

        return lines

    def format_reference_file(
        self,
        task: Dict[str, Any],
        current_project_name: str,
        primary_project_name: str,
    ) -> str:
        """Generate a cross-project reference stub markdown file.

        Args:
            task:                  Minimal task dict (must have ``"gid"`` and ``"name"``).
            current_project_name:  Project the reference lives in.
            primary_project_name:  Project where the full task file lives.

        Returns:
            Markdown string for the reference file.
        """
        task_id = task.get("gid", "")
        task_name = task.get("name", "Untitled")
        completed = task.get("completed", False)
        assignee = (task.get("assignee") or {}).get("name") or "Unassigned"
        due_on = task.get("due_on") or "No due date"

        primary_folder = sanitize_filename(primary_project_name)
        filename = sanitize_filename(task_name)

        return f"""---
title: {task_name}
status: {'completed' if completed else 'pending'}
project: {current_project_name}
asana_id: {task_id}
type: reference
original_project: {primary_project_name}
---

# {task_name}

> **This is a reference to a task in another project.**
> **Main file location:** [[../{primary_folder}/{filename}|{primary_project_name}]]

## Quick Info
- **Status**: {'✅ Completed' if completed else '⏳ Pending'}
- **Assigned to**: {assignee}
- **Due**: {due_on}

---

**To edit this task, open the main file in {primary_project_name} project.**
"""

    def format_project_index(
        self,
        project_name: str,
        tasks: List[Dict[str, Any]],
        sections: List[Dict[str, Any]],
    ) -> str:
        """Generate INDEX.md content for a project.

        Only pending root tasks (no parent, not completed) are included.
        Tasks are grouped by the section order from *sections*.

        Args:
            project_name: Display name of the project.
            tasks:        All tasks in the project.
            sections:     Ordered section list from the Asana API.

        Returns:
            Markdown string for ``INDEX.md``.
        """
        section_map: Dict[str, list] = {}
        unassigned: list = []

        for task in tasks:
            if task.get("parent") or task.get("completed"):
                continue
            task_name = task.get("name", "Untitled")
            task_id = task.get("gid", "")
            memberships = task.get("memberships") or []
            section_name = None
            if memberships:
                section_info = (memberships[0].get("section") or {})
                section_name = section_info.get("name")

            if section_name:
                section_map.setdefault(section_name, []).append((task_name, task_id))
            else:
                unassigned.append((task_name, task_id))

        for key in section_map:
            section_map[key].sort(key=lambda x: x[0])
        unassigned.sort(key=lambda x: x[0])

        total_pending = sum(len(v) for v in section_map.values()) + len(unassigned)

        lines = [
            f"# {project_name} - Task Index",
            "",
            f"📊 **Pending Tasks**: {total_pending} ⏳",
            "",
        ]

        for section in sections:
            sec_name = section.get("name")
            if sec_name and section_map.get(sec_name):
                lines.append(f"## 📑 {sec_name}")
                lines.append("")
                for task_name, _ in section_map[sec_name]:
                    fname = sanitize_filename(task_name)
                    lines.append(f"- [ ] [[{fname}]]")
                lines.append("")

        if unassigned:
            lines.append("## 📌 Unassigned")
            lines.append("")
            for task_name, _ in unassigned:
                fname = sanitize_filename(task_name)
                lines.append(f"- [ ] [[{fname}]]")
            lines.append("")

        return "\n".join(lines)

    def format_project_readme(self, project: Dict[str, Any]) -> str:
        """Generate README.md content for a project folder.

        Args:
            project: Project dict (must have ``"name"``).

        Returns:
            Markdown string for ``README.md``.
        """
        name = project.get("name", "Untitled")
        description = project.get("description", "") or ""
        created = (project.get("created_at") or "")[:10]
        modified = (project.get("modified_at") or "")[:10]

        content = f"""---
title: {name}
type: project
created: {created}
modified: {modified}
---

# {name}

"""
        if description:
            content += f"{description}\n\n"
        content += "📋 See **INDEX.md** for a complete task overview organized by status.\n\n"
        return content

    # ------------------------------------------------------------------
    # Private helper methods
    # ------------------------------------------------------------------

    def _format_quick_info_bar(self, task: Dict[str, Any]) -> str:
        """Return the one-line quick info bar (status, due, assignee, section)."""
        completed = task.get("completed", False)
        due_on = task.get("due_on")
        due_at = task.get("due_at")
        assignee = (task.get("assignee") or {}).get("name")
        memberships = task.get("memberships") or []
        section_name = None
        if memberships:
            section_name = ((memberships[0].get("section") or {}).get("name"))

        icon = "✅" if completed else "⏳"
        text = "Done" if completed else "Pending"
        bar = f"{icon} **{text}**"

        if due_on or due_at:
            bar += f" • 📅 {due_on or due_at[:10]}"
        if assignee:
            bar += f" • 👤 {assignee}"
        if section_name:
            bar += f" • 📍 {section_name}"

        return bar

    def _append_title(self, lines: List[str], title: str) -> None:
        lines.append(f"# {title}\n")

    def _append_quick_info(self, lines: List[str], task: Dict[str, Any]) -> None:
        lines.append(self._format_quick_info_bar(task) + "\n")

    def _append_reference_note(self, lines: List[str]) -> None:
        lines.append("ℹ️ **Note**: This is a reference to the main task file.\n")
        lines.append("See the main file for full details and updates.\n\n")

    def _append_description_notes(
        self,
        lines: List[str],
        description: str,
        notes: str,
        html_notes: Optional[str],
    ) -> None:
        if description:
            lines.append("## Description\n")
            lines.append(f"{description}\n")
        if notes:
            lines.append("## Notes\n")
            lines.append(f"{notes}\n")
        if html_notes and html_notes != notes:
            lines.append("<details>")
            lines.append("<summary>Notes (HTML)</summary>\n")
            lines.append("```html")
            lines.append(html_notes)
            lines.append("```")
            lines.append("</details>\n")

    def _append_metadata(
        self,
        lines: List[str],
        task: Dict[str, Any],
        project_name: str,
    ) -> None:
        lines.append("## Metadata\n")
        lines.extend(self._format_dates_section(task))
        lines.extend(self._format_people_section(task))
        lines.extend(self._format_org_section(task, project_name))
        lines.extend(self._format_technical_section(task))

    def _append_raw_json(self, lines: List[str], task: Dict[str, Any]) -> None:
        lines.append("<details>")
        lines.append("<summary>Raw Asana Data (JSON)</summary>\n")
        lines.append("```json")
        lines.append(json.dumps(task, indent=2, ensure_ascii=False, sort_keys=True))
        lines.append("```")
        lines.append("</details>\n")

    def _append_custom_fields(
        self,
        lines: List[str],
        custom_fields: List[Dict[str, Any]],
    ) -> None:
        if custom_fields:
            lines.append("## Custom Fields\n")
            for field in custom_fields:
                field_name = field.get("name", "Unknown")
                field_value = (
                    field.get("text_value")
                    or field.get("number_value")
                    or (field.get("enum_value") or {}).get("name", "")
                )
                if field_value:
                    lines.append(f"- **{field_name}**: {field_value}")
            lines.append("")

    def _append_attachments(
        self,
        lines: List[str],
        downloaded_attachments: List[Dict[str, str]],
    ) -> None:
        if downloaded_attachments:
            lines.append("## Attachments\n")
            for att in downloaded_attachments:
                lines.append(f"![[{att['path']}]]")
            lines.append("")

    def _append_subtasks(
        self,
        lines: List[str],
        num_subtasks: int,
        subtasks: List[Dict],
        nested_subtasks: Dict[str, List[Dict]],
        subtask_attachments: Dict[str, List[Dict[str, str]]],
    ) -> None:
        if num_subtasks > 0 or subtasks:
            lines.append("## 📋 Subtasks\n")
            if subtasks:
                for subtask in subtasks:
                    sub_id = subtask.get("gid", "")
                    sub_nested = nested_subtasks.get(sub_id, [])
                    lines.extend(self.format_subtask_markdown(
                        subtask,
                        sub_nested,
                        level=3,
                        downloaded_attachments=subtask_attachments.get(sub_id, []),
                        nested_subtask_attachments=subtask_attachments,
                    ))
                    lines.append("")
            else:
                lines.append("*No subtasks found.*\n")

    def _append_stories(self, lines: List[str], stories: List[Dict]) -> None:
        if stories:
            lines.append("## Timeline / Comments\n")
            for story in sorted(stories, key=lambda s: s.get("created_at", "")):
                lines.extend(self._format_story(story))

    def _build_subtask_info_bar(
        self,
        due_on: Optional[str],
        due_at: Optional[str],
        start_on: Optional[str],
        start_at: Optional[str],
        assignee: Dict[str, Any],
        assignee_status: Optional[str],
        num_subtasks: int,
    ) -> Optional[str]:
        info_items = []
        if due_on or due_at:
            info_items.append(f"📅 **Due**: {due_on or due_at[:10]}")
        if start_on or start_at:
            info_items.append(f"🟢 **Start**: {start_on or start_at[:10]}")
        if assignee.get("name"):
            info_items.append(f"👤 **Assigned to**: {assignee['name']}")
        if assignee_status:
            info_items.append(f"📊 **Status**: {assignee_status}")
        if num_subtasks > 0:
            info_items.append(f"📌 **Sub-subtasks**: {num_subtasks}")

        if info_items:
            return " | ".join(info_items)
        return None

    def _append_subtask_attachments(
        self,
        lines: List[str],
        header_prefix: str,
        downloaded_attachments: List[Dict[str, str]],
    ) -> None:
        if downloaded_attachments:
            lines.append(f"{header_prefix}# Attachments")
            lines.append("")
            for att in downloaded_attachments:
                lines.append(f"![[{att['path']}]]")
            lines.append("")

    def _append_subtask_metadata(
        self,
        lines: List[str],
        created_at: Optional[str],
        modified_at: Optional[str],
        completed_at: Optional[str],
        completed_by: Dict[str, Any],
        approval_status: Optional[str],
        resource_subtype: Optional[str],
        task_gid: str,
        permalink: str,
    ) -> None:
        metadata_rows = []
        if created_at:
            metadata_rows.append(f"| Created | {created_at[:10]} {created_at[11:19]} |")
        if modified_at:
            metadata_rows.append(f"| Modified | {modified_at[:10]} {modified_at[11:19]} |")
        if completed_at:
            metadata_rows.append(f"| Completed | {completed_at[:10]} {completed_at[11:19]} |")
        if completed_by.get("name"):
            metadata_rows.append(f"| Completed by | {completed_by['name']} |")
        if approval_status:
            metadata_rows.append(f"| Approval Status | {approval_status} |")
        if resource_subtype and resource_subtype != "default_task":
            metadata_rows.append(f"| Task Type | {resource_subtype} |")
        if task_gid:
            metadata_rows.append(f"| Asana ID | `{task_gid}` |")
        if permalink:
            metadata_rows.append(f"| Link | [Open in Asana]({permalink}) |")

        if metadata_rows:
            lines.append("| Field | Value |")
            lines.append("|-------|-------|")
            lines.extend(metadata_rows)
            lines.append("")

    def _append_nested_subtasks(
        self,
        lines: List[str],
        header_prefix: str,
        nested_subtasks: List[Dict],
        level: int,
        nested_subtask_attachments: Dict[str, List[Dict[str, str]]],
    ) -> None:
        if nested_subtasks:
            lines.append(f"{header_prefix}# Sub-subtasks")
            lines.append("")
            for sub in nested_subtasks:
                sub_id = sub.get("gid", "")
                lines.extend(self.format_subtask_markdown(
                    sub,
                    [],
                    level + 1,
                    downloaded_attachments=nested_subtask_attachments.get(sub_id, []),
                    nested_subtask_attachments=nested_subtask_attachments,
                ))
                lines.append("")

    def _format_dates_section(self, task: Dict[str, Any]) -> List[str]:
        """Return lines for the ### Dates metadata sub-section."""
        created_at = task.get("created_at", "")
        modified_at = task.get("modified_at", "")
        start_on = task.get("start_on")
        start_at = task.get("start_at")
        due_on = task.get("due_on")
        due_at = task.get("due_at")
        completed_at = task.get("completed_at", "")

        rows = []
        if created_at:
            rows.append(f"| Created | {created_at[:10]} {created_at[11:19]} |")
        if modified_at:
            rows.append(f"| Modified | {modified_at[:10]} {modified_at[11:19]} |")
        if start_on or start_at:
            rows.append(f"| Start Date | {start_on or start_at[:10]} |")
        if due_on or due_at:
            rows.append(f"| Due Date | {due_on or due_at[:10]} |")
        if completed_at:
            rows.append(f"| Completed | {completed_at[:10]} {completed_at[11:19]} |")

        if not rows:
            return []

        lines = ["### Dates\n", "| Field | Value |", "|-------|-------|"]
        lines.extend(rows)
        lines.append("")
        return lines

    def _format_people_section(self, task: Dict[str, Any]) -> List[str]:
        """Return lines for the ### People metadata sub-section."""
        created_by = (task.get("created_by") or {})
        assignee = (task.get("assignee") or {})
        completed_by = (task.get("completed_by") or {})
        followers = task.get("followers") or []

        items = []
        if created_by.get("name"):
            items.append(f"- **Created by**: {created_by['name']}")
        if assignee.get("name"):
            info = assignee["name"]
            if assignee.get("email"):
                info += f" ({assignee['email']})"
            items.append(f"- **Assigned to**: {info}")
        if completed_by.get("name"):
            info = completed_by["name"]
            if completed_by.get("email"):
                info += f" ({completed_by['email']})"
            items.append(f"- **Completed by**: {info}")
        if followers:
            names = ", ".join(f.get("name", "Unknown") for f in followers if f.get("name"))
            if names:
                items.append(f"- **Followers** ({len(followers)}): {names}")

        if not items:
            return []

        return ["### People\n"] + items + [""]

    def _format_org_section(self, task: Dict[str, Any], project_name: str) -> List[str]:
        """Return lines for the ### Organization metadata sub-section."""
        memberships = task.get("memberships") or []
        section_name = None
        if memberships:
            section_name = ((memberships[0].get("section") or {}).get("name"))

        parent = (task.get("parent") or {})
        projects = task.get("projects") or []
        tags = task.get("tags") or []

        items = [f"- **Project**: {project_name}"]
        if section_name:
            items.append(f"- **Section**: {section_name}")
        if parent.get("name"):
            items.append(f"- **Parent Task**: {parent['name']}")
        if len(projects) > 1:
            others = ", ".join(
                p["name"] for p in projects if p.get("name") and p["name"] != project_name
            )
            if others:
                items.append(f"- **Also in**: {others}")
        if tags:
            tag_str = " ".join(
                f"#{t.get('name', '').replace(' ', '-').lower()}"
                for t in tags
                if t.get("name")
            )
            if tag_str:
                items.append(f"- **Tags**: {tag_str}")

        return ["### Organization\n"] + items + [""]

    def _format_technical_section(self, task: Dict[str, Any]) -> List[str]:
        """Return lines for the ### Technical Information metadata sub-section."""
        items = [f"- **Completed**: {task.get('completed', False)}"]

        for key, label in [
            ("resource_type", "Resource Type"),
            ("resource_subtype", "Task Type"),
            ("assignee_status", "Assignee Status"),
            ("approval_status", "Approval Status"),
        ]:
            val = task.get(key)
            if val and val != "default_task":
                items.append(f"- **{label}**: {val}")

        task_gid = task.get("gid", "")
        if task_gid:
            items.append(f"- **Asana ID**: `{task_gid}`")
        items.append(f"- **Subtasks**: {task.get('num_subtasks', 0)}")
        items.append(f"- **Attachments**: {task.get('num_attachments', 0)}")

        permalink = task.get("permalink_url")
        if permalink:
            items.append(f"- **Link**: [Open in Asana]({permalink})")

        return ["### Technical Information\n"] + items + [""]

    def _format_story(self, story: Dict[str, Any]) -> List[str]:
        """Return lines for a single story (comment or attachment event)."""
        story_type = story.get("type", "unknown")
        created_by = (story.get("created_by") or {})
        created_at = story.get("created_at", "")
        date_str = created_at[:10] if created_at else "Unknown"
        author = created_by.get("name", "Unknown") if created_by else "Unknown"

        lines: List[str] = []
        if story_type == "comment":
            text = story.get("text", "")
            if text:
                lines.append(f"### {date_str} - {author}\n")
                lines.append(f"{text}\n")
        elif story_type == "attachment_added":
            att_name = (story.get("attachment") or {}).get("name", "Attachment")
            lines.append(f"### {date_str} - {author}\n")
            lines.append(f"Added attachment: {att_name}\n")

        return lines
