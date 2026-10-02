# Security Policy

## Your data stays on your machine

Notion Better Export talks only to the Notion API using **your own** integration token and writes files locally. It has no server, no telemetry, and no shared credentials. Each user creates their own Notion integration and only exports pages they explicitly connect to it.

## Handling your token

- Create the integration with **Read content** capability only; the exporter never writes to Notion.
- Store the token with `nbe init` (saved with owner-only permissions) or in a git-ignored `.env`. Prefer these over `--token`, which lands in shell history.
- Never commit `.env`, paste the token in an issue, or share a screenshot of it. If it leaks, rotate it at <https://www.notion.so/profile/integrations> immediately.
- Exports contain your private notes. Don't commit the export folder or `notion_export_manifest.json` to a public repository.

## Reporting a vulnerability

Please open a private security advisory on this repository (Security → Report a vulnerability) instead of a public issue. Include steps to reproduce; expect an acknowledgement within a few days.
