"""Notify platform and entity services for PagerDeck."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
import logging
import re
from typing import Any

from homeassistant.components.notify import (
    ATTR_MESSAGE,
    ATTR_TITLE,
    NotifyEntity,
    NotifyEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
import voluptuous as vol

from . import PagerDeckConfigEntry
from .api import (
    PagerDeckAuthError,
    PagerDeckClient,
    PagerDeckConnectionError,
    PagerDeckError,
    PagerDeckNotFoundError,
    PagerDeckPaymentError,
    PagerDeckRateLimitError,
    PagerDeckRequestError,
)
from .const import (
    ATTR_DEDUP_KEY,
    ATTR_SEVERITY,
    ATTR_TAGS,
    ATTR_TTL,
    ATTR_URL,
    DOMAIN,
    MAX_BODY_BYTES,
    MAX_DEDUP_KEY_BYTES,
    MAX_TAG_BYTES,
    MAX_TAGS,
    MAX_TITLE_BYTES,
    SERVICE_RESOLVE,
    SERVICE_SEND_ALERT,
    SEVERITIES,
)

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 1

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def _max_bytes(limit: int) -> Callable[[Any], str]:
    """Return a validator that rejects strings longer than limit UTF-8 bytes."""

    def validate(value: Any) -> str:
        text = cv.string(value)
        if len(text.encode()) > limit:
            raise vol.Invalid(f"must be at most {limit} bytes")
        return text

    return validate


def _dedup_key(value: Any) -> str:
    """Validate a dedup key: non-empty, bounded, free of control characters."""
    text = _max_bytes(MAX_DEDUP_KEY_BYTES)(value)
    if not text or _CONTROL_CHARS.search(text):
        raise vol.Invalid("must not be empty or contain control characters")
    return text


def _http_url(value: Any) -> str:
    """Validate that a link uses http or https, as the API requires."""
    text = cv.string(value).strip()
    if not text.lower().startswith(("http://", "https://")):
        raise vol.Invalid("must start with http:// or https://")
    return cv.url(text)


def _ttl(value: Any) -> int:
    """Validate a duration between 1 second and 30 days, return seconds."""
    period = cv.time_period(value)
    if not timedelta(seconds=1) <= period <= timedelta(days=30):
        raise vol.Invalid("must be between 1 second and 30 days")
    return int(period.total_seconds())


SEND_ALERT_SCHEMA = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_TITLE): cv.string,
        vol.Optional(ATTR_SEVERITY): vol.In(SEVERITIES),
        vol.Optional(ATTR_TAGS): vol.All(
            cv.ensure_list, vol.Length(max=MAX_TAGS), [_max_bytes(MAX_TAG_BYTES)]
        ),
        vol.Optional(ATTR_DEDUP_KEY): _dedup_key,
        vol.Optional(ATTR_URL): _http_url,
        vol.Optional(ATTR_TTL): _ttl,
    }
)

RESOLVE_SCHEMA = cv.make_entity_service_schema(
    {vol.Required(ATTR_DEDUP_KEY): _dedup_key}
)


def _truncate(text: str, limit: int) -> str:
    """Cut text to at most limit UTF-8 bytes without splitting a character."""
    raw = text.encode()
    if len(raw) <= limit:
        return text
    return raw[:limit].decode(errors="ignore")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PagerDeckConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the PagerDeck notify entity and its services."""
    async_add_entities([PagerDeckNotifyEntity(entry)])

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SEND_ALERT, SEND_ALERT_SCHEMA, "async_send_alert"
    )
    platform.async_register_entity_service(
        SERVICE_RESOLVE, RESOLVE_SCHEMA, "async_resolve"
    )


class PagerDeckNotifyEntity(NotifyEntity):
    """Notify entity that sends alerts to one PagerDeck source."""

    entity_description = NotifyEntityDescription(key="alert", translation_key="alert")
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: PagerDeckConfigEntry) -> None:
        """Initialize the entity from its config entry."""
        self._entry = entry
        self._client: PagerDeckClient = entry.runtime_data
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            entry_type=DeviceEntryType.SERVICE,
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="PagerDeck",
            name="PagerDeck",
        )

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        """Send a message as an alert without severity or tags."""
        await self.async_send_alert(message=message, title=title)

    async def async_send_alert(
        self,
        message: str,
        title: str | None = None,
        severity: str | None = None,
        tags: list[str] | None = None,
        dedup_key: str | None = None,
        url: str | None = None,
        ttl: int | None = None,
    ) -> None:
        """Send an alert. The API needs a title, so the message fills in for it."""
        payload: dict[str, Any] = {}
        if title:
            payload["title"] = _truncate(title, MAX_TITLE_BYTES)
            payload["body"] = _truncate(message, MAX_BODY_BYTES)
        else:
            payload["title"] = _truncate(message, MAX_TITLE_BYTES)
        optional = {
            ATTR_SEVERITY: severity,
            ATTR_TAGS: tags,
            ATTR_DEDUP_KEY: dedup_key,
            ATTR_URL: url,
            ATTR_TTL: ttl,
        }
        payload.update({key: value for key, value in optional.items() if value})
        await self._call(self._client.push(payload))

    async def async_resolve(self, dedup_key: str) -> None:
        """Close the open incident that carries this dedup key."""
        await self._call(self._client.resolve(dedup_key))

    async def _call(self, request: Awaitable[Any]) -> None:
        """Await an API call and translate client errors for the caller."""
        try:
            await request
        except PagerDeckAuthError as err:
            self._entry.async_start_reauth(self.hass)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="invalid_auth"
            ) from err
        except PagerDeckPaymentError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="payment_required"
            ) from err
        except PagerDeckRateLimitError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                translation_placeholders={"retry_after": str(err.retry_after or "?")},
            ) from err
        except PagerDeckNotFoundError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="incident_not_found"
            ) from err
        except PagerDeckRequestError as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_request",
                translation_placeholders={"message": err.message},
            ) from err
        except PagerDeckConnectionError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="cannot_connect"
            ) from err
        except PagerDeckError as err:
            _LOGGER.exception("Unexpected PagerDeck error")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="cannot_connect"
            ) from err
