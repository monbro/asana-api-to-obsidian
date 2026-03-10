"""
Advanced Usage Examples for Asana Obsidian Exporter
Zeigt spezielle Anwendungsfälle und Anpassungen.
"""

from asana_obsidian_exporter import AsanaExporter
import os


# ============================================================================
# Beispiel 1: Nur bestimmte Projekte exportieren
# ============================================================================

def export_selected_projects():
    """Exportiert nur ausgewählte Projekte nach Namen."""
    token = os.getenv("ASANA_TOKEN")
    exporter = AsanaExporter(token, "./vault_selected")
    
    # Alle Projekte abrufen
    projects = exporter.get_projects()
    
    # Filter nach Projektnamen
    selected_names = ["Clients", "Coaching", "Business"]
    filtered_projects = [
        p for p in projects 
        if any(name in p.get("name", "") for name in selected_names)
    ]
    
    print(f"Exporting {len(filtered_projects)} selected projects")
    
    # Projekte einzeln exportieren
    for project in filtered_projects:
        exporter.export_project(project)
    
    exporter._save_state()


# ============================================================================
# Beispiel 2: Nur neue/geänderte Tasks seit letztem Export
# ============================================================================

def export_incremental_changes():
    """Exportiert nur geänderte Tasks seit letztem Lauf."""
    token = os.getenv("ASANA_TOKEN")
    exporter = AsanaExporter(token, "./vault_incremental")
    
    projects = exporter.get_projects()
    
    for project in projects:
        tasks = exporter.get_project_tasks(project.get("gid"))
        
        # Nur neue Tasks exportieren (nicht im State)
        for task in tasks:
            task_id = task.get("gid")
            if task_id not in exporter.state["exported_tasks"]:
                exporter.export_task(task, project.get("name"), 
                                   exporter.vault_path / exporter._sanitize_filename(project.get("name")))
    
    exporter._save_state()
    print("Incremental export completed")


# ============================================================================
# Beispiel 3: Nur Anhänge neu downloaden (ohne Tasks neu zu exportieren)
# ============================================================================

def redownload_attachments():
    """Lädt alle Anhänge erneut herunter."""
    token = os.getenv("ASANA_TOKEN")
    exporter = AsanaExporter(token, "./vault_with_attachments")
    
    # State zurücksetzen für Anhänge
    exporter.state["downloaded_attachments"] = {}
    
    projects = exporter.get_projects()
    
    for project in projects:
        project_folder = exporter.vault_path / exporter._sanitize_filename(project.get("name"))
        project_folder.mkdir(parents=True, exist_ok=True)
        
        tasks = exporter.get_project_tasks(project.get("gid"))
        
        for task in tasks:
            task_detail = exporter.get_task_details(task.get("gid"))
            if task_detail and task_detail.get("attachments"):
                for attachment in task_detail["attachments"]:
                    print(f"Downloading: {attachment.get('name')}")
                    exporter.download_attachment(attachment, project_folder)
    
    exporter._save_state()
    print("Attachment download completed")


# ============================================================================
# Beispiel 4: Task-Filter nach Status/Zuordnung
# ============================================================================

def export_assigned_tasks_only():
    """Exportiert nur zugewiesene Tasks."""
    token = os.getenv("ASANA_TOKEN")
    exporter = AsanaExporter(token, "./vault_assigned")
    
    target_assignee = "Your Name"  # Ändern Sie dies
    
    projects = exporter.get_projects()
    
    for project in projects:
        tasks = exporter.get_project_tasks(project.get("gid"))
        project_folder = exporter.vault_path / exporter._sanitize_filename(project.get("name"))
        project_folder.mkdir(parents=True, exist_ok=True)
        
        # Filter nach Zuordnung
        assigned_tasks = [
            t for t in tasks 
            if t.get("assignee") and t["assignee"].get("name") == target_assignee
        ]
        
        print(f"Project {project.get('name')}: {len(assigned_tasks)} assigned tasks")
        
        for task in assigned_tasks:
            exporter.export_task(task, project.get("name"), project_folder)
    
    exporter._save_state()


# ============================================================================
# Beispiel 5: Benutzerdefinierter Markdown-Output Format
# ============================================================================

