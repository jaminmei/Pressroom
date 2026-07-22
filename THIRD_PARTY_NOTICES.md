# Third-Party Notices

Document Conversion depends on open-source software distributed under its own license terms. Major components include FastAPI, SQLAlchemy, Alembic, Celery, Redis client libraries, Pydantic, HTTPX, React, Ant Design, React Router, Vite, Vitest, Playwright, OpenAI's Python SDK, OCR and image-processing libraries, MarkItDown, and Docling.

The authoritative dependency set and versions are recorded in the checked-in Python hash lockfiles and `frontend/package-lock.json`. Package distributions include their applicable license metadata. Container base images and system packages are governed by their respective licenses.

## Text engine and html2text

The separately deployed Text engine under `engines/text/**` uses [`html2text==2020.1.16`](https://pypi.org/project/html2text/2020.1.16/) to convert HTML to Markdown-oriented text.

- Upstream source: [Alir3z4/html2text](https://github.com/Alir3z4/html2text/)
- Upstream authorship: originally written by Aaron Swartz and maintained by the html2text contributors
- License declared by this release's package metadata: GNU GPL version 3 (GPLv3)
- Distribution hashes: wheel `c7c629882da0cf377d66f073329ccf34a12ed2adf0169b9285ae4e63ef54c82b`; source archive `e296318e16b059ddb97f7a8a1d6a5c1d7af4544049a01e261731d2d5cc277bbb`
- Use scope: imported only by `engines/text/src/text_engine.py`; no other service may import Text engine modules

The complete GPL version 3 text is included at [`LICENSES/GPL-3.0-only.txt`](LICENSES/GPL-3.0-only.txt) and [`engines/text/COPYING`](engines/text/COPYING). The Text engine's original Document Conversion code is also licensed `GPL-3.0-only`; see [`engines/text/README.md`](engines/text/README.md).

## Containers, services, and models

Locally built containers include base-image packages and may install operating-system components such as Poppler and CA certificate bundles. Python packages such as `certifi` retain their own license notices. Redis, PostgreSQL, external model services, and runtime model artifacts are separate products and are not relicensed by this repository.

No model weights are stored in this source tree. Some dependencies obtain or bundle model artifacts when installed or first run. Their provenance and redistribution terms must be reviewed separately as described in [`docs/model-licenses.md`](docs/model-licenses.md).

Temporary security-audit exceptions for the optional layout-detection dependency stack are listed in [`docs/dependency-audit-exceptions.md`](docs/dependency-audit-exceptions.md).

This file is informational and does not replace or modify any third-party license. Before redistribution, inspect the license files and metadata in the exact dependency artifacts and locally built images being shipped.
