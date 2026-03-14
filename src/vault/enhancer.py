"""
Vault enhancement: smart tagging, knowledge base, client hub, search tools.

``VaultEnhancer`` merges the functionality of the former ``enhance_vault.py``
(categories 1-3) and ``enhance_vault_advanced.py`` (categories 5B, 6A, 6B)
into one class.

The duplicated ``scan_vault()`` / ``_parse_task()`` logic from both old scripts
is replaced by a single ``VaultScanner`` instance via composition.
"""

import logging
import random
import re
from difflib import SequenceMatcher
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.vault.scanner import VaultScanner
from src.utils.files import sanitize_filename

logger = logging.getLogger(__name__)


_GENERIC_CLIENT_FILE_RE = re.compile(
    r"^(Agenda(?:_\d+)?|Current Agenda(?:_\d+)?|Session(?:s)?(?: Notes| Archive)?(?:_\d+)?|"
    r"Workspace(?:_\d+)?|Notes(?:_\d+)?|Protokoll|Protocoll)\.md$"
)

_CLIENT_NAME_LINE_PATTERNS = (
    re.compile(r"📍\s*(.+)"),
    re.compile(r"- \*\*Section\*\*:\s*(.+)"),
)

_CLIENT_PREFIX_RE = re.compile(r"^(jc|kiz|digicamp)\s*[:\-]\s*", re.IGNORECASE)
_TRAILING_DATE_RE = re.compile(r"\s+(\d{1,2}\.\d{1,2}(?:\.\d{2,4})?|20\d{2})\s*$")

_NON_NAME_TOKENS = {
    "archived",
    "einzelpersonen",
    "gruenderberatung",
    "grunderberatung",
    "gründerberatung",
    "clients",
    "client",
}