def export_with_custom_format():
    """Exportiert mit benutzerdefiniertem Markdown-Format."""
    token = os.getenv("ASANA_TOKEN")
    exporter = AsanaExporter(token, "./vault_custom")
    
    # Überschreiben Sie format_task_markdown für Custom Format
    original_format = exporter.format_task_markdown
    
    def custom_format(task, project_name, project_folder):
        """Custom Format mit Emojis und anderen Features."""
        title = task.get("name", "Untitled")
        description = task.get("description", "")
        completed = task.get("completed", False)
        
        status_emoji = "✅" if completed else "⏳"
        
        content = f"""# {status_emoji} {title}

**Projekt:** {project_name}
**Status:** {'Completed' if completed else 'Pending'}
**Asana Link:** [{title}]({task.get('permalink', '#')})

## Description
{description}

---

*Exported from Asana on {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""
        return content
    
    # Format überschreiben
    exporter.format_task_markdown = custom_format
    
    # Normalexport ausführen
    exporter.export_workspace()


# ============================================================================
# Beispiel 6: Export mit erweiterten Statistiken
# ============================================================================

def export_with_statistics():
    """Exportiert und erstellt eine Statistik-Datei."""
    import json
    from datetime import datetime
    
    token = os.getenv("ASANA_TOKEN")
    exporter = AsanaExporter(token, "./vault_stats")
    
    stats = {
        "timestamp": datetime.now().isoformat(),
        "projects": [],
        "total_tasks": 0,
        "total_attachments": 0,
        "completion_rate": 0
    }
    
    projects = exporter.get_projects()
    
    for project in projects:
        tasks = exporter.get_project_tasks(project.get("gid"))
        completed_count = sum(1 for t in tasks if t.get("completed"))
        attachment_count = sum(len(t.get("attachments", [])) for t in tasks)
        
        project_stats = {
            "name": project.get("name"),
            "task_count": len(tasks),
            "completed": completed_count,
            "pending": len(tasks) - completed_count,
            "completion_rate": f"{(completed_count / len(tasks) * 100):.1f}%" if tasks else "N/A",
            "attachments": attachment_count
        }
        stats["projects"].append(project_stats)
        stats["total_tasks"] += len(tasks)
        stats["total_attachments"] += attachment_count
        
        exporter.export_project(project)
        print(f"✓ {project.get('name')}: {len(tasks)} tasks, {attachment_count} attachments")
    
    # Statistiken speichern
    stats_file = exporter.vault_path / "EXPORT_STATISTICS.json"
    with open(stats_file, 'w') as f:
        json.dump(stats, f, indent=2)
    
    print(f"\n{'='*60}")
    print("Export Statistics:")
    print(f"{'='*60}")
    print(f"Total Projekte: {len(stats['projects'])}")
    print(f"Total Tasks: {stats['total_tasks']}")
    print(f"Total Attachments: {stats['total_attachments']}")
    print(f"Statistiken gespeichert in: {stats_file}")


# ============================================================================
# Beispiel 7: Fehlerbehandlung & Retry-Logik
# ============================================================================

def export_with_retry():
    """Exportiert mit automatischen Wiederholungen bei Fehlern."""
    import time
    
    token = os.getenv("ASANA_TOKEN")
    exporter = AsanaExporter(token, "./vault_reliable")
    
    max_retries = 3
    retry_delay = 5  # Sekunden
    
    projects = exporter.get_projects()
    
    for project in projects:
        retry_count = 0
        success = False
        
        while retry_count < max_retries and not success:
            try:
                success = exporter.export_project(project)
            except Exception as e:
                retry_count += 1
                if retry_count < max_retries:
                    print(f"Fehler bei {project.get('name')}, versuche erneut in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    print(f"Fehler bei {project.get('name')} nach {max_retries} Versuchen: {e}")
        
        if not success:
            print(f"⚠ {project.get('name')} konnte nicht exportiert werden")
    
    exporter._save_state()


# ============================================================================
# Beispiel 8: Spezific Export Scheduler
# ============================================================================

def schedule_daily_export():
    """Beispiel für tägliche Export-Planung (erfordert APScheduler)."""
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        print("Installieren Sie apscheduler: pip install apscheduler")
        return
    
    def daily_export():
        print(f"Starting scheduled export at {datetime.now()}")
        token = os.getenv("ASANA_TOKEN")
        exporter = AsanaExporter(token, "./vault_daily")
        exporter.export_workspace()
        print(f"Export completed at {datetime.now()}")
    
    scheduler = BackgroundScheduler()
    scheduler.add_job(daily_export, 'cron', hour=22, minute=0)  # Täglich 22:00
    scheduler.start()
    
    print("Scheduler started. Exporting daily at 22:00")
    
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.shutdown()


# ============================================================================
# Main - Wählen Sie ein Beispiel
# ============================================================================

if __name__ == "__main__":
    import sys
    from datetime import datetime
    
    if len(sys.argv) > 1:
        example = sys.argv[1]
    else:
        print("Available examples:")
        print("  1. export_selected_projects")
        print("  2. export_incremental_changes")
        print("  3. redownload_attachments")
        print("  4. export_assigned_tasks_only")
        print("  5. export_with_custom_format")
        print("  6. export_with_statistics")
        print("  7. export_with_retry")
        print("  8. schedule_daily_export")
        print()
        example = input("Select example (1-8): ").strip()
    
    examples = {
        "1": export_selected_projects,
        "2": export_incremental_changes,
        "3": redownload_attachments,
        "4": export_assigned_tasks_only,
        "5": export_with_custom_format,
        "6": export_with_statistics,
        "7": export_with_retry,
        "8": schedule_daily_export,
    }
    
    if example in examples:
        print(f"Running: {example}")
        examples[example]()
    else:
        print(f"Unknown example: {example}")
