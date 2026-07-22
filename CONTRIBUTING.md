# Contributing

Thank you for helping improve Document Conversion.

## Before opening a change

For substantial features, open an issue describing the use case, public API impact, security considerations, and test approach. Keep changes focused and avoid committing generated runtime data, secrets, model weights, or unrelated binary assets.

## Development workflow

1. Fork the repository and create a topic branch.
2. Install the backend and frontend development dependencies described in the README.
3. Add tests for behavior changes.
4. Run the backend and frontend quality gates.
5. Run the public-boundary checker and inspect the final diff.
6. Open a pull request with a clear problem statement, solution summary, and verification evidence.

The public boundary intentionally excludes organization-specific integrations and configuration. Optional integrations must use the generic plugin contracts and remain removable without changing public core behavior.

## Code style

- Python: Ruff formatting/lint conventions, type annotations, and focused pytest coverage.
- TypeScript/React: ESLint, TypeScript strict checks, accessible UI states, and Vitest coverage.
- Prefer explicit contracts and small modules over environment-specific branches in core files.
- Never log documents, prompts, credentials, authorization headers, or upstream response bodies.

## Commit and pull request hygiene

- Use concise, imperative commit subjects.
- Do not combine broad formatting changes with functional changes.
- Update public documentation when configuration or API contracts change.
- State whether serial, queue, standard Compose, and full Compose paths were tested.

By participating, you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
