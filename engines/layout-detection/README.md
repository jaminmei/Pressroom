# Layout Detection Engine

Document layout analysis engine using PaddlePaddle PPStructure.

## API Endpoints

| Endpoint | Method | Description |
|----------|-------|-------------|
| `/health` | GET | Basic health check |
| `/health/full` | GET | Full health check with model initialization |
| `/models` | GET | Get available models |
| `/layout-types` | GET | Get supported layout types for current config |
| `/process` | POST | Process image and return layout regions |

## Model Files

### Default: PPStructureV2 (PicoDet-LCNet)

The engine uses PaddlePaddle's PPStructure for layout detection. Its fixed
vendor model is **automatically downloaded** on first use to the container
user's cache:

```
/home/appuser/.paddleocr/
└── whl/
    └── layout/
        └── picodet_lcnet_x1_0_layout_infer/
            ├── inference.pdiparams
            ├── inference.pdiparams.info
            └── inference.pdmodel
```

### Controlled model pre-warming

The request API does not accept a model URL or filesystem path. For offline or
hermetic deployments, initialize the engine during a controlled image-build or
pre-deployment step, verify the downloaded archive independently, and preserve
the resulting `/home/appuser/.paddleocr` cache. Restrict runtime egress after
the cache is populated.

The checked-in `models/mapping_table.json` contains display metadata only; it
does not contain model weights.

## Supported Layout Types

### Chinese Model (ch)
- Text
- Title
- Figure
- Figure_caption
- Table
- Table_caption
- Header
- Footer
- Reference
- Equation

### English Model (en)
- Text
- Title
- Figure
- Table
- Caption
- Header
- Footer
- Reference
- Equation

## Request Format

```json
{
    "input_type": "base64",
    "base64_data": "<base64-encoded-image>",
    "config": {
        "model": "ppstructure_v2",
        "model_file": "picodet_lcnet_x1_0",
        "language": "ch",
        "selected_types": ["Text", "Title", "Table"]
    }
}
```

## Response Format

```json
{
    "status": "success",
    "output": {
        "elements": [
            {
                "id": "layout_0",
                "type": "Text",
                "bbox": {"x": 100, "y": 50, "width": 500, "height": 200},
                "confidence": 0.95
            }
        ],
        "total_regions": 1,
        "model": "ppstructure_v2",
        "model_file": "picodet_lcnet_x1_0",
        "language": "ch"
    },
    "processing_time_ms": 1234
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LAYOUT_USE_GPU` | `false` | Enable GPU acceleration |
| `LAYOUT_LANG` | `ch` | Default language |
