"""Tests for src.vault.scanner.VaultScanner."""

from pathlib import Path
from typing import List

import pytest

from src.vault.scanner import VaultScanner


def _write_task(folder: Path, filename: str, content: str) -> Path:
    path = folder / filename
    path.write_text(content, encoding="utf-8")
    return path


class TestVaultScannerFindsFiles:
    def test_finds_markdown_files(self, tmp_vault_with_files: Path) -> None:
        scanner = VaultScanner(tmp_vault_with_files)
        tasks = scanner.scan_vault()
        names = [t["filename"] for t in tasks]
        assert "Alice Müller.md" in names
        assert "Bob Schneider.md" in names

    def test_skips_index_and_readme(self, tmp_vault_with_files: Path) -> None:
        scanner = VaultScanner(tmp_vault_with_files)
        tasks = scanner.scan_vault()
        names = [t["filename"] for t in tasks]
        assert "INDEX.md" not in names
        assert "README.md" not in names

    def test_skips_obsidian_hidden_dir(self, tmp_vault: Path) -> None:
        """Files inside .obsidian/ must be ignored."""
        hidden = tmp_vault / ".obsidian"
        hidden.mkdir()
        (hidden / "config.md").write_text("# Internal", encoding="utf-8")
        scanner = VaultScanner(tmp_vault)
        tasks = scanner.scan_vault()
        assert all(".obsidian" not in t["filename"] for t in tasks)


class TestVaultScannerParsesMetadata:
    def test_extracts_title(self, tmp_vault: Path) -> None:
        project = tmp_vault / "TestProject"
        project.mkdir()
        _write_task(project, "My Task.md", "# My Task\n\nSome content.\n")
        scanner = VaultScanner(tmp_vault)
        tasks = scanner.scan_vault()
        assert any(t["title"] == "My Task" for t in tasks)

    def test_extracts_due_date(self, tmp_vault: Path) -> None:
        project = tmp_vault / "TestProject"
        project.mkdir()
        _write_task(
            project,
            "Task With Due.md",
            "# Task With Due\n\n"
            "## Metadata\n\n"
            "### Dates\n\n"
            "| Field | Value |\n"
            "|-------|-------|\n"
            "| Due Date | 2024-06-15 |\n",
        )
        scanner = VaultScanner(tmp_vault)
        tasks = scanner.scan_vault()
        task = next((t for t in tasks if t["title"] == "Task With Due"), None)
        assert task is not None
        assert task["due_date"] == "2024-06-15"

    def test_extracts_assignee(self, tmp_vault: Path) -> None:
        project = tmp_vault / "TestProject"
        project.mkdir()
        _write_task(
            project,
            "Assigned Task.md",
            "# Assigned Task\n\n"
            "## Metadata\n\n"
            "### People\n\n"
            "- **Assigned to**: Alice\n",
        )
        scanner = VaultScanner(tmp_vault)
        tasks = scanner.scan_vault()
        task = next((t for t in tasks if t["title"] == "Assigned Task"), None)
        assert task is not None
        assert task["assignee"] == "Alice"

    def test_extracts_section(self, tmp_vault: Path) -> None:
        project = tmp_vault / "TestProject"
        project.mkdir()
        _write_task(
            project,
            "Sectioned Task.md",
            "# Sectioned Task\n\n## Metadata\n\n### Organization\n\n- **Section**: My Section\n",
        )
        scanner = VaultScanner(tmp_vault)
        tasks = scanner.scan_vault()
        task = next((t for t in tasks if t["title"] == "Sectioned Task"), None)
        assert task is not None
        assert task["section"] == "My Section"


class TestVaultScannerByProject:
    def test_groups_by_project(self, tmp_vault_with_files: Path) -> None:
        scanner = VaultScanner(tmp_vault_with_files)
        projects = scanner.scan_vault_by_project()
        assert "Clients" in projects
        assert len(projects["Clients"]) >= 1

    def test_project_key_matches_folder_name(self, tmp_vault: Path) -> None:
        (tmp_vault / "MyProject").mkdir()
        _write_task(tmp_vault / "MyProject", "Task.md", "# Task\n")
        scanner = VaultScanner(tmp_vault)
        projects = scanner.scan_vault_by_project()
        assert "MyProject" in projects


class TestVaultScannerUnreadableFile:
    def test_handles_unreadable_file_gracefully(self, tmp_vault: Path) -> None:
        """An unreadable file must not crash the scan; it should be skipped."""
        project = tmp_vault / "TestProject"
        project.mkdir()
        bad_file = project / "bad.md"
        bad_file.write_bytes(b"\xff\xfe malformed utf")  # Not valid UTF-8
        # Should not raise
        scanner = VaultScanner(tmp_vault)
        tasks = scanner.scan_vault()
        # bad.md is either present with empty content or skipped; no crash
        assert isinstance(tasks, list)
