"""Shared pytest fixtures for the Asana-to-Obsidian test suite."""

import json
import tempfile
from pathlib import Path
from typing import Any, Dict, Generator

import pytest


# ---------------------------------------------------------------------------
# Vault fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """Return an empty temporary directory suitable as a vault root."""
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def tmp_vault_with_files(tmp_vault: Path) -> Path:
    """Return a vault with a minimal project folder and task files."""
    project = tmp_vault / "Clients"
    project.mkdir()

    (project / "INDEX.md").write_text("# Clients - Task Index\n", encoding="utf-8")
    (project / "Alice Müller.md").write_text(
        "# Alice Müller\n\n"
        "⏳ **Pending** • 📅 2024-06-15 • 👤 Coach\n\n"
        "---\n\n"
        "## Metadata\n\n"
        "### Organization\n\n"
        "- **Project**: Clients\n"
        "- **Section**: Einzelpersonen\n",
        encoding="utf-8",
    )
    (project / "Bob Schneider.md").write_text(
        "# Bob Schneider\n\n"
        "✅ **Done**\n\n"
        "---\n\n"
        "## Metadata\n\n"
        "### Organization\n\n"
        "- **Project**: Clients\n"
        "- **Section**: Einzelpersonen\n",
        encoding="utf-8",
    )
    return tmp_vault


# ---------------------------------------------------------------------------
# State file fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    """Return a path to a pre-written valid state JSON file."""
    data: Dict[str, Any] = {
        "exported_tasks": {
            "task_001": {
                "file": "/vault/Clients/Alice Müller.md",
                "exported_at": "2024-01-01T00:00:00",
            }
        },
        "downloaded_attachments": {
            "att_001": "attachments/photo.png",
        },
        "last_run": None,
        "last_sync": "2024-01-01T00:00:00",
    }
    path = tmp_path / ".asana_export_state.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Minimal Asana task dict
# ---------------------------------------------------------------------------


def make_task(
    *,
    gid: str = "1",
    name: str = "Test Task",
    completed: bool = False,
    due_on: str = "2024-06-15",
    assignee_name: str = "Coach",
    project_name: str = "Clients",
    section_name: str = "Einzelpersonen",
    tags: list = None,
    notes: str = "",
    subtasks: int = 0,
) -> Dict[str, Any]:
    """Return a minimal Asana task dict suitable for tests."""
    return {
        "gid": gid,
        "name": name,
        "completed": completed,
        "completed_at": None,
        "due_on": due_on,
        "due_at": None,
        "start_on": None,
        "start_at": None,
        "created_at": "2024-01-01T00:00:00.000Z",
        "modified_at": "2024-01-15T00:00:00.000Z",
        "notes": notes,
        "html_notes": None,
        "num_subtasks": subtasks,
        "num_attachments": 0,
        "assignee": {"name": assignee_name, "email": "coach@example.com"},
        "assignee_status": "today",
        "created_by": {"name": "Admin"},
        "completed_by": None,
        "followers": [],
        "tags": [{"name": t} for t in (tags or [])],
        "projects": [{"gid": "proj_1", "name": project_name}],
        "memberships": [
            {
                "project": {"gid": "proj_1", "name": project_name},
                "section": {"gid": "sec_1", "name": section_name},
            }
        ],
        "parent": None,
        "custom_fields": [],
        "attachments": [],
        "permalink_url": f"https://app.asana.com/0/proj_1/{gid}",
        "resource_type": "task",
        "resource_subtype": "default_task",
        "approval_status": None,
    }