class VaultEnhancer:
    """Apply post-export enhancements to an Obsidian vault.

    Usage::

        enhancer = VaultEnhancer(Path("./obsidian-asana-import"))
        enhancer.load()                          # scan vault once
        enhancer.implement_smart_tagging()       # category 1A
        enhancer.implement_relationship_graph()  # category 1B
        ...
        enhancer.run_all()                       # run everything
    """

    def __init__(self, vault_path: Path) -> None:
        self.vault_path = vault_path
        self.scanner = VaultScanner(vault_path)
        self.tasks: List[Dict] = []
        self.projects: Dict[str, List[Dict]] = {}
        self.clients: List[Dict] = []

    def load(self) -> None:
        """Scan the vault and populate ``tasks``, ``projects``, and ``clients``."""
        logger.info("Scanning vault at %s …", self.vault_path)
        self.projects = self.scanner.scan_vault_by_project()
        self.tasks = [t for tasks in self.projects.values() for t in tasks]
        self.clients = [t for t in self.tasks if t["project"] == "Clients"]
        logger.info(
            "Found %d tasks across %d projects.", len(self.tasks), len(self.projects)
        )

    # ------------------------------------------------------------------
    # CATEGORY 1: OBSIDIAN INTEGRATION
    # ------------------------------------------------------------------

    def implement_smart_tagging(self) -> None:
        """1A: Add smart tags to all task files."""
        logger.info("CATEGORY 1A: Smart Tagging")
        updated = 0
        for task in self.tasks:
            if task.get("tags"):
                new_content = self._add_tags_to_file(task["path"], task["tags"])
                if new_content != task["content"]:
                    task["path"].write_text(new_content, encoding="utf-8")
                    updated += 1
        logger.info("Updated %d tasks with smart tags.", updated)

    def implement_relationship_graph(self) -> None:
        """1B: Create relationship links between related items."""
        logger.info("CATEGORY 1B: Relationship Graph")
        links = 0
        for task in self.tasks:
            related = self._find_related_items(task, min_similarity=0.3)
            if related:
                links += self._add_relationship_links(task["path"], related)
        logger.info("Created %d relationship links.", links)

    def improve_project_navigation(self) -> None:
        """1C: Enhance INDEX.md for large projects."""
        logger.info("CATEGORY 1C: Project Navigation")
        improved = 0
        for project_name, tasks in self.projects.items():
            if len(tasks) > 10:
                improved += self._enhance_project_index(project_name, tasks)
        logger.info("Improved %d project indices.", improved)

    # ------------------------------------------------------------------
    # CATEGORY 2: KNOWLEDGE BASE
    # ------------------------------------------------------------------

    def implement_zettelkasten(self) -> None:
        """2A: Create a Zettelkasten hub for '= Resources 4 Me'."""
        logger.info("CATEGORY 2A: Zettelkasten")
        resources = [t for t in self.tasks if t["project"] == "= Resources 4 Me"]
        categories = self._categorize_resources(resources)
        self._create_zettelkasten_hub(categories)
        logger.info("Created Zettelkasten for %d items.", len(resources))

    def create_coaching_methods_book(self) -> None:
        """2B: Build a structured Coaching Methods Handbook file."""
        logger.info("CATEGORY 2B: Coaching Methods Book")
        method_projects = frozenset(
            ["Methoden Koffer", "Systemische Methoden", "@ Thought Tank Business", "@ Thought Tank"]
        )
        methods = [
            t for t in self.tasks
            if any(p in t["project"] for p in method_projects) and "#method" in t.get("tags", [])
        ]
        self._create_methods_book(methods)
        logger.info("Created Methods Book with %d methods.", len(methods))

    # ------------------------------------------------------------------
    # CATEGORY 3: CLIENT HUB
    # ------------------------------------------------------------------

    def create_client_hub(self) -> None:
        """3A: Create _CLIENTS_HUB with profiles and linked resources."""
        logger.info("CATEGORY 3A: Client Hub")
        hub = self.vault_path / "_CLIENTS_HUB"
        hub.mkdir(exist_ok=True)
        self._create_client_hub_index(self.clients, hub)
        created = sum(1 for c in self.clients if self._create_client_profile(c, hub))
        logger.info("Created Client Hub with %d profiles.", created)

    def implement_client_outcomes(self) -> None:
        """3B: Create outcomes tracking template."""
        logger.info("CATEGORY 3B: Client Outcomes")
        self._create_outcomes_tracker()
        logger.info("Created outcomes tracker.")

    # ------------------------------------------------------------------
    # CATEGORY 5B: CLIENT PROJECT TEMPLATES
    # ------------------------------------------------------------------

    def create_client_templates(self) -> None:
        """5B: Create reusable templates for new client projects."""
        logger.info("CATEGORY 5B: Client Templates")
        folder = self.vault_path / "_CLIENT_TEMPLATES"
        folder.mkdir(exist_ok=True)
        self._create_templates_index(folder)
        self._create_welcome_template(folder)
        self._create_first_call_template(folder)
        self._create_coaching_process_template(folder)
        self._create_followup_template(folder)
        self._create_resources_checklist_template(folder)
        logger.info("Created client project templates in _CLIENT_TEMPLATES/.")

    # ------------------------------------------------------------------
    # CATEGORY 6A: PERSONAL DASHBOARD
    # ------------------------------------------------------------------

    def create_personal_dashboard(self) -> None:
        """6A: Generate a personal dashboard markdown file."""
        logger.info("CATEGORY 6A: Personal Dashboard")
        active = sum(1 for t in self.tasks if t["project"] == "_ Next")
        priority = self._count_priority_tasks()
        client_stats = {
            "total_clients": len(self.clients),
            "recently_updated": [c["title"] for c in self.clients[:5]],
        }
        areas: Dict[str, int] = defaultdict(int)
        for name, tasks in self.projects.items():
            if name.startswith("_"):
                area = "System"
            elif name.startswith("="):
                area = "Resources/Knowledge"
            elif name.startswith("@"):
                area = "Thought/Ideas"
            elif any(x in name for x in ("Client", "CRM")):
                area = "Client Work"
            else:
                area = "Active Projects"
            areas[area] += len(tasks)

        total = len(self.tasks)
        active_proj = sum(1 for n, ts in self.projects.items() if ts and not n.startswith("_"))
        workload = {
            "total_tasks": total,
            "active_projects": active_proj,
            "avg_tasks_per_project": total // active_proj if active_proj else 0,
        }

        dashboard_path = self.vault_path / "_PERSONAL_DASHBOARD.md"
        dashboard_path.write_text(
            self._build_dashboard(active, priority, client_stats, dict(areas), workload),
            encoding="utf-8",
        )
        logger.info("Created personal dashboard at _PERSONAL_DASHBOARD.md.")

    # ------------------------------------------------------------------
    # CATEGORY 6B: SEARCH & DISCOVERY
    # ------------------------------------------------------------------

    def create_search_discovery_tools(self) -> None:
        """6B: Create search guide, faceted search, and random discovery files."""
        logger.info("CATEGORY 6B: Search & Discovery")
        self._create_search_index()
        self._create_faceted_search()
        self._create_discovery_suggestions()
        logger.info("Created search & discovery tools.")

    # ------------------------------------------------------------------
    # CATEGORY 7: CLIENT FILE REORGANIZATION
    # ------------------------------------------------------------------

    def reorganize_client_files(self) -> None:
        """7: Move generic client files into per-client folders when matchable.

        The method only processes markdown files directly in ``Clients/`` with
        generic names like ``Agenda_12.md``, ``Sessions_3.md``, ``Workspace.md``.
        Files for which no client can be determined remain untouched.
        """
        logger.info("CATEGORY 7: Client File Reorganization")
        clients_dir = self.vault_path / "Clients"
        if not clients_dir.exists() or not clients_dir.is_dir():
            logger.warning("Clients folder does not exist: %s", clients_dir)
            return

        known_clients = self._build_known_client_aliases(clients_dir)
        moved = 0
        unmatched = 0
        changed_folders: Set[Path] = set()

        for file_path in sorted(clients_dir.glob("*.md")):
            if file_path.name in {"INDEX.md", "README.md"}:
                continue
            if not _GENERIC_CLIENT_FILE_RE.match(file_path.name):
                continue

            content = file_path.read_text(encoding="utf-8")
            target_client = self._resolve_client_name(content, known_clients)
            if not target_client:
                unmatched += 1
                continue

            client_dir = clients_dir / sanitize_filename(target_client)
            client_dir.mkdir(exist_ok=True)
            target_path = self._unique_target_path(client_dir / file_path.name)
            file_path.rename(target_path)
            moved += 1
            changed_folders.add(client_dir)
            logger.debug("Moved %s -> %s", file_path.name, target_path)

        for folder in sorted(changed_folders):
            self._write_client_folder_index(folder)

        logger.info(
            "Reorganized client files: moved=%d, unmatched=%d, client_folders=%d",
            moved,
            unmatched,
            len(changed_folders),
        )

    # ------------------------------------------------------------------
    # Run-all convenience
    # ------------------------------------------------------------------

    def run_all(self) -> None:
        """Run all enhancement categories in sequence."""
        if not self.tasks:
            self.load()
        logger.info("=" * 60)
        logger.info("VAULT ENHANCEMENT — ALL CATEGORIES")
        logger.info("=" * 60)
        self.implement_smart_tagging()
        self.implement_relationship_graph()
        self.improve_project_navigation()
        self.implement_zettelkasten()
        self.create_coaching_methods_book()
        self.create_client_hub()
        self.implement_client_outcomes()
        self.create_client_templates()
        self.create_personal_dashboard()
        self.create_search_discovery_tools()
        logger.info("Enhancement complete.")

    # ------------------------------------------------------------------
    # Private: category 7 helpers
    # ------------------------------------------------------------------

    def _build_known_client_aliases(self, clients_dir: Path) -> Dict[str, str]:
        aliases: Dict[str, str] = {}
        for file_path in sorted(clients_dir.glob("*.md")):
            if file_path.name in {"INDEX.md", "README.md"}:
                continue
            if _GENERIC_CLIENT_FILE_RE.match(file_path.name):
                continue

            canonical = file_path.stem.strip()
            normalized = self._normalize_client_name(canonical)
            if normalized:
                aliases[normalized] = canonical
        return aliases

    def _resolve_client_name(
        self,
        content: str,
        known_clients: Dict[str, str],
    ) -> Optional[str]:
        candidates = self._extract_client_candidates(content)
        for candidate in candidates:
            normalized = self._normalize_client_name(candidate)
            if not normalized:
                continue

            exact = known_clients.get(normalized)
            if exact:
                return exact

            fuzzy = self._best_fuzzy_client_match(normalized, known_clients)
            if fuzzy:
                return fuzzy

            # If no known profile exists but the signal is strong enough,
            # use the extracted candidate as a new folder name.
            return candidate
        return None

    def _extract_client_candidates(self, content: str) -> List[str]:
        candidates: List[str] = []
        # Restrict extraction to the beginning of the file where metadata lines
        # and section headers are expected. This avoids random body false positives.
        head = "\n".join(content.splitlines()[:120])
        for pattern in _CLIENT_NAME_LINE_PATTERNS:
            for match in pattern.findall(head):
                cleaned = self._clean_client_name_hint(match)
                if cleaned and cleaned not in candidates:
                    candidates.append(cleaned)
        return candidates

    def _clean_client_name_hint(self, raw_hint: str) -> str:
        name = raw_hint.strip()
        name = _CLIENT_PREFIX_RE.sub("", name)
        name = _TRAILING_DATE_RE.sub("", name)
        name = re.sub(r"\([^)]*\)", "", name)
        name = re.sub(r"\s+-\s+.*$", "", name)
        name = re.sub(r"\s+", " ", name).strip(" -:")
        return name

    def _normalize_client_name(self, name: str) -> str:
        text = name.strip().lower()
        text = re.sub(r"\([^)]*\)", "", text)
        text = re.sub(r"[^\w\säöüß-]", " ", text)
        text = _CLIENT_PREFIX_RE.sub("", text)
        text = _TRAILING_DATE_RE.sub("", text)
        parts = [p for p in re.split(r"\s+", text) if p and p not in _NON_NAME_TOKENS]
        return " ".join(parts)

    def _best_fuzzy_client_match(
        self,
        normalized_candidate: str,
        known_clients: Dict[str, str],
    ) -> Optional[str]:
        best_name: Optional[str] = None
        best_score = 0.0
        cand_tokens = set(normalized_candidate.split())
        for known_normalized, canonical in known_clients.items():
            seq_score = SequenceMatcher(None, normalized_candidate, known_normalized).ratio()
            known_tokens = set(known_normalized.split())
            token_score = 0.0
            if cand_tokens or known_tokens:
                token_score = len(cand_tokens & known_tokens) / max(
                    1,
                    len(cand_tokens | known_tokens),
                )
            score = max(seq_score, token_score)
            if score > best_score:
                best_score = score
                best_name = canonical

        if best_score >= 0.72:
            return best_name
        return None

    def _unique_target_path(self, target_path: Path) -> Path:
        if not target_path.exists():
            return target_path
        stem = target_path.stem
        suffix = target_path.suffix
        counter = 2
        while True:
            candidate = target_path.with_name(f"{stem}_{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _write_client_folder_index(self, client_dir: Path) -> None:
        files = sorted(
            [p for p in client_dir.glob("*.md") if p.name != "INDEX.md"],
            key=lambda p: p.name.lower(),
        )
        lines = [f"# {client_dir.name}", "", "## Dateien", ""]
        if not files:
            lines.append("- (Keine Dateien)")
        else:
            for file_path in files:
                note = file_path.stem
                lines.append(f"- [[{note}|{file_path.name}]]")
        lines += ["", f"Zuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d')}"]
        (client_dir / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # Private: tagging helpers
    # ------------------------------------------------------------------

    def _add_tags_to_file(self, file_path: Path, tags: List[str]) -> str:
        """Add tag list to the task file and return the updated content."""
        content = file_path.read_text(encoding="utf-8")
        if not tags:
            return content
        tags_str = " ".join(tags)
        # Replace existing tags before the Raw Asana block
        if "**Tags**:" in content and "**Tags**:" in content.split("Raw Asana Data")[0]:
            content = re.sub(r"(\n\*\*Tags\*\*:) [^\n]*", f"\\1 {tags_str}", content)
        else:
            for marker in ("## Custom Fields", "## Attachments", "## 📋 Subtasks", "## Timeline"):
                pos = content.find(marker)
                if pos != -1:
                    line_start = content.rfind("\n", 0, pos) + 1
                    content = content[:line_start] + f"**Tags**: {tags_str}\n\n" + content[line_start:]
                    break
        return content

    # ------------------------------------------------------------------
    # Private: relationship graph
    # ------------------------------------------------------------------

    def _find_related_items(self, task: Dict, min_similarity: float = 0.3) -> List[Dict]:
        kw = self._extract_keywords(task["title"] + " " + task["content"])
        related = []
        for other in self.tasks:
            if other["path"] == task["path"]:
                continue
            other_kw = self._extract_keywords(other["title"])
            denom = len(kw) + len(other_kw)
            if denom > 0 and len(kw & other_kw) / denom >= min_similarity:
                related.append(other)
        return sorted(related, key=lambda x: x["title"])[:5]

    def _extract_keywords(self, text: str):
        stop = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
            "of", "with", "by", "from", "as", "is", "was", "are", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "must", "can", "this", "that",
            "these", "those", "i", "you", "he", "she", "it", "we", "they",
        }
        words = re.findall(r"\b\w+\b", text.lower())
        return set(w for w in words if w not in stop and len(w) > 3)

    def _add_relationship_links(self, file_path: Path, related: List[Dict]) -> int:
        content = file_path.read_text(encoding="utf-8")
        if "## 🔗 Related Items" in content or "## Related Items" in content:
            return 0
        section = "\n## 🔗 Related Items\n\n"
        for item in related:
            link = item["filename"].replace(".md", "")
            section += f"- [[{link}|{item['title']}]] ({item['project']})\n"
        pos = content.find("<details>")
        if pos == -1:
            pos = len(content)
        new_content = content[:pos] + section + "\n" + content[pos:]
        file_path.write_text(new_content, encoding="utf-8")
        return 1

    def _enhance_project_index(self, project_name: str, tasks: List[Dict]) -> int:
        index_path = self.vault_path / project_name / "INDEX.md"
        if not index_path.exists():
            return 0
        grouped: Dict[str, list] = defaultdict(list)
        for t in tasks:
            grouped[t["context"]].append(t)
        lines = [
            f"# {project_name} - Index",
            "",
            f"📊 **{len(tasks)} Items** | Last Updated: {datetime.now().strftime('%Y-%m-%d')}",
            "",
            "## 🔍 Quick Filters",
            "",
            "- (tag:#active) Active Only",
            "- (tag:#priority) Priority",
            "- (tag:#client) Client-Related",
            "",
        ]
        label = {"active": "Active", "client": "Client", "method": "Methods",
                 "learning": "Learning", "reference": "References", "general": "General"}
        for ctx in ("active", "client", "method", "learning", "reference", "general"):
            if ctx in grouped:
                lines.append(f"### {label.get(ctx, ctx)}")
                lines.append("")
                for t in sorted(grouped[ctx], key=lambda x: x["title"])[:20]:
                    fname = t["filename"].replace(".md", "")
                    lines.append(f"- [[{fname}|{t['title']}]]")
                lines.append("")
        index_path.write_text("\n".join(lines), encoding="utf-8")
        return 1

    # ------------------------------------------------------------------
    # Private: knowledge base
    # ------------------------------------------------------------------

    def _categorize_resources(self, tasks: List[Dict]) -> Dict[str, List[Dict]]:
        kw_map = {
            "Core Concepts": ["konzept", "concept", "principle", "prinzip", "grundlagen"],
            "Methods & Techniques": ["methode", "method", "technique", "technik", "prozess"],
            "Case Studies": ["case", "example", "beispiel", "story", "geschichte"],
            "Tools & Resources": ["tool", "vorlage", "template", "checklist", "worksheet"],
            "References": ["referenz", "reference", "link", "artikel", "article", "buch"],
        }
        result: Dict[str, List[Dict]] = defaultdict(list)
        for task in tasks:
            text = (task["title"] + " " + task["content"]).lower()
            placed = False
            for cat, keywords in kw_map.items():
                if any(kw in text for kw in keywords):
                    result[cat].append(task)
                    placed = True
                    break
            if not placed:
                result["General"].append(task)
        return dict(result)

    def _create_zettelkasten_hub(self, categories: Dict[str, List[Dict]]) -> None:
        hub_path = self.vault_path / "= Resources 4 Me" / "00_ZETTELKASTEN_HUB.md"
        hub_path.parent.mkdir(exist_ok=True)
        lines = ["# 🧠 Zettelkasten - Knowledge Base Hub", "", ""]
        for cat, items in sorted(categories.items()):
            lines.append(f"### {cat} ({len(items)} Items)")
            lines.append("")
            for item in sorted(items, key=lambda x: x["title"])[:10]:
                fname = item["filename"].replace(".md", "")
                lines.append(f"- [[{fname}|{item['title']}]]")
            if len(items) > 10:
                lines.append(f"- … and {len(items) - 10} more")
            lines.append("")
        lines.append(f"\nZuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d')}")
        hub_path.write_text("\n".join(lines), encoding="utf-8")

    def _create_methods_book(self, methods: List[Dict]) -> None:
        book_path = self.vault_path / "Methoden Koffer" / "_METHODS_BOOK.md"
        book_path.parent.mkdir(exist_ok=True)
        lines = ["# 📖 Coaching Methods Handbook", "", ""]
        for m in sorted(methods, key=lambda x: x["title"]):
            fname = m["filename"].replace(".md", "")
            lines.append(f"### [[{fname}|{m['title']}]]")
            lines.append(f"**Quelle:** {m['project']}")
            desc_match = re.search(r"## Description\n\n(.+?)(?:\n##|\Z)", m["content"], re.DOTALL)
            if desc_match:
                lines.append(f"\n{desc_match.group(1).strip()[:200]}…")
            lines.append("")
        lines.append(f"\nZuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d')}")
        book_path.write_text("\n".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # Private: client hub
    # ------------------------------------------------------------------

    def _create_client_hub_index(self, clients: List[Dict], hub: Path) -> None:
        lines = [f"# 👥 Client Hub", "", f"Zentrale Verwaltung aller {len(clients)} Klienten.", ""]
        for c in sorted(clients, key=lambda x: x["title"]):
            fname = sanitize_filename(c["title"])
            lines.append(f"- [[_CLIENTS_HUB/{fname}|{c['title']}]]")
        lines.append(f"\nZuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d')}")
        (hub / "_INDEX.md").write_text("\n".join(lines), encoding="utf-8")

    def _create_client_profile(self, client: Dict, hub: Path) -> bool:
        try:
            fname = sanitize_filename(client["title"])
            resources = [
                t for t in self.tasks
                if t["project"] == "= Resources 4 Clients"
                and (client["title"].lower() in t["title"].lower()
                     or client["title"].lower() in t["content"].lower())
            ]
            lines = [
                f"# {client['title']}", "",
                "## 📋 Profil", "",
                f"**Zuletzt aktualisiert:** {datetime.now().strftime('%Y-%m-%d')}", "",
            ]
            if client.get("assignee"):
                lines.append(f"**Coach:** {client['assignee']}")
            if client.get("due_date"):
                lines.append(f"**Nächster Termin:** {client['due_date']}")
            lines += ["", "## 📚 Zugehörige Ressourcen", ""]
            if resources:
                for r in resources[:10]:
                    rf = r["filename"].replace(".md", "")
                    lines.append(f"- [[{rf}|{r['title']}]]")
            else:
                lines.append("*Keine spezifischen Ressourcen*")
            orig = client["filename"].replace(".md", "")
            lines += [
                "", "## 📝 Original Task", "",
                f"[[{orig}|{client['title']} (Clients)]]",
                "", "---", "",
                "[[_CLIENTS_HUB/_INDEX|← Client Hub]]",
            ]
            (hub / f"{fname}.md").write_text("\n".join(lines), encoding="utf-8")
            return True
        except Exception as exc:
            logger.warning("Could not create profile for %s: %s", client.get("title"), exc)
            return False

    def _create_outcomes_tracker(self) -> None:
        path = self.vault_path / "_CLIENTS_HUB" / "_OUTCOMES_TRACKER.md"
        path.parent.mkdir(exist_ok=True)
        lines = ["# 📈 Client Outcomes & Results", ""]
        for c in sorted(self.clients, key=lambda x: x["title"])[:15]:
            lines += [f"### {c['title']}", "- **Status:** Aktiv", "- **Outcome:** (To be documented)", ""]
        lines.append(f"\nZuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d')}")
        path.write_text("\n".join(lines), encoding="utf-8")

    # ------------------------------------------------------------------
    # Private: client templates (5B)
    # ------------------------------------------------------------------

    def _create_templates_index(self, folder: Path) -> None:
        content = f"""# 📋 Client Project Templates

Vorlagen für neue Client-Projekte. Copy & Paste in ein neues Client-Projekt!

## Verfügbare Templates

1. [[_CLIENT_TEMPLATES/01_WELCOME_PACKAGE|📦 Welcome Package]]
2. [[_CLIENT_TEMPLATES/02_FIRST_CALL_AGENDA|📞 Erstes Call Agenda]]
3. [[_CLIENT_TEMPLATES/03_COACHING_PROCESS|🎯 Coaching Process Blueprint]]
4. [[_CLIENT_TEMPLATES/04_FOLLOWUP_SCHEDULE|⏰ Follow-up Schedule]]
5. [[_CLIENT_TEMPLATES/05_RESOURCES_CHECKLIST|✓ Resources Checklist]]

---

Zuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d')}
"""
        (folder / "_INDEX.md").write_text(content, encoding="utf-8")

    def _create_welcome_template(self, folder: Path) -> None:
        (folder / "01_WELCOME_PACKAGE.md").write_text(
            "# 📦 Welcome Package - [CLIENT NAME]\n\n[Deine Willkommens-Info hier.]\n",
            encoding="utf-8",
        )

    def _create_first_call_template(self, folder: Path) -> None:
        (folder / "02_FIRST_CALL_AGENDA.md").write_text(
            "# 📞 Erstes Coaching-Call Agenda - [CLIENT NAME]\n\n"
            "**Datum:** [DATE]  \n**Dauer:** 60 min\n\n"
            "## Agenda\n\n1. Warm-up (10 min)\n2. Situation (15 min)\n"
            "3. Goal Setting (15 min)\n4. Prozess (10 min)\n5. Closure (10 min)\n",
            encoding="utf-8",
        )

    def _create_coaching_process_template(self, folder: Path) -> None:
        (folder / "03_COACHING_PROCESS.md").write_text(
            "# 🎯 Coaching Process Blueprint - [CLIENT NAME]\n\n"
            "## Phase 1: Discovery\n## Phase 2: Planning\n## Phase 3: Interventions\n"
            "## Phase 4: Closure\n",
            encoding="utf-8",
        )

    def _create_followup_template(self, folder: Path) -> None:
        (folder / "04_FOLLOWUP_SCHEDULE.md").write_text(
            "# ⏰ Follow-up Schedule - [CLIENT NAME]\n\n"
            "## Meilensteine\n\n- [ ] Week 1\n- [ ] Week 4\n- [ ] Week 8\n",
            encoding="utf-8",
        )

    def _create_resources_checklist_template(self, folder: Path) -> None:
        (folder / "05_RESOURCES_CHECKLIST.md").write_text(
            "# ✓ Resources Checklist - [CLIENT NAME]\n\n"
            "## Relevante Methoden\n\n- [ ] Aktives Zuhören\n- [ ] Reframing\n",
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Private: personal dashboard utilities (6A)
    # ------------------------------------------------------------------

    def _count_priority_tasks(self) -> int:
        count = 0
        for t in self.tasks:
            if t.get("due_date"):
                try:
                    due = datetime.strptime(t["due_date"], "%Y-%m-%d")
                    if 0 <= (due - datetime.now()).days <= 7:
                        count += 1
                except ValueError:
                    pass
        return count

    def _build_dashboard(
        self,
        active: int,
        priority: int,
        clients: Dict,
        areas: Dict[str, int],
        workload: Dict,
    ) -> str:
        total_areas = sum(areas.values()) or 1
        area_lines = ""
        for area, count in sorted(areas.items(), key=lambda x: x[1], reverse=True):
            pct = count / total_areas * 100
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            area_lines += f"- **{area:25}** {bar} {int(pct)}% ({count})\n"

        next_items = "\n".join(
            f"- [ ] {t['title']}" for t in self.tasks if t["project"] == "_ Next"
        )[:300] or "- (Keine)"

        return f"""# 📊 Personal Dashboard

**Last Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

---

## 🎯 Snapshot

- ⏳ Sofort (_ Next): **{active}**
- ⭐ Diese Woche: **{priority}**
- 👥 Clients: **{clients['total_clients']}**
- 📁 Aktive Projekte: **{workload['active_projects']}**

---

## 📈 Time Breakdown

{area_lines}

---

## 🎯 Diese Woche Action Items

{next_items}

---

## 🚀 Quick Links

- [[_CLIENTS_HUB/_INDEX|👥 Client Hub]]
- [[= Resources 4 Me/00_ZETTELKASTEN_HUB|🧠 Zettelkasten]]
- [[Methoden Koffer/_METHODS_BOOK|📖 Methods Handbook]]
- [[_ Next|⏳ Next Actions]]

---

Zuletzt generiert: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

    # ------------------------------------------------------------------
    # Private: search & discovery (6B)
    # ------------------------------------------------------------------

    def _create_search_index(self) -> None:
        path = self.vault_path / "= Resources 4 Me" / "_SEARCH_GUIDE.md"
        path.parent.mkdir(exist_ok=True)
        resources = [t for t in self.tasks if t["project"] == "= Resources 4 Me"]
        keywords: Dict[str, list] = defaultdict(list)
        for t in resources[:100]:
            for w in re.findall(r"\b\w+\b", t["title"].lower()):
                if len(w) > 4:
                    keywords[w].append(t["title"])
        top_kw = "\n".join(
            f"- `{kw}` ({len(set(v))} items)"
            for kw, v in sorted(keywords.items(), key=lambda x: len(x[1]), reverse=True)[:30]
        )
        content = (
            f"# 🔍 Search Guide\n\n"
            f"**Total Items:** {len(resources)}  \n"
            f"**Indexed Keywords:** {len(keywords)}  \n"
            f"**Last Updated:** {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"## Top Keywords\n\n{top_kw}\n"
        )
        path.write_text(content, encoding="utf-8")

    def _create_faceted_search(self) -> None:
        path = self.vault_path / "= Resources 4 Me" / "_FACETED_SEARCH.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            "# 🔎 Faceted Search Interface\n\n"
            "Nutze Tags, Pfad-Filter und Volltextsuche für gezielte Suchen.\n\n"
            f"Zuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d')}\n",
            encoding="utf-8",
        )

    def _create_discovery_suggestions(self) -> None:
        path = self.vault_path / "= Resources 4 Me" / "_RANDOM_DISCOVERY.md"
        path.parent.mkdir(exist_ok=True)
        resources = [t for t in self.tasks if t["project"] == "= Resources 4 Me"]
        random.seed(int(datetime.now().strftime("%Y%m%d")))
        picks = random.sample(resources, min(7, len(resources)))
        picks_lines = "\n".join(
            f"- [[{p['filename'].replace('.md', '')}|{p['title']}]]" for p in picks
        )
        path.write_text(
            f"# 🎲 Random Discovery\n\n{picks_lines}\n\n"
            f"Zuletzt aktualisiert: {datetime.now().strftime('%Y-%m-%d')}\n",
            encoding="utf-8",
        )
