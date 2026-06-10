# max-money-bot agent guide

Use this file to help AI agents work safely and efficiently in the `max-money-bot` repo.

## What this repo is
- A Python 3.12 voice bot for MAX messenger that parses spoken retail operations and writes them into Google Sheets.
- The source of truth is Sheets; SQLite is a technical layer for dedup, idempotency, dialog state, and pending writes.
- The bot uses OpenRouter for LLM parsing and local GigaAM for speech-to-text.

## Key local docs
- [`CLAUDE.md`](CLAUDE.md) — project overview, stack, commands, env vars, and repo conventions.
- `docs/SPEC.md` — source of truth for functional requirements.
- `docs/data-model.md` — Sheets schema + domain model.
- `docs/llm-parsing.md` — parser tools, prompt, and examples.
- `docs/scenarios.md` — supported user flows.

## How to run
- `python -m venv .venv && source .venv/bin/activate`
- `pip install -r requirements.txt`
- `python -m src.main` for local dev
- `pytest` for tests
- `ruff check src tests` and `mypy src` for lint/typecheck

## Important conventions
- Async I/O only (`asyncio`, `httpx.AsyncClient`).
- LLM parser returns typed `ParsedCommand`; avoid regex-based parsing.
- Maintain atomic writes across Sheets via shared `tx_id`.
- Treat `docs/SPEC.md` as contract for behavior.
- Do not commit `.env` or any secret files.

## What not to change without asking
- `docs/archive/` — old versions only.
- `.env`, `secrets/`, and any service account files.
- The core Sheets data model in `docs/data-model.md` without checking `CLAUDE.md` and spec first.
