# AGENTS.md

## Scope

These instructions apply to the entire public Document Conversion repository.

## Optional maintainer overlay

When a root-level `AGENTS.private.md` is present in a private development clone,
read it after this file and apply its additional private-source and release
controls. Its absence in a clean public clone is expected. Never add the overlay
to a public export.

## Public boundary

- Keep the repository suitable for a clean public clone.
- Do not add credentials, private endpoints, organization-specific configuration, runtime data, model weights, or unapproved binary assets.
- Optional integrations must load through generic plugin registries or environment-selected module entry points. Core application files must continue to work when optional modules are absent.
- Provider credentials may be decrypted only at invocation time and must never enter workflow/node configuration, logs, API responses, or persisted traces.
- Run `python3 scripts/check-public-boundary.py --include-untracked` before handing off changes.
- Private preflight rules must stay outside this repository. Pass them with
  `--deny-pattern-file /path/to/private.rules`; findings report only the matched file or
  metadata category and never echo a rule or matched content.

## Architecture

- Backend: FastAPI, SQLAlchemy/PostgreSQL, a SQLite Provider store, and optional Celery execution.
- Frontend: React, TypeScript, Vite, Ant Design, and registry-loaded optional UI modules.
- Engines implement the Document Conversion `/process`, `/health`, and `/config` contracts.
- `engine_service` Providers are invoked directly through `/process`.
- `openai_compatible` Providers are invoked through the local VLM adapter, which selects standard OpenAI-compatible or Azure OpenAI behavior per request.

## Security invariants

- Public deployments enforce workspace RBAC.
- Compose secrets are explicit and have no insecure fallback.
- Private Provider hosts are an operator-controlled risk; link-local and cloud metadata destinations are always blocked.
- Do not log prompts, document contents, secrets, authorization headers, upstream response bodies, or complete private endpoints.
- Production frontend bundles must not expose debug stores or unconditional console diagnostics.
- Public Playwright coverage belongs under `frontend/e2e/public/`; only deterministic
  inputs belong under `frontend/e2e/fixtures/`. Keep private/manual acceptance suites
  outside this repository.

## Verification

Backend changes should run Ruff, mypy, and focused pytest coverage. Frontend changes should run ESLint, TypeScript, Vitest, and a production build. Routing or deployment changes should additionally validate standard and full Compose profiles.

Before a public release, also run:

- `python3 scripts/generate-public-fixtures.py --check`
- `python3 scripts/check-license-scope.py`
- `python3 scripts/check-public-boundary.py --include-untracked`
