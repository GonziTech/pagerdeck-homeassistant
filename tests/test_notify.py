"""Tests for sending and resolving through the notify entity."""

import json

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
import voluptuous as vol

from custom_components.pagerdeck.const import DOMAIN

from .conftest import API_KEY, API_URL

PUSH_URL = f"{API_URL}/v1/push"
RESOLVE_URL = f"{API_URL}/v1/resolve"
ENTITY_ID = "notify.pagerdeck"
ACCEPTED = {
    "message_id": "10aa2f31-29f7-4429-94cb-d69cb7bb3227",
    "level": "high",
    "deduplicated": False,
    "queued": 1,
    "devices": 1,
}


@pytest.fixture
async def entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
) -> MockConfigEntry:
    """Set the entry up, after the HTTP mock replaced the shared session."""
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.LOADED
    return mock_config_entry


def _last_payload(aioclient_mock: AiohttpClientMocker) -> dict:
    """Return the JSON body of the latest request."""
    data = aioclient_mock.mock_calls[-1][2]
    return data if isinstance(data, dict) else json.loads(data)


@pytest.mark.usefixtures("entry")
async def test_notify_send_message(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """notify.send_message maps message and title onto body and title."""
    aioclient_mock.post(PUSH_URL, status=202, json=ACCEPTED)

    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": ENTITY_ID, "message": "/ is 94% full", "title": "Disk full"},
        blocking=True,
    )

    method, url, data, headers = aioclient_mock.mock_calls[0]
    assert (method, str(url)) == ("POST", PUSH_URL)
    assert data == {"title": "Disk full", "body": "/ is 94% full"}
    assert headers["Authorization"] == f"Bearer {API_KEY}"


@pytest.mark.usefixtures("entry")
async def test_notify_without_title_uses_message_as_title(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The API requires a title, so a message without one becomes the title."""
    aioclient_mock.post(PUSH_URL, status=202, json=ACCEPTED)

    await hass.services.async_call(
        "notify",
        "send_message",
        {"entity_id": ENTITY_ID, "message": "Door open"},
        blocking=True,
    )

    assert _last_payload(aioclient_mock) == {"title": "Door open"}


@pytest.mark.usefixtures("entry")
async def test_send_alert_full_payload(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """send_alert passes severity, tags, dedup key, url and ttl."""
    aioclient_mock.post(PUSH_URL, status=202, json=ACCEPTED)

    await hass.services.async_call(
        DOMAIN,
        "send_alert",
        {
            "entity_id": ENTITY_ID,
            "title": "Disk full on web-01",
            "message": "/ is 94% full",
            "severity": "error",
            "tags": ["prod", "disk"],
            "dedup_key": "web-01:disk",
            "url": "https://status.example.com/web-01",
            "ttl": {"minutes": 30},
        },
        blocking=True,
    )

    assert _last_payload(aioclient_mock) == {
        "title": "Disk full on web-01",
        "body": "/ is 94% full",
        "severity": "error",
        "tags": ["prod", "disk"],
        "dedup_key": "web-01:disk",
        "url": "https://status.example.com/web-01",
        "ttl": 1800,
    }


@pytest.mark.usefixtures("entry")
async def test_long_text_is_cut_to_api_limits(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Title and body are cut to byte limits without splitting a character."""
    aioclient_mock.post(PUSH_URL, status=202, json=ACCEPTED)

    await hass.services.async_call(
        DOMAIN,
        "send_alert",
        {"entity_id": ENTITY_ID, "title": "ü" * 200, "message": "x" * 9000},
        blocking=True,
    )

    payload = _last_payload(aioclient_mock)
    assert len(payload["title"].encode()) == 250
    assert len(payload["body"].encode()) == 8192


@pytest.mark.usefixtures("entry")
@pytest.mark.parametrize(
    "bad",
    [
        {"severity": "fatal"},
        {"url": "javascript:alert(1)"},
        {"url": "ftp://example.com/x"},
        {"dedup_key": "a\nb"},
        {"dedup_key": "k" * 201},
        {"tags": ["t"] * 21},
        {"tags": ["t" * 65]},
        {"ttl": {"seconds": 0}},
        {"ttl": {"days": 31}},
    ],
)
async def test_send_alert_rejects_invalid_input(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, bad: dict
) -> None:
    """Input the API would reject is refused before any request is made."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "send_alert",
            {"entity_id": ENTITY_ID, "message": "x", **bad},
            blocking=True,
        )
    assert aioclient_mock.call_count == 0


@pytest.mark.usefixtures("entry")
async def test_resolve(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """resolve posts the dedup key to /v1/resolve."""
    aioclient_mock.post(RESOLVE_URL, status=200, json={"id": "x"})

    await hass.services.async_call(
        DOMAIN,
        "resolve",
        {"entity_id": ENTITY_ID, "dedup_key": "web-01:disk"},
        blocking=True,
    )

    assert _last_payload(aioclient_mock) == {"dedup_key": "web-01:disk"}


@pytest.mark.usefixtures("entry")
async def test_resolve_unknown_incident(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 404 from resolve surfaces as a validation error."""
    aioclient_mock.post(RESOLVE_URL, status=404, json={"error": "not_found"})

    with pytest.raises(ServiceValidationError, match="No open incident"):
        await hass.services.async_call(
            DOMAIN,
            "resolve",
            {"entity_id": ENTITY_ID, "dedup_key": "gone"},
            blocking=True,
        )


@pytest.mark.parametrize(
    ("mock_kwargs", "exception", "message"),
    [
        (
            {"status": 402, "json": {"error": "payment_required"}},
            HomeAssistantError,
            "no entitlement",
        ),
        (
            {
                "status": 429,
                "json": {"error": "rate_limited"},
                "headers": {"Retry-After": "7"},
            },
            HomeAssistantError,
            "after 7 seconds",
        ),
        (
            {"status": 400, "json": {"error": "invalid_request", "message": "bad"}},
            ServiceValidationError,
            "rejected the request: bad",
        ),
        ({"status": 503}, HomeAssistantError, "Could not reach"),
        ({"exc": aiohttp.ClientError}, HomeAssistantError, "Could not reach"),
        ({"exc": TimeoutError}, HomeAssistantError, "Could not reach"),
    ],
)
@pytest.mark.usefixtures("entry")
async def test_send_errors(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict,
    exception: type[Exception],
    message: str,
) -> None:
    """API failures become translated Home Assistant errors."""
    aioclient_mock.post(PUSH_URL, **mock_kwargs)

    with pytest.raises(exception, match=message):
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": ENTITY_ID, "message": "x"},
            blocking=True,
        )


@pytest.mark.usefixtures("entry")
async def test_rejected_key_starts_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A 401 on send raises and opens a reauth flow."""
    aioclient_mock.post(PUSH_URL, status=401, json={"error": "unauthorized"})

    with pytest.raises(HomeAssistantError, match="rejected the ingest key"):
        await hass.services.async_call(
            "notify",
            "send_message",
            {"entity_id": ENTITY_ID, "message": "x"},
            blocking=True,
        )
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """The entry unloads cleanly."""
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
