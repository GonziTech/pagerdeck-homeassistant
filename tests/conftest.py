"""Shared fixtures for the PagerDeck tests."""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pagerdeck.const import CONF_API_KEY, CONF_URL, DOMAIN

API_URL = "https://api.pagerdeck.com"
API_KEY = "src_live_" + "A" * 43


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow Home Assistant to load the integration under test."""


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a configured PagerDeck entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="PagerDeck",
        data={CONF_API_KEY: API_KEY, CONF_URL: API_URL},
        unique_id="existing",
    )


@pytest.fixture
def mock_setup_entry() -> Generator[None]:
    """Skip the real setup while the config flow is tested."""
    with patch("custom_components.pagerdeck.async_setup_entry", return_value=True):
        yield
