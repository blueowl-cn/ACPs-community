# Repository Guidelines

## Project Structure & Module Organization

This Python monorepo implements the Agent Collaboration Protocols (ACPs). Specifications and documentation live in `acps-specs/` and `acps-docs/`. Reusable code is in `acps-sdk/acps_sdk/`; CLI code is in `acps-cli/acps_cli/`. FastAPI services are `ca-server/`, `registry-server/`, `discovery-server/`, and `mq-auth-server/`, with code in `app/`, tests in `tests/`, and Alembic migrations where needed. `demo-leader/` and `demo-partner/` are reference applications. Shared infrastructure belongs in `acps-infra/`.

## Build, Test, and Development Commands

Run commands from the component being changed; package requirements differ (currently Python 3.10 or 3.14).

- `uv sync --locked`: install exact dependencies from `uv.lock`.
- Bootstrap: most service components use `just app bootstrap`; `acps-cli` uses `just dev bootstrap`.
- `just app start fg`: run a service in the foreground.
- `just test unit|integration|e2e`: run the selected suite; `just test all` runs all suites.
- `just qa all`: run all QA checks; components supporting `full` may use `just qa full`. Use `just qa fix` for safe fixes.
- `just package wheel`: build a wheel where supported.

Use `just help` for component-specific targets. In `acps-sdk/`, run `uv run pytest` directly.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations for new code, a 120-character line limit, and double quotes. Name modules/functions `snake_case`, classes `PascalCase`, and constants `UPPER_SNAKE_CASE`. Keep schemas, services, and routes in their existing feature packages. Run `just qa all` before submitting; components supporting `full` may use `just qa full`. Do not hand-edit lock files or Alembic revision identifiers.

## Testing Guidelines

Use pytest. Name files `test_*.py` and functions `test_*`; place them under `tests/unit/`, `tests/integration/`, or `tests/e2e/`. Add regression tests for fixes. Use markers declared in the component's `pyproject.toml` for slow or environment-dependent cases. Server coverage gates are generally 70%; run `just test coverage` when available.

## Commit & Pull Request Guidelines

Recent root history is release-oriented, while component Commitizen settings expect Conventional Commits. Prefer `feat(discovery): add semantic filter` or `fix(cli): validate registry URL`. Keep commits focused. Pull requests should explain impact, identify affected components, link issues, and list checks run. Include migration notes for schema changes, documentation for new settings, and screenshots for visible UI changes.

## Security & Configuration

Copy `.env.example`; never commit `.env`, keys, certificates, tokens, or production credentials. Use the PKI and infrastructure commands in each `Justfile` rather than embedding secrets or endpoints.
