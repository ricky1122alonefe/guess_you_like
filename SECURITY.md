# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

1. Email or DM the repository owner with a description and steps to reproduce.
2. Include impact assessment if known (data leak, RCE, etc.).
3. Allow reasonable time to patch before public disclosure.

## Scope notes

This project is a **local research tool**:

- It stores API keys in `.env` / `local_secrets.py` (gitignored) — never commit them.
- It scrapes third-party sports sites; do not use it to bypass rate limits or access controls.
- The bundled web server (`serve.py`) is intended for **localhost**; do not expose it to the public internet without authentication and hardening.

## Out of scope

- Weaknesses in third-party sites (500.com, sporttery, AI providers)
- Social engineering / physical access to your machine
- Issues requiring a compromised `local_secrets.py` already on disk
