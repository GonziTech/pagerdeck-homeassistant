"""The PagerDeck integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import PagerDeckClient
from .const import CONF_API_KEY, CONF_URL

PLATFORMS: list[Platform] = [Platform.NOTIFY]

type PagerDeckConfigEntry = ConfigEntry[PagerDeckClient]


async def async_setup_entry(hass: HomeAssistant, entry: PagerDeckConfigEntry) -> bool:
    """Set up PagerDeck from a config entry."""
    entry.runtime_data = PagerDeckClient(
        async_get_clientsession(hass),
        entry.data[CONF_API_KEY],
        entry.data[CONF_URL],
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PagerDeckConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
