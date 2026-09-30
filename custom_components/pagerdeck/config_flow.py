"""Config flow for the PagerDeck integration."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
import voluptuous as vol
from yarl import URL

from .api import (
    PagerDeckAuthError,
    PagerDeckClient,
    PagerDeckConnectionError,
    PagerDeckError,
    PagerDeckRateLimitError,
)
from .const import CONF_API_KEY, CONF_URL, DEFAULT_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

KEY_SELECTOR = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _normalize_url(value: str) -> str | None:
    """Return the URL without trailing slash, or None if it is not http(s)."""
    try:
        url = URL(value.strip())
    except ValueError:
        return None
    if url.scheme not in ("http", "https") or not url.host or url.query_string:
        return None
    return str(url).rstrip("/")


def _unique_id(api_key: str) -> str:
    """Derive a stable id from the key without storing it twice in clear."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:32]


class PagerDeckConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the UI setup of one PagerDeck source."""

    VERSION = 1

    async def _validate(self, api_key: str, url: str) -> str | None:
        """Return an error key, or None when the key is accepted."""
        client = PagerDeckClient(async_get_clientsession(self.hass), api_key, url)
        try:
            await client.validate()
        except PagerDeckAuthError:
            return "invalid_auth"
        except (PagerDeckConnectionError, PagerDeckRateLimitError):
            return "cannot_connect"
        except PagerDeckError:
            _LOGGER.exception("Unexpected PagerDeck error during validation")
            return "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the ingest key and check it."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            url = _normalize_url(user_input[CONF_URL])
            if not api_key:
                errors[CONF_API_KEY] = "invalid_auth"
            elif url is None:
                errors[CONF_URL] = "invalid_url"
            else:
                await self.async_set_unique_id(_unique_id(api_key))
                self._abort_if_unique_id_configured()
                if (error := await self._validate(api_key, url)) is None:
                    return self.async_create_entry(
                        title="PagerDeck",
                        data={CONF_API_KEY: api_key, CONF_URL: url},
                    )
                errors["base"] = error

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): KEY_SELECTOR,
                    vol.Optional(
                        CONF_URL,
                        default=(user_input or {}).get(CONF_URL, DEFAULT_URL),
                    ): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start re-authentication after the API rejected the key."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new ingest key for the existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            if not api_key:
                errors[CONF_API_KEY] = "invalid_auth"
            elif (error := await self._validate(api_key, entry.data[CONF_URL])) is None:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=_unique_id(api_key),
                    data_updates={CONF_API_KEY: api_key},
                )
            else:
                errors["base"] = error

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): KEY_SELECTOR}),
            errors=errors,
        )
