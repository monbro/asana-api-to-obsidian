# Asana to Obsidian Vault Exporter

Ein umfassendes Python-Skript zum Exportieren eines kompletten Asana-Workspaces (kostenlos) in eine lokale Obsidian-Vault mit vollständiger Metadaten-Erhaltung, Anhängen und inkrementellen Backups.

## Features

✅ **Vollständiger Workspace-Export**
- Exportiert alle Projekte und Tasks
- Respektiert Asana Free Tier API-Rate-Limits
- Inkrementelle Synchronisation (nur geaenderte Tasks werden aktualisiert)
- Konflikt-Handling bei lokalen Aenderungen (overwrite/skip/copy)

✅ **Strukturierte Markdown-Dateien**
- Jeder Task erhält eine eigene `.md`-Datei
- Obsidian-native Format mit vollständigen Metadaten
- Lesbare Metadata-Sektion statt YAML Frontmatter
- Unterstützung für Custom Fields
- Chronologisch sortierte Kommentare (Stories)
- Eingebettete, kollapsierbare Subtasks

✅ **Vault-Enhancements**
- Smart Tagging (#active, #priority, #client, …)
- Relationship Graph (Wikilinks zwischen verwandten Items)
- Zettelkasten Hub für Wissensquellen
- Client Hub mit Profilen & Outcome-Tracking
- Persönliches Dashboard & Such-Tools

✅ **Git-Ready**
- Automatische `.gitignore` für Medienformate
- State-Tracking für reproduzierbare Läufe

## Projektstruktur

```
project-root/
├── asana_obsidian_exporter.py   # Entry point (Export)
├── enhance_vault.py             # Entry point (Enhancement)
├── verify_setup.py              # Verbindungstest
├── requirements.txt
│
├── src/                         # Alle Quellcode-Module
│   ├── config.py                # Konstanten & ExporterSettings
│   ├── api/
│   │   └── client.py            # AsanaApiClient (HTTP-Schicht)
│   ├── export/
│   │   ├── state.py             # ExportState (inkrementelle Backups)
│   │   ├── formatter.py         # MarkdownFormatter (stateless)
│   │   └── exporter.py          # AsanaExporter (Orchestrierung)
│   ├── vault/
│   │   ├── scanner.py           # VaultScanner (gemeinsames Parsing)
│   │   ├── enhancer.py          # VaultEnhancer (alle Kategorien)
│   │   └── cleanup.py           # VaultCleanup (Bereinigung)
│   └── utils/
│       ├── files.py             # sanitize_filename, safe_delete, …
│       └── logging_config.py    # configure_logging()
│
└── tests/
    ├── conftest.py              # Geteilte Fixtures & Hilfsfunktionen
    ├── test_api_client.py
    ├── test_formatter.py
    ├── test_state.py
    └── test_vault_scanner.py
```

## Installation

### 1. Asana Personal Access Token erstellen

1. Melden Sie sich bei [Asana](https://app.asana.com) an
2. Gehen Sie zu **Einstellungen → Sicherheit → Personal Access Token**
3. Klicken Sie auf **Neuen Token generieren**
4. Kopieren Sie den generierten Token (speichern Sie ihn sicher!)

### 2. Python Environment einrichten

```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
```

## Verwendung

### Export

```bash
# Mit Token als Argument
python3 asana_obsidian_exporter.py \
  --token YOUR_ASANA_TOKEN \
  --vault ~/Obsidian/AsanaExport

# Mit .env Datei (empfohlen)
# .env anlegen: ASANA_TOKEN=your_token
python3 asana_obsidian_exporter.py --vault ~/Obsidian/AsanaExport

# Debug-Modus
python3 asana_obsidian_exporter.py --vault ~/Obsidian/AsanaExport --debug

# Konflikt-Handling bei lokalen Aenderungen
python3 asana_obsidian_exporter.py \
  --vault ~/Obsidian/AsanaExport \
  --conflict-policy overwrite  # overwrite | skip | copy
```

### Vault Enhancement

Hinweis: Enhancements laufen **nach** der Synchronisation und veraendern
die lokal exportierten Dateien fuer eine bessere Obsidian-Nutzung.

```bash
# Alle Kategorien
python3 enhance_vault.py --vault ~/Obsidian/AsanaExport

# Einzelne Kategorie
python3 enhance_vault.py \
  --vault ~/Obsidian/AsanaExport \
  --category smart_tagging

# Verfügbare Kategorien:
#   smart_tagging, relationship_graph, project_navigation,
#   zettelkasten, coaching_methods, client_hub, client_outcomes,
#   client_templates, personal_dashboard, search_discovery,
#   client_file_reorganization
```

### Tests ausführen

```bash
python3 -m pytest tests/ -v
```

## Ausgabestruktur

```
AsanaExport/
├── .asana_export_state.json          # Inkrementalbackup-State
├── .gitignore                         # Git-Filter für Medien
├── Projekt 1/
│   ├── README.md                      # Projektübersicht
│   ├── INDEX.md                       # Task-Liste nach Sektionen
│   ├── Task 1 - Titel.md              # Task mit Metadaten + Stories
│   └── attachments/
│       └── dokument.pdf
└── ...
```

## Inkrementelle Backups

Das Skript speichert den Export-State in `.asana_export_state.json`:

- Bereits exportierte Tasks werden übersprungen
- Bereits heruntergeladene Anhänge werden nicht neu heruntergeladen

```bash
# Kompletten Re-Export erzwingen
rm AsanaExport/.asana_export_state.json
python3 asana_obsidian_exporter.py --vault ~/Obsidian/AsanaExport
```

## API-Rate-Limiting

- **Conservative Delays**: 0.2s zwischen API-Calls (`RATE_LIMIT_DELAY` in `src/config.py`)
- **Pagination**: Batch-Abruf mit max. 100 Items pro Request
- **Timeout-Handling**: 30s Timeout pro Request

## Architektur-Hinweise

| Schicht | Klasse | Verantwortlichkeit |
|---------|--------|-------------------|
| HTTP | `AsanaApiClient` | Rate-Limiting, Pagination, Fehlerbehandlung |
| State | `ExportState` | Persistenz inkrementeller Backup-State |
| Format | `MarkdownFormatter` | Stateless: Input-Dict → Markdown-String |
| Export | `AsanaExporter` | Orchestrierung aller Schichten |
| Scan | `VaultScanner` | Gemeinsames Vault-Parsing |
| Enhance | `VaultEnhancer` | Post-Export-Anreicherung |
| Cleanup | `VaultCleanup` | Bereinigung (dry_run=True Standard) |

**Dependency-Reihenfolge** (keine zirkulären Importe):
`utils` ← `config` ← `api` ← `export` ← `vault`

## Fehlerbehebung

### "Failed to authenticate"
- Token überprüfen: `echo $ASANA_TOKEN`
- Token-Gültigkeit auf asana.com prüfen

### "No projects found"
- Asana-Account hat keine Projekte
- Token hat keine Projektlese-Berechtigung

### API Timeouts
- `RATE_LIMIT_DELAY` in `src/config.py` erhöhen
- Internetverbindung prüfen

## Sicherheitshinweise

- Speichern Sie Tokens nicht im Git-Repository
- Verwenden Sie `.env` (in `.gitignore` enthalten)
- `VaultCleanup`-Methoden löschen standardmäßig nichts (`dry_run=True`)

## Changelog

### v2.0.0 (2026-03)
- Vollständige Refaktorierung in `src/`-Package-Struktur
- Duplikat-Scanner-Logik in `VaultScanner` konsolidiert
- 10 Cleanup-Skripte in `VaultCleanup` zusammengeführt
- Beide Enhancement-Skripte zu `VaultEnhancer` vereint
- `MarkdownFormatter` vollständig stateless (testbar ohne Mocks)
- Alle destruktiven Operationen mit `dry_run=True` Standard
- `safe_delete()` als einzige Funktion mit `unlink()`-Aufruf
- 47 Unit-Tests hinzugefügt

### v1.0.0 (2026-02-20)
- Initial Release
- Vollständiger Workspace-Export
- Inkrementelle Backups
- Anhang-Download
- Custom Fields Support
- Stories/Comments Integration
