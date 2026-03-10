"""
Shared file-system utilities.

Rule: ``safe_delete()`` is the **only** function in the entire codebase that
is permitted to call ``Path.unlink()``.  All other code must go through this
function so that dry-run protection and optional backup are always applied.
"""

import hashlib
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from src.config import ATTACHMENT_CHUNK_SIZE, FILENAME_INVALID_CHARS, FILENAME_MAX_LENGTH

logger = logging.getLogger(__name__)


def sanitize_filename(name: str, max_length: int = FILENAME_MAX_LENGTH) -> str:
    """Return *name* safe for use as a filename on all major operating systems.

    - Replaces every character in ``FILENAME_INVALID_CHARS`` with ``_``.
    - Strips leading/trailing spaces and dots.
    - Truncates to *max_length* characters.
    - Preserves Unicode characters (e.g. German Umlauts ä ö ü ß).

    Args:
        name:       Raw string to sanitize.
        max_length: Maximum allowed length (default: FILENAME_MAX_LENGTH).

    Returns:
        Sanitized filename string (without path separators or directory part).
    """
    for char in FILENAME_INVALID_CHARS:
        name = name.replace(char, "_")
    name = name.strip(". ")
    return name[:max_length]


def get_file_hash(file_path: Path) -> str:
    """Return the SHA-256 hex-digest of the file at *file_path*.

    Reads the file in ``ATTACHMENT_CHUNK_SIZE``-byte chunks to keep memory
    usage bounded for large attachments.

    Args:
        file_path: Path to an existing file.

    Returns:
        Lowercase hex string of the SHA-256 digest.

    Raises:
        OSError: If the file cannot be read.
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(ATTACHMENT_CHUNK_SIZE), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def ensure_unique_path(path: Path) -> Path:
    """Return a path that does not yet exist by appending ``_1``, ``_2``, ...

    If *path* does not exist it is returned unchanged. Otherwise the stem is
    suffixed with an incrementing counter until a free slot is found.

    Args:
        path: Candidate path (need not exist yet).

    Returns:
        A path guaranteed not to exist at the time of the call.

    Example::

        ensure_unique_path(Path("foo/bar.md"))
        # → Path("foo/bar.md")       if it does not exist
        # → Path("foo/bar_1.md")     if bar.md exists
        # → Path("foo/bar_2.md")     if bar_1.md also exists
    """
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def safe_delete(
    path: Path,
    backup_dir: Optional[Path] = None,
    dry_run: bool = True,
) -> bool:
    """Delete *path*, optionally with a backup copy first.

    This is the **only** function in the codebase that calls ``path.unlink()``.

    Args:
        path:       File to delete. Must be a file (not a directory).
        backup_dir: If given, *path* is copied here with ``shutil.copy2``
                    before deletion.  The directory is created if absent.
        dry_run:    When ``True`` (the default) the deletion is only logged,
                    never performed.  Pass ``dry_run=False`` explicitly to
                    delete for real.

    Returns:
        ``True`` if the file was deleted (or would have been in dry_run mode),
        ``False`` if an error occurred.
    """
    if not path.exists():
        logger.warning("safe_delete: path does not exist, skipping: %s", path)
        return False

    if dry_run:
        logger.info("[DRY RUN] Would delete: %s", path)
        return True

    # Warn loudly if deleting without a backup
    if backup_dir is None:
        logger.warning(
            "Deleting file without backup: %s  "
            "(pass backup_dir= to safe_delete() to keep a copy)",
            path,
        )
    else:
        backup_dir.mkdir(parents=True, exist_ok=True)
        dest = backup_dir / path.name
        dest = ensure_unique_path(dest)
        try:
            shutil.copy2(path, dest)
            logger.debug("Backed up %s → %s", path, dest)
        except OSError as exc:
            logger.error("Could not back up %s before deletion: %s", path, exc)
            return False

    try:
        path.unlink()
        logger.info("Deleted: %s", path)
        return True
    except OSError as exc:
        logger.error("Could not delete %s: %s", path, exc)
        return False
