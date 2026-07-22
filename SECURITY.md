# Security Policy

## Supported versions

Security fixes are applied to the latest public release on `main`. Older snapshots are not supported.

## Report a vulnerability

Please use GitHub's private vulnerability reporting for this repository. Do not open a public issue containing exploit details, credentials, private documents, or deployment endpoints.

Include the affected version, impact, reproduction steps, and any suggested mitigation. Maintainers will acknowledge a complete report as soon as practical and coordinate disclosure after a fix is available.

## Deployment baseline

- Replace every required value in `.env.example`; never reuse the example placeholders.
- Keep `WORKSPACE_RBAC_ENFORCED=true`.
- Use HTTPS and secure session cookies outside local development.
- Keep the Provider encryption key stable, private, and shared only by the backend and worker.
- Set `PROVIDER_ALLOW_PRIVATE_HOSTS=false` for untrusted multi-tenant deployments unless private routing is explicitly required.
- Restrict the backend, database, Redis, and engine network ports with host and network controls.
- Review Provider TLS settings before disabling certificate verification.
- Rotate API keys and secrets immediately after suspected disclosure.

Provider URLs are protected with DNS validation and connection pinning. Private-host opt-in never permits link-local, cloud metadata, reserved, multicast, or unspecified destinations.

Known, narrowly scoped dependency-audit exceptions are documented in [docs/dependency-audit-exceptions.md](docs/dependency-audit-exceptions.md). No unlisted audit exception is accepted.
