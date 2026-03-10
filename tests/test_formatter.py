"""Tests for src.export.formatter.MarkdownFormatter."""

from pathlib import Path

import pytest

from src.export.formatter import MarkdownFormatter
from tests.conftest import make_task


@pytest.fixture
def fmt() -> MarkdownFormatter:
    return MarkdownFormatter()


class TestFormatTaskMarkdown:
    def test_h1_title(self, fmt: MarkdownFormatter) -> None:
        task = make_task(name="My Task")
        md = fmt.format_task_markdown(task, "Clients")
        assert md.startswith("# My Task")

    def test_pending_status_icon(self, fmt: MarkdownFormatter) -> None:
        task = make_task(completed=False)
        md = fmt.format_task_markdown(task, "Clients")
        assert "⏳" in md
        assert "Pending" in md

    def test_completed_status_icon(self, fmt: MarkdownFormatter) -> None:
        task = make_task(completed=True)
        md = fmt.format_task_markdown(task, "Clients")
        assert "✅" in md
        assert "Done" in md

    def test_due_date_in_quick_info(self, fmt: MarkdownFormatter) -> None:
        task = make_task(due_on="2024-06-15")
        md = fmt.format_task_markdown(task, "Clients")
        assert "2024-06-15" in md

    def test_assignee_in_quick_info(self, fmt: MarkdownFormatter) -> None:
        task = make_task(assignee_name="Alice")
        md = fmt.format_task_markdown(task, "Clients")
        assert "Alice" in md

    def test_no_attachments_section_when_empty(self, fmt: MarkdownFormatter) -> None:
        task = make_task()
        md = fmt.format_task_markdown(task, "Clients", downloaded_attachments=[])
        assert "## Attachments" not in md

    def test_attachments_section_present(self, fmt: MarkdownFormatter) -> None:
        task = make_task()
        md = fmt.format_task_markdown(
            task, "Clients", downloaded_attachments=[{"name": "img.png", "path": "attachments/img.png"}]
        )
        assert "## Attachments" in md
        assert "img.png" in md

    def test_notes_section(self, fmt: MarkdownFormatter) -> None:
        task = make_task(notes="Some coaching notes.")
        md = fmt.format_task_markdown(task, "Clients")
        assert "Some coaching notes." in md

    def test_no_subtasks_section_when_zero(self, fmt: MarkdownFormatter) -> None:
        task = make_task(subtasks=0)
        md = fmt.format_task_markdown(task, "Clients", subtasks=[])
        assert "## 📋 Subtasks" not in md

    def test_subtask_present(self, fmt: MarkdownFormatter) -> None:
        task = make_task(subtasks=1)
        subtask = make_task(gid="2", name="Sub Task")
        md = fmt.format_task_markdown(task, "Clients", subtasks=[subtask])
        assert "Sub Task" in md

    def test_tags_in_organization(self, fmt: MarkdownFormatter) -> None:
        task = make_task(tags=["coaching", "priority"])
        md = fmt.format_task_markdown(task, "Clients")
        assert "#coaching" in md
        assert "#priority" in md


class TestFormatSubtaskMarkdown:
    def test_checkbox_pending(self, fmt: MarkdownFormatter) -> None:
        subtask = make_task(completed=False, name="Do it")
        lines = fmt.format_subtask_markdown(subtask)
        md = "\n".join(lines)
        assert "⏳" in md
        assert "Do it" in md

    def test_checkbox_completed(self, fmt: MarkdownFormatter) -> None:
        subtask = make_task(completed=True, name="Done it")
        lines = fmt.format_subtask_markdown(subtask)
        md = "\n".join(lines)
        assert "✅" in md

    def test_markdown_headers_present(self, fmt: MarkdownFormatter) -> None:
        subtask = make_task(name="Test Task")
        lines = fmt.format_subtask_markdown(subtask)
        md = "\n".join(lines)
        assert "###" in md
        assert "Test Task" in md

    def test_nested_subtasks_appear(self, fmt: MarkdownFormatter) -> None:
        subtask = make_task(name="Parent Sub")
        nested = [make_task(gid="99", name="Grandchild")]
        lines = fmt.format_subtask_markdown(subtask, nested_subtasks=nested)
        md = "\n".join(lines)
        assert "Grandchild" in md


class TestFormatReferenceFile:
    def test_reference_link_to_primary(self, fmt: MarkdownFormatter) -> None:
        task = make_task(name="Shared Task", gid="T1")
        ref = fmt.format_reference_file(task, "Project B", "Project A")
        assert "Project A" in ref
        assert "reference" in ref

    def test_reference_pending_status(self, fmt: MarkdownFormatter) -> None:
        task = make_task(completed=False)
        ref = fmt.format_reference_file(task, "B", "A")
        assert "Pending" in ref

    def test_reference_completed_status(self, fmt: MarkdownFormatter) -> None:
        task = make_task(completed=True)
        ref = fmt.format_reference_file(task, "B", "A")
        assert "Completed" in ref


class TestFormatProjectIndex:
    def test_pending_task_count(self, fmt: MarkdownFormatter) -> None:
        tasks = [make_task(gid=str(i), name=f"Task {i}") for i in range(5)]
        idx = fmt.format_project_index("Clients", tasks, [])
        assert "5" in idx

    def test_completed_tasks_excluded(self, fmt: MarkdownFormatter) -> None:
        tasks = [
            make_task(gid="1", name="Pending"),
            make_task(gid="2", name="Done", completed=True),
        ]
        idx = fmt.format_project_index("Clients", tasks, [])
        assert "Done" not in idx
        assert "Pending" in idx
