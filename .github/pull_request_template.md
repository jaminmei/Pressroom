## Purpose

-

## Changed Files

-

## Verification Commands and Results

```bash
# Backend
pytest
mypy .
ruff check .
ruff format . --check

# Frontend
cd frontend
npm run lint
npx tsc --noEmit
npm test -- --run
npm run build
```

## Risks / Follow-ups

-
