"""Constants for the PagerDeck integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pagerdeck"

CONF_API_KEY: Final = "api_key"
CONF_URL: Final = "url"

DEFAULT_URL: Final = "https://api.pagerdeck.com"

ATTR_SEVERITY: Final = "severity"
ATTR_TAGS: Final = "tags"
ATTR_DEDUP_KEY: Final = "dedup_key"
ATTR_URL: Final = "url"
ATTR_TTL: Final = "ttl"

SERVICE_SEND_ALERT: Final = "send_alert"
SERVICE_RESOLVE: Final = "resolve"

SEVERITIES: Final = ("info", "warning", "error", "critical")

# Limits taken from the PagerDeck API reference for POST /v1/push.
MAX_TITLE_BYTES: Final = 250
MAX_BODY_BYTES: Final = 8192
MAX_TAGS: Final = 20
MAX_TAG_BYTES: Final = 64
MAX_DEDUP_KEY_BYTES: Final = 200
