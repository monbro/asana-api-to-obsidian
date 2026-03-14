"""Tests for client file reorganization in src.vault.enhancer.VaultEnhancer."""

from pathlib import Path

from src.vault.enhancer import VaultEnhancer


def _write_md(path: Path, title: str, pending_line: str, section: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                pending_line,
                "",
                "---",
                "",
                "## Metadata",
                "",
                "### Organization",
                "",
                "- **Project**: Clients",
                f"- **Section**: {section}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_reorganize_client_files_moves_generic_files(tmp_vault: Path) -> None:
    clients = tmp_vault / "Clients"
    clients.mkdir()

    # Non-generic file acts as canonical client name.
    _write_md(
        clients / "Sabine Hannakampf.md",
        "Sabine Hannakampf",
        "⏳ **Pending** • 📍 Einzelpersonen",
        "Einzelpersonen",
    )

    _write_md(
        clients / "Agenda_1.md",
        "Agenda",
        "⏳ **Pending** • 📍 Sabine Hanakampf (Lektorin) 15.05",
        "Sabine Hanakampf",
    )
    _write_md(
        clients / "Sessions_1.md",
        "Sessions",
        "⏳ **Pending** • 📍 Sabine Hannakampf",
        "Sabine Hannakampf",
    )
    _write_md(
        clients / "Workspace_1.md",
        "Workspace",
        "⏳ **Pending** • 📍 KIZ: Sabine Hannakampf 2024",
        "Sabine Hannakampf",
    )

    # Should remain untouched because no client hint is present.
    (clients / "Notes.md").write_text("# Notes\n\nGeneral text only.\n", encoding="utf-8")

    enhancer = VaultEnhancer(tmp_vault)
    enhancer.reorganize_client_files()

    sabine_dir = clients / "Sabine Hannakampf"
    assert sabine_dir.exists()
    assert (sabine_dir / "Agenda_1.md").exists()
    assert (sabine_dir / "Sessions_1.md").exists()
    assert (sabine_dir / "Workspace_1.md").exists()

    # The canonical profile file is not generic and should stay where it is.
    assert (clients / "Sabine Hannakampf.md").exists()

    # Unmatched generic file remains in root Clients folder.
    assert (clients / "Notes.md").exists()

    index = (sabine_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "[[Agenda_1|Agenda_1.md]]" in index
    assert "[[Sessions_1|Sessions_1.md]]" in index
    assert "[[Workspace_1|Workspace_1.md]]" in index
