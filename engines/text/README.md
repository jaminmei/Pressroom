<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Text engine

This directory is the Document Conversion Text engine service. It accepts plain text or HTML through the engine HTTP contract and returns normalized text output.

## License boundary

Every original work under `engines/text/**` is licensed under **GPL-3.0-only**, not the repository's default MIT license. The complete terms are available in [COPYING](COPYING) and [`../../LICENSES/GPL-3.0-only.txt`](../../LICENSES/GPL-3.0-only.txt).

The Text engine is deployed as a separate HTTP service. Code outside this directory communicates with it through the engine API and must not import modules from `engines/text` directly. Third-party packages retain their own licenses; see [`../../THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md), including the notice for `html2text==2020.1.16`.
