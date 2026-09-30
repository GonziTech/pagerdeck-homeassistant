"""Async client for the PagerDeck ingest API."""

from __future__ import annotations

from http import HTTPStatus
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Key used to check an ingest key without creating an alert or counting
# against the quota. A resolve for an unknown incident answers 404 once the
# key itself was accepted.
_PROBE_DEDUP_KEY = "homeassistant-key-check"


class PagerDeckError(Exception):
    """Base class for all PagerDeck client errors."""


class PagerDeckAuthError(PagerDeckError):
    """The ingest key is missing, unknown or expired."""


class PagerDeckConnectionError(PagerDeckError):
    """The API could not be reached or answered with a server error."""


class PagerDeckPaymentError(PagerDeckError):
    """The account has no entitlement to send alerts (HTTP 402)."""


class PagerDeckRateLimitError(PagerDeckError):
    """The rate limit or the quota was hit (HTTP 429)."""

    def __init__(self, retry_after: int | None) -> None:
        """Store the number of seconds to wait, when the API gave one."""
        super().__init__("rate limited")
        self.retry_after = retry_after


class PagerDeckNotFoundError(PagerDeckError):
    """No open incident exists for the given dedup key (HTTP 404)."""


class PagerDeckRequestError(PagerDeckError):
    """The API rejected the request as invalid (HTTP 400 and other 4xx)."""

    def __init__(self, message: str) -> None:
        """Store the developer message returned by the API."""
        super().__init__(message)
        self.message = message


class PagerDeckClient:
    """Thin client for POST /v1/push and POST /v1/resolve."""

    def __init__(
        self, session: aiohttp.ClientSession, api_key: str, base_url: str
    ) -> None:
        """Initialize the client with the shared HA session."""
        self._session = session
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a JSON payload and map error responses to exceptions.

        The key only travels in the Authorization header and is never logged.
        """
        try:
            async with self._session.post(
                f"{self._base_url}{path}",
                json=payload,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=REQUEST_TIMEOUT,
                allow_redirects=False,
            ) as response:
                status = response.status
                retry_after = response.headers.get("Retry-After")
                body = await self._read_json(response)
        except TimeoutError as err:
            raise PagerDeckConnectionError("timeout") from err
        except aiohttp.ClientError as err:
            raise PagerDeckConnectionError("connection failed") from err

        if status in (HTTPStatus.OK, HTTPStatus.ACCEPTED):
            return body
        _LOGGER.debug("PagerDeck %s answered HTTP %s", path, status)
        if status == HTTPStatus.UNAUTHORIZED:
            raise PagerDeckAuthError
        if status == HTTPStatus.PAYMENT_REQUIRED:
            raise PagerDeckPaymentError
        if status == HTTPStatus.NOT_FOUND:
            raise PagerDeckNotFoundError
        if status == HTTPStatus.TOO_MANY_REQUESTS:
            raise PagerDeckRateLimitError(
                int(retry_after) if retry_after and retry_after.isdigit() else None
            )
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise PagerDeckConnectionError(f"server error {status}")
        message = body.get("message") if isinstance(body.get("message"), str) else ""
        raise PagerDeckRequestError(message or f"HTTP {status}")

    @staticmethod
    async def _read_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
        """Read a JSON object body, tolerating empty or non-JSON bodies."""
        try:
            data = await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    async def push(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send an alert. Returns message_id, deduplicated, queued, devices."""
        return await self._post("/v1/push", payload)

    async def resolve(self, dedup_key: str) -> dict[str, Any]:
        """Close the open incident that carries this dedup key."""
        return await self._post("/v1/resolve", {"dedup_key": dedup_key})

    async def validate(self) -> None:
        """Check that the key is accepted, without sending an alert.

        Raises PagerDeckAuthError for a bad key and PagerDeckConnectionError
        when the API is unreachable. A payment error still proves the key is
        valid, so it is not treated as a failure here.
        """
        try:
            await self.resolve(_PROBE_DEDUP_KEY)
        except (PagerDeckNotFoundError, PagerDeckPaymentError):
            return
