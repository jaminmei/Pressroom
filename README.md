# Document Conversion

Document Conversion is a self-hosted workspace for building, running, and evaluating document-processing workflows. It combines a visual workflow editor with OCR, layout detection, image preprocessing, document conversion, and vision-language-model adapters.

This repository contains the public **0.2.0** core source release. Workspace isolation is enabled in every supported public deployment.

## Highlights

- Visual workflows with typed ports and reusable templates
- OCR, layout detection, image enhancement, image rotation, Text, MarkItDown, and Docling engines
- OpenAI-compatible and Azure OpenAI vision providers configured per workspace
- Test sets, ground-truth versions, batch evaluation, result comparison, and review
- Serial execution for a simple deployment or durable Redis/Celery queue execution
- English and Traditional Chinese UI
- Session authentication, workspace RBAC, encrypted Provider credentials, and SSRF-protected Provider calls
- Published workflow API with upload and remote-input safeguards

## Requirements

- Docker Engine with Docker Compose v2
- At least 16 GB RAM for the standard or full profile; model-heavy engines may require more
- Node.js 20+ and Python 3.11 for local development

## Release format

Version 0.2.0 is distributed as source code only. The project does not publish prebuilt Docker/OCI images to GHCR, Docker Hub, or another container registry. The Compose commands below build the project images locally from the checked-in Dockerfiles.

Locally built images contain third-party base images, Python and npm packages, and system components such as Poppler. Packages such as `certifi` also retain their own terms. Review [Third-Party Notices](THIRD_PARTY_NOTICES.md), the lockfiles, and the license metadata shipped by those components before redistributing an image.

## Quick start

1. Create the environment file:

   ```bash
   cp .env.example .env
   ```

2. Replace every required placeholder in `.env`. Generate a Provider encryption key with:

   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```

3. Start the standard application:

   ```bash
   docker compose --profile standard up -d --build
   ```

4. Open `http://localhost:5173`, register an account, and create a workspace.

The standard profile starts the UI, API, PostgreSQL, and all built-in engines. The full profile adds Redis and a Celery worker:

```bash
# In .env, set ORCHESTRATOR_MODE=queue and ENABLE_QUEUE_MODE=true first.
docker compose --profile full up -d --build
```

Check process liveness at `http://localhost:8000/api/health`. Upstream Provider connectivity is tested from Settings → Model Providers.

## Configure a vision Provider

Open Settings → Model Providers and create an `openai_compatible` Provider.

- For a standard OpenAI-compatible API, select **OpenAI compatible**, enter the API base URL, and optionally discover models from `/models`.
- For Azure OpenAI, select **Azure OpenAI**, enter the Azure endpoint and API version, then add deployment names manually.
- The Provider URL is always explicit; the application never substitutes a deployment-wide upstream URL.

If exactly one enabled model is available, new workflows select it automatically. With zero or multiple enabled models, the workflow asks the user to choose.

### Private network Providers

`PROVIDER_ALLOW_PRIVATE_HOSTS=true` permits workspace Providers on private or loopback networks, which is convenient for local engines. Link-local addresses, cloud metadata endpoints, reserved/multicast addresses, and DNS rebinding remain blocked.

In an untrusted multi-tenant deployment, set `PROVIDER_ALLOW_PRIVATE_HOSTS=false` unless private routing is an intentional part of the threat model.

## Compose profiles

| Profile | Services | Typical use |
| --- | --- | --- |
| `core` | Built-in engines | Engine development |
| `standard` | Core + backend + frontend + PostgreSQL | Single-process application execution |
| `full` | Standard + Redis + Celery worker | Durable queue execution |

All Compose profiles require the secrets documented in `.env.example`. Public deployments always run with `WORKSPACE_RBAC_ENFORCED=true`.

## Local development

Backend:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --require-hashes -r requirements-dev.lock
# Required when running the repository-wide test suite, which includes the
# separately licensed Text engine tests.
python3 -m pip install --require-hashes -r tests/requirements-text-engine.lock
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm ci
npm run dev
```

Quality gates:

```bash
ruff check .
ruff format --check .
mypy app
pytest -q

cd frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

Run `python3 scripts/check-public-boundary.py --include-untracked` before committing public-release changes.

For the one-time 0.2.0 root publication, run the stricter history gate after
creating the root commit and again after creating the release tag:

```bash
python3 scripts/check-public-boundary.py --initial-release-tag v0.2.0
```

This release-only mode accepts zero tags or exactly `v0.2.0` and requires all
refs to resolve to the single parentless release commit. It is intentionally
not part of normal post-release CI, where public history grows linearly.

## Public workflow API

Publish a workflow from the UI, create an API key in API Access, and invoke the versioned API under `/api/v1/workflows/{workflow_id}`. The UI provides a request example for each published workflow.

Never expose API keys in browser code or commit them to the repository. See [SECURITY.md](SECURITY.md) for reporting and deployment guidance.

## Documentation

- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Model sources and license records](docs/model-licenses.md)
- [Project-authored assets](ASSETS.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Trademark policy](TRADEMARKS.md)

## License

This is a mixed-license repository:

- Unless a file or directory says otherwise, original Document Conversion code and assets are licensed under the [MIT License](LICENSE), copyright 2026 Jamin Mei and ricoyudog.
- Every original work under [`engines/text/**`](engines/text/) is licensed under **GPL-3.0-only**. Its complete license is available in [`engines/text/COPYING`](engines/text/COPYING) and [`LICENSES/GPL-3.0-only.txt`](LICENSES/GPL-3.0-only.txt).

The Text engine runs as a separate HTTP service; other components must use its engine API rather than import its GPL-covered modules. Third-party dependencies and runtime model artifacts remain under their respective terms. The MIT copyright license does not grant rights in project trademarks; see [TRADEMARKS.md](TRADEMARKS.md).
