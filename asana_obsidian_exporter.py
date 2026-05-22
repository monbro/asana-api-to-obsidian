#!/usr/bin/env python3
"""
Asana to Obsidian Vault Exporter — entry point.

This file is a thin shim that parses CLI arguments and delegates all logic
to ``src.export.exporter.AsanaExporter``.

Usage::

    python3 asana_obsidian_exporter.py --vault ./my-vault

    # Or with an explicit token:
    python3 asana_obsidian_exporter.py --vault ./my-vault --token 1/abc...

    # Enable debug logging:
    python3 asana_obsidian_exporter.py --vault ./my-vault --debug

Environment variables:
    ASANA_TOKEN        Personal Access Token (alternative to --token flag).
    OBSIDIAN_VAULT_PATH   Default vault path (alternative to --vault flag).
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from src.config import ExporterSettings
from src.export.exporter import AsanaExporter
from src.utils.logging_config import configure_logging


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Export Asana workspace to an Obsidian vault."
    )
    parser.add_argument(
        "--token",
        help="Asana Personal Access Token (or set ASANA_TOKEN env var).",
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("OBSIDIAN_VAULT_PATH"),
        required=not os.getenv("OBSIDIAN_VAULT_PATH"),
        help="Path to the Obsidian vault directory (created if it does not exist).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "Export only the project whose name matches this value "
            "(case-insensitive). When omitted, all projects are exported."
        ),
    )
    parser.add_argument(
        "--conflict-policy",
        choices=["overwrite", "skip", "copy"],
        default="overwrite",
        help=(
            "When a remote task changed and the local file was edited: "
            "overwrite (default), skip, or copy (write a conflict copy)."
        ),
    )
    args = parser.parse_args()

    level = logging.DEBUG if args.debug else logging.INFO
    configure_logging(level)

    token = args.token or os.getenv("ASANA_TOKEN")
    if not token:
        sys.exit(
            "Asana token required. Set the ASANA_TOKEN environment variable "
            "or pass --token."
        )

    settings = ExporterSettings(
        token=token,
        vault_path=Path(args.vault),
        debug=args.debug,
        project_filter=args.project,
        conflict_policy=args.conflict_policy,
    )
    exporter = AsanaExporter(settings)
    sys.exit(0 if exporter.export_workspace() else 1)


if __name__ == "__main__":
    main()
