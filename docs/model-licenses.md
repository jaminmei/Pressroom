# Runtime Model Sources and Licenses

## Source-tree policy

Document Conversion 0.2.11 does not store learned-model weights in this repository. Files under engine `models/` directories are configuration or metadata only. Model artifacts may instead arrive inside an installed dependency, be downloaded to a runtime cache, or be served by an operator-selected external Provider.

Dependency version locks do not establish a model artifact's license. Before deployment or redistribution, the operator must verify the exact model revision, source, license, acceptable-use terms, and checksum.

## Built-in engine inventory

| Engine | Runtime model source | Version anchor in this release | Required license record |
| --- | --- | --- | --- |
| OCR | [RapidOCR](https://github.com/RapidAI/RapidOCR) / `rapidocr-onnxruntime`; its installed distribution supplies or locates PaddleOCR-compatible ONNX assets | `rapidocr-onnxruntime==1.3.24` in `engines/ocr/requirements.lock` | Record every ONNX filename, upstream model/revision, model-specific license, package artifact hash, and final file SHA-256 |
| Layout detection | PaddleOCR `PPStructure` obtains vendor layout artifacts in its runtime cache; `engines/layout-detection/models/mapping_table.json` records known PP-StructureV2 source URLs as metadata | `paddleocr==2.8.1` and `paddlepaddle==2.6.2` in the layout lock | Record language and model variant, exact download URL/revision, upstream model terms, archive hash, and each extracted artifact hash |
| Docling | The default `DocumentConverter` may obtain pipeline artifacts through the installed [Docling](https://github.com/docling-project/docling) dependency and its configured model hubs/caches | `docling==2.114.0` in `engines/docling/requirements.lock` | Export the resolved artifact inventory after initialization; record repository/revision, model card/license, and SHA-256 for every cached weight |
| VLM adapter | No local model. The workspace administrator selects an OpenAI-compatible or Azure OpenAI Provider and model/deployment | Provider configuration at runtime | Record provider, immutable model/deployment version where available, service/model terms, data-processing terms, and the date reviewed; a local hash may not exist for a hosted model |
| Text, MarkItDown, image enhancement, image rotation | Rule-based or deterministic processing; no learned weights are shipped by this repository | Dependency locks | No model record unless the operator adds a model-backed plugin or dependency |

Entries in the layout mapping table with no URL do not supply an implementation or weights. An operator who enables such an entry must provide and document the artifact independently.

## Release and deployment record

For every model-backed deployment, maintain a record with at least:

```text
engine:
model_name:
model_revision_or_version:
source_url:
retrieved_at_utc:
license_or_terms_url:
artifact_sha256:
redistribution_allowed: yes/no/unknown
reviewed_by:
```

Generate hashes only after all downloads and extraction complete. For a cache directory, an operator can produce a deterministic file inventory with:

```bash
find /path/to/model-cache -type f -print0 \
  | sort -z \
  | xargs -0 sha256sum > model-artifacts.sha256
```

Do not publish model caches, weights, or a prebuilt image containing them until every entry has a verified source and redistribution decision. A hosted Provider's authorization to call a model does not imply permission to redistribute that model.
