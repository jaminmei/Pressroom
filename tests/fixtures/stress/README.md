# Stress Fixtures

This folder contains small deterministic fixture files for stress tests.

## Files

- `single-page.pdf`: valid 1-page PDF
- `multi-page.pdf`: valid 3-page PDF
- `single-page.png`: valid PNG image
- `sample.txt`: plain-text sample

## Reproducibility

These files and the frontend E2E binary fixtures are generated from auditable source with no
external tools, fonts, network access, timestamps, or random data:

```bash
python3 scripts/generate-public-fixtures.py
python3 scripts/generate-public-fixtures.py --check
```
