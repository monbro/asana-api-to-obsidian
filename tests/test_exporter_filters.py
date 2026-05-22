"""Tests for completed-task filtering and export finalization in AsanaExporter."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.config import ExporterSettings
from src.export.exporter import AsanaExporter


def _make_task(completed: bool, completed_at: Optional[str]) -> dict:
    return {
        "completed": completed,
        "completed_at": completed_at,
    }


def test_include_completed_flag_allows_completed(tmp_path: Path) -> None:
    settings = ExporterSettings(
        token="test",
        vault_path=tmp_path,
        include_completed=True,
    )
    exporter = AsanaExporter(settings)
    task = _make_task(True, None)
    assert exporter._should_include_completed(task)


def test_completed_within_days_allows_recent(tmp_path: Path) -> None:
    settings = ExporterSettings(
        token="test",
        vault_path=tmp_path,
        completed_within_days=7,
    )
    exporter = AsanaExporter(settings)
    recent = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    task = _make_task(True, recent)
    assert exporter._should_include_completed(task)


def test_completed_within_days_blocks_old(tmp_path: Path) -> None:
    settings = ExporterSettings(
        token="test",
        vault_path=tmp_path,
        completed_within_days=7,
    )
    exporter = AsanaExporter(settings)
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    task = _make_task(True, old)
    assert not exporter._should_include_completed(task)


def test_finalize_export_logs_completion_duration(
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    settings = ExporterSettings(token="test", vault_path=tmp_path)
    exporter = AsanaExporter(settings)
    exporter._run_started_at = datetime.now(timezone.utc) - timedelta(seconds=75)

    monkeypatch.setattr(exporter, "_update_state_metadata", lambda: None)
    monkeypatch.setattr(exporter, "_write_summary_json", lambda: None)
    monkeypatch.setattr(exporter, "_log_diff_report", lambda: None)

    with caplog.at_level("INFO"):
        exporter._finalize_export(2)

    assert "Export complete! Exported 2 projects in" in caplog.text
