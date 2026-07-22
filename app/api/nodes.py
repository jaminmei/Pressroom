from __future__ import annotations

from functools import lru_cache

from fastapi import APIRouter

from app.services.node_registry import NodeRegistryService

router = APIRouter()


@lru_cache
def get_node_registry_service() -> NodeRegistryService:
    return NodeRegistryService()


@router.get("/nodes/registry", response_model=None)
async def get_node_registry() -> dict[str, object]:
    registry = get_node_registry_service().get_registry()
    return registry.model_dump(mode="json")
