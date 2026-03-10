#!/usr/bin/env python3
"""
Vault enhancement entry point — delegates to src.vault.enhancer.VaultEnhancer.

Usage::

    python3 enhance_vault.py
    python3 enhance_vault.py --vault ./obsidian-asana-import
    python3 enhance_vault.py --vault ./obsidian-asana-import --category smart_tagging
    python3 enhance_vault.py --debug
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from src.vault.enhancer import VaultEnhancer
from src.utils.logging_config import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply post-export enhancements to an Obsidian vault.",
    )
    parser.add_argument(
        "--vault",
        default=os.getenv(
            "VAULT_PATH",
            "./obsidian-asana-import",
        ),
        help="Path to the Obsidian vault folder (default: ./obsidian-asana-import)",
    )
    parser.add_argument(
        "--category",
        choices=[
            "smart_tagging",
            "relationship_graph",
            "project_navigation",
            "zettelkasten",
            "coaching_methods",
            "client_hub",
            "client_outcomes",
            "client_templates",
            "personal_dashboard",
            "search_discovery",
        ],
        help="Run a single category instead of all. Omit to run everything.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug-level logging.",
    )
    args = parser.parse_args()

    configure_logging(logging.DEBUG if args.debug else logging.INFO)

    vault_path = Path(args.vault)
    if not vault_path.exists():
        sys.exit(f"Vault path does not exist: {vault_path}")

    enhancer = VaultEnhancer(vault_path)
    enhancer.load()

    category_map = {
        "smart_tagging": enhancer.implement_smart_tagging,
        "relationship_graph": enhancer.implement_relationship_graph,
        "project_navigation": enhancer.improve_project_navigation,
        "zettelkasten": enhancer.implement_zettelkasten,
        "coaching_methods": enhancer.create_coaching_methods_book,
        "client_hub": enhancer.create_client_hub,
        "client_outcomes": enhancer.implement_client_outcomes,
        "client_templates": enhancer.create_client_templates,
        "personal_dashboard": enhancer.create_personal_dashboard,
        "search_discovery": enhancer.create_search_discovery_tools,
    }

    if args.category:
        category_map[args.category]()
    else:
        enhancer.run_all()


if __name__ == "__main__":
    main()
