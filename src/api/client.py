"""
Asana REST API client.

Pure HTTP layer: knows nothing about markdown formatting, vault paths, or
export orchestration.  Every method returns parsed JSON dicts / lists or
``None`` / ``[]`` on failure so callers never need to handle exceptions.

All requests are rate-limited by sleeping ``RATE_LIMIT_DELAY`` seconds before
each call to stay within Asana's Free Tier limits.
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from src.config import (
    ASANA_BASE_URL,
    ATTACHMENT_CHUNK_SIZE,
    CONTENT_TYPE_MAP,
    HEAD_REQUEST_TIMEOUT,
    PAGE_SIZE_MAX,
    RATE_LIMIT_BACKOFF_BASE,
    RATE_LIMIT_BACKOFF_MAX,
    RATE_LIMIT_DELAY,
    RATE_LIMIT_MAX_RETRIES,
    REQUEST_TIMEOUT_SECONDS,
    STORY_OPT_FIELDS,
    SUBTASK_OPT_FIELDS,
    TASK_OPT_FIELDS,
)
from src.utils.files import ensure_unique_path, sanitize_filename

logger = logging.getLogger(__name__)


class AsanaApiClient:
    """Low-level Asana API client.

    Responsibilities:
    - Session management (Bearer token auth)
    - Rate limiting (sleep before every request)
    - Pagination (follow next_page.offset tokens)
    - Error handling (log + return None/[] on failure)
    - Attachment downloading (streaming with deduplication)
    - Destructive API actions (task deletion/removal) for cleanup operations

    Not responsible for:
    - Markdown formatting
    - File system operations (except attachment download streaming)
    - Export state management
    """

    def __init__(self, token: str) -> None:
        """Initialise with an Asana Personal Access Token.

        Args:
            token: Asana PAT (starts with ``1/``).
        """
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            }
        )
        # Cached after the first call to get_workspace_id()
        self._workspace_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Optional[Any]:
        """Make a single API request with rate limiting.

        Args:
            endpoint: Path relative to the API base URL (e.g. ``"users/me"``).
            method:   HTTP method (default ``"GET"``).
            params:   URL query parameters.
            data:     JSON request body (for POST/PUT/DELETE).
            stream:   When True the raw ``requests.Response`` is returned so
                      the caller can stream the body.

        Returns:
            Parsed JSON dict (or list), the raw ``Response`` object when
            ``stream=True``, or ``None`` on any error.
        """
        url = f"{ASANA_BASE_URL}/{endpoint}"
        attempts = 0

        while True:
            time.sleep(RATE_LIMIT_DELAY)
            try:
                response = self._session.request(
                    method,
                    url,
                    params=params,
                    json=data,
                    stream=stream,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                if response.status_code == 429:
                    attempts += 1
                    if attempts > RATE_LIMIT_MAX_RETRIES:
                        logger.error(
                            "Rate limit exceeded for %s after %d retries.",
                            endpoint,
                            RATE_LIMIT_MAX_RETRIES,
                        )
                        return None

                    retry_after = response.headers.get("Retry-After")
                    sleep_time = None
                    if retry_after:
                        try:
                            sleep_time = float(retry_after)
                        except ValueError:
                            sleep_time = None
                    if sleep_time is None:
                        sleep_time = min(
                            RATE_LIMIT_BACKOFF_MAX,
                            RATE_LIMIT_BACKOFF_BASE * (2 ** (attempts - 1)),
                        )

                    logger.warning(
                        "Rate limited on %s (attempt %d/%d). Sleeping %.2fs.",
                        endpoint,
                        attempts,
                        RATE_LIMIT_MAX_RETRIES,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
                    continue

                response.raise_for_status()
                if stream:
                    return response
                return response.json()

            except requests.exceptions.RequestException as exc:
                logger.error("API request failed for %s: %s", endpoint, exc)
                # Attempt to log the response body for diagnostics.
                # Replaced bare `except:` with specific exceptions.
                if hasattr(exc, "response") and exc.response is not None:
                    try:
                        logger.error("Response body: %s", exc.response.json())
                    except (ValueError, AttributeError):
                        pass
                return None

    def _get_paginated(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict]:
        """Collect all pages of results from a paginated endpoint.

        Args:
            endpoint: API path (e.g. ``"projects"``).
            params:   Base query parameters (``limit`` is added automatically).

        Returns:
            Flat list of all result dicts across all pages.
        """
        results: List[Dict] = []
        params = dict(params or {})
        params["limit"] = PAGE_SIZE_MAX

        while True:
            response = self._api_request(endpoint, params=params)
            if not response or "data" not in response:
                break

            results.extend(response["data"])

            next_page = response.get("next_page")
            if not next_page or not next_page.get("offset"):
                break

            params["offset"] = next_page["offset"]
            logger.debug("Fetching more results for %s (offset token present)", endpoint)

        return results

    # ------------------------------------------------------------------
    # Read endpoints
    # ------------------------------------------------------------------

    def get_user_info(self) -> Optional[Dict]:
        """Return the authenticated user object or ``None``."""
        response = self._api_request("users/me")
        if response and "data" in response:
            return response["data"]
        return None

    def get_workspace_id(self) -> Optional[str]:
        """Return the first workspace GID for the authenticated user.

        The result is cached after the first successful call.
        """
        if self._workspace_id:
            return self._workspace_id
        user = self.get_user_info()
        if user and user.get("workspaces"):
            self._workspace_id = user["workspaces"][0].get("gid")
            logger.debug(
                "Using workspace: %s (%s)",
                user["workspaces"][0].get("name"),
                self._workspace_id,
            )
        return self._workspace_id

    def get_projects(self) -> List[Dict]:
        """Return all non-archived projects in the workspace."""
        logger.info("Fetching all projects...")
        workspace_id = self.get_workspace_id()
        if not workspace_id:
            logger.error("Could not determine workspace ID.")
            return []
        projects = self._get_paginated(
            "projects",
            {
                "workspace": workspace_id,
                "archived": "false",
                "opt_fields": "name,description,created_at,modified_at,members.name",
            },
        )
        logger.info("Found %d projects.", len(projects))
        return projects

    def get_project_tasks(self, project_id: str) -> List[Dict]:
        """Return all tasks (with full opt_fields) for *project_id*."""
        return self._get_paginated(
            f"projects/{project_id}/tasks",
            {"opt_fields": TASK_OPT_FIELDS},
        )

    def get_task_details(self, task_id: str) -> Optional[Dict]:
        """Return the full task object for *task_id*, or ``None``."""
        response = self._api_request(
            f"tasks/{task_id}", params={"opt_fields": TASK_OPT_FIELDS}
        )
        if response and "data" in response:
            return response["data"]
        return None

    def get_task_stories(self, task_id: str) -> List[Dict]:
        """Return comments and attachment-added events for *task_id*."""
        stories = self._get_paginated(
            f"tasks/{task_id}/stories",
            {"opt_fields": STORY_OPT_FIELDS},
        )
        return [s for s in stories if s.get("type") in ("comment", "attachment_added")]

    def get_task_subtasks(self, task_id: str) -> List[Dict]:
        """Return direct subtasks of *task_id*."""
        return self._get_paginated(
            f"tasks/{task_id}/subtasks",
            {"opt_fields": SUBTASK_OPT_FIELDS},
        )

    def get_project_sections(self, project_id: str) -> List[Dict]:
        """Return all sections in *project_id*."""
        return self._get_paginated(
            f"projects/{project_id}/sections",
            {"opt_fields": "gid,name,created_at"},
        )

    def get_attachment_details(self, attachment_id: str) -> Optional[Dict]:
        """Return full metadata for *attachment_id*, or ``None``."""
        response = self._api_request(
            f"attachments/{attachment_id}",
            params={"opt_fields": "name,download_url,url,size,created_at"},
        )
        if response and "data" in response:
            return response["data"]
        return None

    # ------------------------------------------------------------------
    # Attachment download
    # ------------------------------------------------------------------

    def download_attachment(
        self,
        attachment: Dict,
        project_folder: Path,
        state_cache: Dict[str, str],
    ) -> Optional[str]:
        """Download *attachment* to *project_folder*/attachments/ and return
        its relative path.

        Args:
            attachment:   Minimal attachment dict (must contain ``"gid"``).
            project_folder: Root folder of the project being exported.
            state_cache:  The ``downloaded_attachments`` dict from
                          ``ExportState``; consulted for deduplication and
                          updated on success.

        Returns:
            Relative path string ``"attachments/<filename>"`` on success,
            ``None`` on failure.
        """
        attachment_id = attachment.get("gid")
        if not attachment_id:
            return None

        # Deduplication: already downloaded in a previous run
        if attachment_id in state_cache:
            return state_cache[attachment_id]

        details = self.get_attachment_details(attachment_id)
        if not details:
            logger.warning("Could not fetch details for attachment %s", attachment_id)
            return None

        url = details.get("download_url") or details.get("url")
        if not url:
            logger.warning("No download URL for attachment %s", attachment_id)
            return None

        attachments_folder = project_folder / "attachments"
        attachments_folder.mkdir(parents=True, exist_ok=True)

        filename = details.get("name") or f"attachment_{attachment_id}"
        filename = self._resolve_filename(filename, attachment_id, url)
        filename = sanitize_filename(filename)

        file_path = ensure_unique_path(attachments_folder / filename)

        try:
            logger.debug("Downloading attachment: %s", filename)
            response = self._download_with_retry(url)
            if response is None:
                return None

            with open(file_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=ATTACHMENT_CHUNK_SIZE):
                    if chunk:
                        f.write(chunk)

            relative_path = f"attachments/{file_path.name}"
            state_cache[attachment_id] = relative_path
            logger.info(
                "Downloaded: %s (%d bytes)", filename, file_path.stat().st_size
            )
            return relative_path

        except Exception as exc:
            logger.error("Failed to download attachment %s: %s", filename, exc)
            return None

    def _resolve_filename(self, filename: str, attachment_id: str, url: str) -> str:
        """Determine a filename for an attachment, using URL or Content-Type as fallback."""
        if filename and "." in filename:
            return filename

        # Try URL path component
        parsed = urlparse(url)
        url_part = parsed.path.split("/")[-1] if parsed.path else ""
        if url_part and "." in url_part:
            return url_part

        # HEAD request to infer content-type
        try:
            head = self._head_with_retry(url)
            if not head:
                return f"attachment_{attachment_id}.bin"
            content_type = head.headers.get("content-type", "")
            for ct, ext in CONTENT_TYPE_MAP.items():
                if ct in content_type:
                    return f"{attachment_id}{ext}"
        except Exception as exc:
            logger.debug("Could not determine extension for %s: %s", attachment_id, exc)

        return f"attachment_{attachment_id}.bin"

    def _download_with_retry(self, url: str) -> Optional[requests.Response]:
        attempts = 0
        while True:
            time.sleep(RATE_LIMIT_DELAY)
            try:
                response = self._session.get(
                    url,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    stream=True,
                )
            except requests.exceptions.RequestException as exc:
                logger.error("Attachment download request failed: %s", exc)
                return None

            if response.status_code == 429:
                attempts += 1
                if attempts > RATE_LIMIT_MAX_RETRIES:
                    logger.error("Attachment download rate-limited after retries.")
                    return None
                sleep_time = self._retry_after_seconds(response.headers.get("Retry-After"), attempts)
                logger.warning(
                    "Rate limited downloading attachment (attempt %d/%d). Sleeping %.2fs.",
                    attempts,
                    RATE_LIMIT_MAX_RETRIES,
                    sleep_time,
                )
                time.sleep(sleep_time)
                continue

            try:
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException as exc:
                logger.error("Attachment download failed: %s", exc)
                return None

    def _head_with_retry(self, url: str) -> Optional[requests.Response]:
        attempts = 0
        while True:
            time.sleep(RATE_LIMIT_DELAY)
            try:
                response = self._session.head(
                    url,
                    timeout=HEAD_REQUEST_TIMEOUT,
                    allow_redirects=True,
                )
            except requests.exceptions.RequestException as exc:
                logger.debug("HEAD request failed: %s", exc)
                return None

            if response.status_code == 429:
                attempts += 1
                if attempts > RATE_LIMIT_MAX_RETRIES:
                    logger.debug("HEAD request rate-limited after retries.")
                    return None
                sleep_time = self._retry_after_seconds(response.headers.get("Retry-After"), attempts)
                time.sleep(sleep_time)
                continue

            try:
                response.raise_for_status()
                return response
            except requests.exceptions.RequestException:
                return None

    def _retry_after_seconds(self, retry_after: Optional[str], attempts: int) -> float:
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass
        return min(
            RATE_LIMIT_BACKOFF_MAX,
            RATE_LIMIT_BACKOFF_BASE * (2 ** (attempts - 1)),
        )

    # ------------------------------------------------------------------
    # Destructive / write endpoints (used by VaultCleanup)
    # ------------------------------------------------------------------

    def delete_task(self, task_id: str) -> bool:
        """Permanently delete *task_id* from Asana.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        result = self._api_request(f"tasks/{task_id}", method="DELETE")
        # DELETE returns an empty envelope ``{"data": {}}`` on success
        if result is not None:
            logger.info("Deleted Asana task %s.", task_id)
            return True
        logger.error("Failed to delete Asana task %s.", task_id)
        return False

    def remove_task_from_project(self, task_id: str, project_id: str) -> bool:
        """Remove *task_id* from *project_id* without deleting the task.

        Returns:
            ``True`` on success, ``False`` on failure.
        """
        result = self._api_request(
            f"tasks/{task_id}/removeProject",
            method="POST",
            data={"data": {"project": project_id}},
        )
        if result is not None:
            logger.info("Removed task %s from project %s.", task_id, project_id)
            return True
        logger.error("Failed to remove task %s from project %s.", task_id, project_id)
        return False
