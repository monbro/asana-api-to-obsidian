"""Tests for src.export.state.ExportState."""

import json
from pathlib import Path

import pytest

from src.export.state import ExportState


class TestExportStateDefaults:
    def test_fresh_vault_returns_default_schema(self, tmp_path: Path) -> None:
        """No state file → all keys initialise to empty defaults."""
        state = ExportState(tmp_path)
        assert state.exported_tasks == {}
        assert state.downloaded_attachments == {}

    def test_corrupt_json_falls_back_to_defaults(self, tmp_path: Path) -> None:
        """Corrupt JSON → silently falls back to defaults; no exception raised."""
        (tmp_path / ".asana_export_state.json").write_text("{not valid json}", encoding="utf-8")
        state = ExportState(tmp_path)
        assert state.exported_tasks == {}

    def test_missing_keys_in_old_file_are_filled(self, tmp_path: Path) -> None:
        """Old state files without ``last_sync`` still load correctly."""
        (tmp_path / ".asana_export_state.json").write_text(
            json.dumps({"exported_tasks": {}, "downloaded_attachments": {}}),
            encoding="utf-8",
        )
        state = ExportState(tmp_path)
        # Should not raise; missing keys are filled with defaults
        assert state.exported_tasks == {}


class TestExportStateRoundTrip:
    def test_save_and_reload(self, tmp_path: Path) -> None:
        """mark_task_exported → save → reload → is_task_exported returns True."""
        state = ExportState(tmp_path)
        state.mark_task_exported("task_abc", "/vault/file.md")
        state.save()

        reloaded = ExportState(tmp_path)
        assert reloaded.is_task_exported("task_abc")

    def test_unknown_task_not_exported(self, tmp_path: Path) -> None:
        state = ExportState(tmp_path)
        assert not state.is_task_exported("nonexistent_task")

    def test_update_last_run_sets_timestamp(self, tmp_path: Path) -> None:
        state = ExportState(tmp_path)
        assert state._data["last_run"] is None
        state.update_last_run()
        assert state._data["last_run"] is not None


class TestExportStateAttachments:
    def test_mark_and_retrieve_attachment(self, tmp_path: Path) -> None:
        state = ExportState(tmp_path)
        state.mark_attachment_downloaded("att_xyz", "attachments/photo.png")
        assert state.is_attachment_downloaded("att_xyz")
        assert state.get_attachment_path("att_xyz") == "attachments/photo.png"

    def test_unknown_attachment_not_downloaded(self, tmp_path: Path) -> None:
        state = ExportState(tmp_path)
        assert not state.is_attachment_downloaded("att_xyz")
        assert state.get_attachment_path("att_xyz") is None


class TestExportStateFromFixture:
    def test_loads_pre_written_state(self, state_file: Path) -> None:  # uses conftest fixture
        state = ExportState(state_file.parent)
        assert state.is_task_exported("task_001")
        assert state.get_attachment_path("att_001") == "attachments/photo.png"
