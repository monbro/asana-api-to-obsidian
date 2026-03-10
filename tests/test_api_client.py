"""Tests for src.api.client.AsanaApiClient."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.api.client import AsanaApiClient


@pytest.fixture
def client() -> AsanaApiClient:
    return AsanaApiClient(token="test_token_1/xyz")


class TestAuthHeader:
    def test_bearer_token_in_session_headers(self, client: AsanaApiClient) -> None:
        assert client._session.headers["Authorization"] == "Bearer test_token_1/xyz"

    def test_accept_json_in_session_headers(self, client: AsanaApiClient) -> None:
        assert client._session.headers["Accept"] == "application/json"


class TestRateLimiting:
    @patch("src.api.client.time.sleep")
    @patch.object(requests.Session, "request")
    def test_sleep_called_before_request(
        self, mock_request: MagicMock, mock_sleep: MagicMock, client: AsanaApiClient
    ) -> None:
        """A ``time.sleep`` call must precede every API request."""
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"data": {"gid": "1", "name": "user"}}
        mock_request.return_value = mock_response

        client._api_request("users/me")
        mock_sleep.assert_called_once()


class TestHttpErrorHandling:
    @patch("src.api.client.time.sleep")
    @patch.object(requests.Session, "request")
    def test_http_error_returns_none(
        self, mock_request: MagicMock, mock_sleep: MagicMock, client: AsanaApiClient
    ) -> None:
        """A 4xx/5xx response must return ``None``, not raise."""
        mock_request.side_effect = requests.exceptions.HTTPError("403 Forbidden")
        result = client._api_request("users/me")
        assert result is None

    @patch("src.api.client.time.sleep")
    @patch.object(requests.Session, "request")
    def test_connection_error_returns_none(
        self, mock_request: MagicMock, mock_sleep: MagicMock, client: AsanaApiClient
    ) -> None:
        mock_request.side_effect = requests.exceptions.ConnectionError()
        result = client._api_request("users/me")
        assert result is None


class TestPagination:
    @patch("src.api.client.time.sleep")
    @patch.object(requests.Session, "request")
    def test_follows_offset_token(
        self, mock_request: MagicMock, mock_sleep: MagicMock, client: AsanaApiClient
    ) -> None:
        """Pagination must follow ``next_page.offset`` until it is absent."""
        page1 = MagicMock()
        page1.raise_for_status.return_value = None
        page1.json.return_value = {
            "data": [{"gid": "1"}],
            "next_page": {"offset": "abc123"},
        }
        page2 = MagicMock()
        page2.raise_for_status.return_value = None
        page2.json.return_value = {
            "data": [{"gid": "2"}],
            "next_page": None,
        }
        mock_request.side_effect = [page1, page2]

        results = client._get_paginated("projects")
        assert len(results) == 2
        assert results[0]["gid"] == "1"
        assert results[1]["gid"] == "2"

    @patch("src.api.client.time.sleep")
    @patch.object(requests.Session, "request")
    def test_stops_on_missing_next_page(
        self, mock_request: MagicMock, mock_sleep: MagicMock, client: AsanaApiClient
    ) -> None:
        page = MagicMock()
        page.raise_for_status.return_value = None
        page.json.return_value = {"data": [{"gid": "1"}]}
        mock_request.return_value = page

        results = client._get_paginated("projects")
        assert len(results) == 1
        assert mock_request.call_count == 1


class TestGetUserInfo:
    @patch("src.api.client.time.sleep")
    @patch.object(requests.Session, "request")
    def test_returns_user_dict(
        self, mock_request: MagicMock, mock_sleep: MagicMock, client: AsanaApiClient
    ) -> None:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "data": {"gid": "user_1", "name": "Alice", "workspaces": [{"gid": "ws_1", "name": "WS"}]}
        }
        mock_request.return_value = mock_response

        user = client.get_user_info()
        assert user is not None
        assert user["name"] == "Alice"

    @patch("src.api.client.time.sleep")
    @patch.object(requests.Session, "request")
    def test_returns_none_on_failure(
        self, mock_request: MagicMock, mock_sleep: MagicMock, client: AsanaApiClient
    ) -> None:
        mock_request.side_effect = requests.exceptions.ConnectionError()
        assert client.get_user_info() is None
