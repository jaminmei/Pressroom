from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import lru_cache
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.auth import AuthenticatedContext
from app.services.auth_service import AuthService, IssuedAuthContext
from app.services.workspace_access import (
    ResolvedContext,
    request_workspace_selector,
    resolve_workspace_access,
)
from app.services.workspace_rbac import workspace_rbac_enforced

router = APIRouter()
_session_cookie = APIKeyCookie(
    name=get_settings().auth_session_cookie_name,
    auto_error=False,
    scheme_name="SessionCookie",
)


class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str


@lru_cache
def get_auth_service() -> AuthService:
    return AuthService()


def _issued_response(
    *,
    status_code: int,
    issued: IssuedAuthContext,
    settings: Settings,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content={
            "success": True,
            "data": {
                "user": issued.context.user.model_dump(mode="json"),
                "session": {
                    "expires_at": issued.context.session.expires_at.isoformat(),
                },
            },
        },
    )
    response.set_cookie(
        key=settings.auth_session_cookie_name,
        value=issued.raw_session_token,
        expires=int(issued.context.session.expires_at.timestamp()),
        httponly=True,
        secure=settings.auth_session_secure,
        samesite=settings.auth_session_same_site,
        domain=settings.auth_session_domain,
        path=settings.auth_session_path,
    )
    return response


def get_authenticated_context(
    request: Request,
    _: Annotated[str | None, Security(_session_cookie)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthenticatedContext:
    raw_session_token = request.cookies.get(get_settings().auth_session_cookie_name)
    return auth_service.require_authenticated(raw_session_token)


def require_workspace_capability(
    capability: str,
) -> Callable[[Request, AuthenticatedContext], Coroutine[Any, Any, ResolvedContext]]:
    async def _dependency(
        request: Request,
        context: Annotated[AuthenticatedContext, Depends(get_authenticated_context)],
    ) -> ResolvedContext:
        with SessionLocal() as session:
            return resolve_workspace_access(
                session,
                context=context,
                selector=request_workspace_selector(request, context),
                capability=capability if workspace_rbac_enforced() else None,
            )

    setattr(_dependency, "policy_kind", "workspace")  # noqa: B010
    setattr(_dependency, "capability", capability)  # noqa: B010
    return _dependency


@router.post("/auth/register", response_model=None)
async def register(payload: RegisterRequest) -> JSONResponse:
    settings = get_settings()
    issued = get_auth_service().register(
        email=payload.email,
        password=payload.password,
        name=payload.name,
    )
    return _issued_response(status_code=201, issued=issued, settings=settings)


@router.post("/auth/login", response_model=None)
async def login(payload: LoginRequest) -> JSONResponse:
    settings = get_settings()
    issued = get_auth_service().login(email=payload.email, password=payload.password)
    return _issued_response(status_code=200, issued=issued, settings=settings)


@router.post("/auth/logout", response_model=None)
async def logout(request: Request) -> JSONResponse:
    settings = get_settings()
    raw_session_token = request.cookies.get(settings.auth_session_cookie_name)
    get_auth_service().logout(raw_session_token)
    response = JSONResponse(status_code=200, content={"success": True})
    response.delete_cookie(
        key=settings.auth_session_cookie_name,
        domain=settings.auth_session_domain,
        path=settings.auth_session_path,
    )
    return response


@router.get("/auth/me", response_model=None)
async def me(
    context: Annotated[AuthenticatedContext, Depends(get_authenticated_context)],
) -> JSONResponse:
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "data": {
                "user": context.user.model_dump(mode="json"),
                "session": {
                    "expires_at": context.session.expires_at.isoformat(),
                },
            },
        },
    )
