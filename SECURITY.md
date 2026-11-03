# Security Policy

## Supported versions

Only the current `main` branch receives security fixes. Older tags and
forks are not maintained.

## Reporting a vulnerability

Do not open a public issue for a security problem. Report it privately through
GitHub's "Report a vulnerability" feature on this repository
(`Security` tab -> `Advisories` -> `Report a vulnerability`), or email the
maintainer listed in the repository profile.

Please include:

- the affected commit or version,
- the impact and the reachable path,
- a minimal reproduction if you have one,
- any suggested fix.

You will receive an acknowledgement within a few days. Please keep the report
confidential until a fix is published.

## Scope

This project is a Telegram trading-signal bot. The most sensitive assets are
exchange API keys, the Telegram bot token, the admin chat id, and the ability
to place a live order. Reports about how these could be exposed or misused are
the highest priority.

Live trading is disabled by default and every live path is fail-closed; see
`docs/runbook.md` for the activation gates.
