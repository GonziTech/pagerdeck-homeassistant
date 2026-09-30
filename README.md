# PagerDeck for Home Assistant

Send alerts from Home Assistant to [PagerDeck](https://pagerdeck.com). The
integration adds a `notify` entity and two actions: `pagerdeck.send_alert` and
`pagerdeck.resolve`.

## Installation with HACS

1. In HACS open the menu and choose **Custom repositories**.
2. Add `https://github.com/GonziTech/pagerdeck-homeassistant` with the category
   **Integration**.
3. Search for **PagerDeck**, download it and restart Home Assistant.
4. Go to **Settings > Devices & services > Add integration** and pick
   **PagerDeck**.

Requires Home Assistant 2026.2.0 or newer.

## Setup

Create a source in the PagerDeck dashboard and copy its ingest key
(`src_live_...`). The key is shown once. Paste it into the setup dialog. The key
is checked against the API without sending an alert and without using quota.

Each ingest key is one entry. Add the integration again to connect more sources.
If PagerDeck rejects the key later, Home Assistant starts a reauthentication.

The **API URL** field defaults to `https://api.pagerdeck.com`. Change it only for
a self-hosted or local API.

## Notify entity

The entity is `notify.pagerdeck`. `notify.send_message` sends `title` as the
alert title and `message` as the body. Without a title, the message becomes the
title, because PagerDeck requires one.

## Actions

### `pagerdeck.send_alert`

| Field | Required | Description |
|---|---|---|
| `message` | yes | Body of the alert |
| `title` | no | Headline, up to 250 bytes |
| `severity` | no | `info`, `warning`, `error` or `critical`. Without it the default of the source applies |
| `tags` | no | Up to 20 tags of at most 64 bytes |
| `dedup_key` | no | Keeps an incident together. While it is open, the same key updates the first alert instead of creating a new one |
| `url` | no | Link opened by the app, `http` or `https` only |
| `ttl` | no | Delivery deadline and auto-resolve, 1 second to 30 days |

Whether `critical` breaks through Focus and the mute switch is decided by the
receiving device, not by Home Assistant.

### `pagerdeck.resolve`

Closes the incident that was opened with a `dedup_key`. Resolving a key that has
no open incident fails with an error, as the API answers 404.

## Example automation

```yaml
automation:
  - alias: "Freezer too warm"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.freezer_temperature
        above: -10
        for: "00:10:00"
    actions:
      - action: pagerdeck.send_alert
        target:
          entity_id: notify.pagerdeck
        data:
          title: "Freezer too warm"
          message: "{{ states('sensor.freezer_temperature') }} C for 10 minutes"
          severity: error
          tags: [home, freezer]
          dedup_key: freezer-temperature

  - alias: "Freezer back to normal"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.freezer_temperature
        below: -15
    actions:
      - action: pagerdeck.resolve
        target:
          entity_id: notify.pagerdeck
        data:
          dedup_key: freezer-temperature
```

If the incident was already closed in the dashboard, the second automation fails
with "No open incident exists". Add `continue_on_error: true` to the action if
that is expected.

## Limits and errors

- Messages longer than the API limits are cut at a character boundary: title
  250 bytes, body 8192 bytes.
- Requests time out after 30 seconds. Nothing is retried, so a failed action
  never produces a second alert.
- An account without entitlement (HTTP 402) and a source over its rate limit
  (HTTP 429) raise an error that names the reason.
- The ingest key is stored in the config entry and is never written to logs.

## Development

```sh
./scripts/test.sh
```

runs `ruff` and `pytest` in a `python:3.13` container.

## License

MIT
