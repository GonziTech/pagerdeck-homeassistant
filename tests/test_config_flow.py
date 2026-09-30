"""Tests for the PagerDeck config flow."""

import aiohttp
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.pagerdeck.const import CONF_API_KEY, CONF_URL, DOMAIN

from .conftest import API_KEY, API_URL

RESOLVE_URL = f"{API_URL}/v1/resolve"


async def _start(hass: HomeAssistant) -> dict:
    """Open the user step."""
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_success(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A key the API accepts creates an entry; the probe is a resolve call."""
    aioclient_mock.post(RESOLVE_URL, status=404, json={"error": "not_found"})

    result = await _start(hass)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: f" {API_KEY} ", CONF_URL: f"{API_URL}/"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: API_KEY, CONF_URL: API_URL}
    _, url, data, headers = aioclient_mock.mock_calls[0]
    assert str(url) == RESOLVE_URL
    assert data == {"dedup_key": "homeassistant-key-check"}
    assert headers["Authorization"] == f"Bearer {API_KEY}"


@pytest.mark.parametrize(
    ("mock_kwargs", "error"),
    [
        ({"status": 401, "json": {"error": "unauthorized"}}, "invalid_auth"),
        ({"status": 503, "json": {"error": "service_unavailable"}}, "cannot_connect"),
        ({"exc": aiohttp.ClientError}, "cannot_connect"),
        ({"exc": TimeoutError}, "cannot_connect"),
        ({"status": 400, "json": {"error": "invalid_request"}}, "unknown"),
    ],
)
@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_errors_then_recovery(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_kwargs: dict,
    error: str,
) -> None:
    """Each failure shows an error, and the same form can still succeed."""
    aioclient_mock.post(RESOLVE_URL, **mock_kwargs)
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_URL: API_URL}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": error}

    aioclient_mock.clear_requests()
    aioclient_mock.post(RESOLVE_URL, status=404, json={"error": "not_found"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_URL: API_URL}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize("url", ["ftp://example.com", "not a url", "https://"])
async def test_user_flow_invalid_url(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, url: str
) -> None:
    """A URL that is not http(s) is rejected before any request is made."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: API_KEY, CONF_URL: url}
    )
    assert result["errors"] == {CONF_URL: "invalid_url"}
    assert aioclient_mock.call_count == 0


async def test_user_flow_blank_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A blank key never reaches the API."""
    result = await _start(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "   ", CONF_URL: API_URL}
    )
    assert result["errors"] == {CONF_API_KEY: "invalid_auth"}
    assert aioclient_mock.call_count == 0


@pytest.mark.usefixtures("mock_setup_entry")
async def test_user_flow_duplicate_key(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The same key cannot be added twice."""
    aioclient_mock.post(RESOLVE_URL, status=404, json={"error": "not_found"})
    for expected in (FlowResultType.CREATE_ENTRY, FlowResultType.ABORT):
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: API_KEY, CONF_URL: API_URL}
        )
        assert result["type"] is expected
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("mock_setup_entry")
async def test_reauth_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
) -> None:
    """Reauth replaces the key on the existing entry."""
    mock_config_entry.add_to_hass(hass)
    new_key = "src_live_" + "B" * 43
    aioclient_mock.post(RESOLVE_URL, status=401, json={"error": "unauthorized"})

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: new_key}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.post(RESOLVE_URL, status=404, json={"error": "not_found"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: new_key}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_API_KEY] == new_key
