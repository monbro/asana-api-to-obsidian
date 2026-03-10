"""
Centralized configuration and constants for the Asana to Obsidian exporter.

All magic numbers and shared configuration live here so they are documented
and easy to adjust in one place.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Asana API
# ---------------------------------------------------------------------------

ASANA_BASE_URL: str = "https://app.asana.com/api/1.0"

RATE_LIMIT_DELAY: float = 0.2
"""Seconds to sleep before each API call. Conservative value for Free Tier safety."""

FREE_TIER_REQUESTS_PER_WINDOW: int = 600
"""Asana Free Tier maximum: 600 requests per 10-minute window. Available for
future rate-limit tracking; not currently used as a counter."""

PAGE_SIZE_MAX: int = 100
"""Maximum records per page enforced by the Asana API."""

REQUEST_TIMEOUT_SECONDS: int = 30
"""HTTP socket timeout for standard API calls."""

HEAD_REQUEST_TIMEOUT: int = 10
"""Short timeout for HEAD requests used to detect attachment content-type."""

ATTACHMENT_CHUNK_SIZE: int = 8192
"""Bytes per chunk when streaming attachment downloads."""

# opt_fields string reused across task-related API calls
TASK_OPT_FIELDS: str = (
    "gid,name,description,notes,completed,completed_at,completed_by.name,"
    "completed_by.email,due_on,due_at,start_on,start_at,assignee.name,"
    "assignee.email,assignee_status,created_by.name,created_by.email,"
    "created_at,modified_at,followers.name,followers.email,custom_fields,"
    "attachments,projects.name,tags.name,parent.name,num_subtasks,"
    "num_attachments,resource_type,resource_subtype,approval_status,"
    "permalink_url,html_notes,memberships.section.name,memberships.section.gid"
)

SUBTASK_OPT_FIELDS: str = (
    "gid,name,description,notes,completed,completed_at,completed_by.name,"
    "completed_by.email,due_on,due_at,start_on,start_at,assignee.name,"
    "assignee.email,assignee_status,created_by.name,created_by.email,"
    "created_at,modified_at,followers.name,followers.email,custom_fields,"
    "attachments,num_subtasks,resource_type,resource_subtype,approval_status,"
    "permalink_url,html_notes"
)

STORY_OPT_FIELDS: str = (
    "gid,type,created_by.name,created_by.email,created_at,text,"
    "attachment.name,attachment.url,attachment.download_url,attachment.size,"
    "resource_subtype,html_text"
)

# ---------------------------------------------------------------------------
# File system
# ---------------------------------------------------------------------------

FILENAME_MAX_LENGTH: int = 200
"""OS-safe maximum character length for generated filenames."""

FILENAME_INVALID_CHARS: str = '<>:"/\\|?*'
"""Characters that are invalid in filenames on Windows and/or macOS/Linux."""

STATE_FILENAME: str = ".asana_export_state.json"
"""Name of the incremental-backup state file stored in the vault root."""

# ---------------------------------------------------------------------------
# Vault scanner
# ---------------------------------------------------------------------------

SKIP_FILENAMES: frozenset = frozenset({"INDEX.md", "README.md"})
"""Markdown filenames that the vault scanner always skips."""

SUBTASK_FETCH_DEPTH: int = 2
"""Maximum depth to recursively fetch sub-subtasks. Prevents infinite loops
on deeply nested task hierarchies."""

# ---------------------------------------------------------------------------
# Content-type → file extension mapping for attachment downloads
# ---------------------------------------------------------------------------

CONTENT_TYPE_MAP: dict = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
    "text/csv": ".csv",
}

# ---------------------------------------------------------------------------
# Settings dataclass (passed to entry-point constructors)
# ---------------------------------------------------------------------------


@dataclass
class ExporterSettings:
    """Runtime settings for the Asana exporter."""

    token: str
    """Asana Personal Access Token."""

    vault_path: Path
    """Absolute path to the target Obsidian vault directory."""

    debug: bool = False
    """Enable DEBUG-level logging when True."""

    project_filter: Optional[str] = None
    """When set, only the project whose name matches this string (case-insensitive)
    will be exported. All other projects are skipped."""
