"""Unauthenticated health endpoint for the public API namespace.

No prefix here — the parent router in ``router.py`` mounts this under
``/api/v1``. Health requests do not require credentials.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["public-api"])


@router.get("/health", response_model=None)
async def health() -> dict[str, str]:
    return {"status": "ok"}
