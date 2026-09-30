# Security policy

## Reporting a vulnerability

Please do not open a public issue for security problems.

Report it privately through GitHub: **Security > Report a vulnerability** in this
repository, or by email to support [at] pagerdeck [dot] com.

We acknowledge reports within three working days and keep you informed until the
issue is resolved.

## Scope

This repository contains the Home Assistant integration only. Issues in the
PagerDeck service itself can be reported the same way.

## Handling of secrets

The integration stores the PagerDeck ingest key in the Home Assistant config
entry and never writes it to logs. Rotate a key you suspect to be exposed in the
PagerDeck dashboard under Sources.
