# -*- coding: utf-8 -*-
"""Credential router — CRUD endpoints for API key credentials."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from ..access import ResourceKind
from ..deps import (
    get_current_user_id,
    get_resource_access_service,
    get_storage,
)
from ._schema import (
    CreateCredentialRequest,
    CreateCredentialResponse,
    ListCredentialsResponse,
    ListCredentialSchemasResponse,
    UpdateCredentialRequest,
)
from ._schema._credential import (
    CheckCredentialModelRequest,
    CheckCredentialModelResponse,
    NewAPIEmbeddingProbeRequest,
    NewAPIEmbeddingProbeResponse,
    NewAPIGatewayRequest,
    SetCredentialEnabledRequest,
)
from .._service import CredentialView, ResourceAccessService
from .._service._newapi import GatewayConnectionResult, NewAPIGateway
from ..storage import StorageBase
from ...credential import CredentialBase, CredentialFactory, NewAPICredential

credential_router = APIRouter(
    prefix="/credential",
    tags=["credential"],
    responses={404: {"description": "Not found"}},
)


def _saved_newapi_key(data: dict, base_url: str) -> str:
    if (
        data.get("type") != "newapi_credential"
        or data.get("base_url") != base_url
    ):
        raise HTTPException(
            status_code=400,
            detail="Enter the API key for this gateway address.",
        )
    return data["api_key"]


async def _resolve_newapi_gateway(
    body: NewAPIGatewayRequest,
    user_id: str,
    access: ResourceAccessService,
) -> NewAPIGateway:
    key = body.api_key.get_secret_value().strip() if body.api_key else ""
    if not key and body.credential_id:
        _, record = await access.resolve_for_edit(
            user_id,
            ResourceKind.CREDENTIAL,
            body.credential_id,
        )
        ResourceAccessService.ensure_credential_enabled(record)
        key = _saved_newapi_key(record.data, body.base_url)
    if not key:
        raise HTTPException(
            status_code=400, detail="Enter the gateway API key."
        )

    return NewAPIGateway(body.base_url, key)


@credential_router.post(
    "/newapi/check-connection",
    response_model=GatewayConnectionResult,
)
async def check_newapi_connection(
    body: NewAPIGatewayRequest,
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> GatewayConnectionResult:
    """Test the gateway configured in the form without saving it."""
    gateway = await _resolve_newapi_gateway(body, user_id, access)
    return await gateway.check_connection()


@credential_router.post(
    "/newapi/embedding-dimensions",
    response_model=NewAPIEmbeddingProbeResponse,
)
async def probe_newapi_embedding(
    body: NewAPIEmbeddingProbeRequest,
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> NewAPIEmbeddingProbeResponse:
    """Measure a model's native dimension with one short embedding request."""
    gateway = await _resolve_newapi_gateway(body, user_id, access)
    return NewAPIEmbeddingProbeResponse(
        dimensions=await gateway.embedding_dimensions(body.model),
    )


@credential_router.post(
    "/{credential_id}/check-model",
    response_model=CheckCredentialModelResponse,
)
async def check_credential_model(
    credential_id: str,
    body: CheckCredentialModelRequest,
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CheckCredentialModelResponse:
    """Test one explicitly configured chat model without changing its record."""
    _, record = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )
    ResourceAccessService.ensure_credential_enabled(record)
    credential = _validate_credential(record.data)
    if not isinstance(credential, NewAPICredential):
        raise HTTPException(
            status_code=400,
            detail="Model checks require a gateway credential.",
        )
    if body.model not in credential._model_names(credential.models):
        raise HTTPException(
            status_code=400,
            detail="The model is not configured on this credential.",
        )
    gateway = NewAPIGateway(
        credential.base_url,
        credential.api_key.get_secret_value(),
    )
    try:
        await gateway.check_chat_model(body.model)
        return CheckCredentialModelResponse(model=body.model, status="passed")
    except HTTPException as exc:
        return CheckCredentialModelResponse(
            model=body.model,
            status="failed",
            detail=str(exc.detail),
        )


@credential_router.patch(
    "/{credential_id}/enabled",
    response_model=CredentialView,
)
async def set_credential_enabled(
    credential_id: str,
    body: SetCredentialEnabledRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CredentialView:
    """Preserve the credential's configuration while changing its availability."""
    owner_id, record = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )
    credential = _validate_credential({**record.data, "enabled": body.enabled})
    credential.id = credential_id
    await storage.upsert_credential(owner_id, credential)
    return await access.get_resource(user_id, "credential", credential_id)


def _validate_credential(data: dict) -> CredentialBase:
    try:
        return CredentialFactory.from_dict(data)
    except ValidationError as exc:
        detail = ". ".join(error["msg"] for error in exc.errors())
        raise HTTPException(status_code=422, detail=detail) from exc


@credential_router.get(
    "/schemas",
    response_model=ListCredentialSchemasResponse,
    summary="List JSON schemas for all credential types",
)
async def list_credential_schemas() -> ListCredentialSchemasResponse:
    """Return JSON schemas for all registered credential types.

    Used by the frontend to render credential creation forms dynamically.
    """

    return ListCredentialSchemasResponse(
        schemas=CredentialFactory.list_schemas(),
    )


@credential_router.get(
    "/",
    response_model=ListCredentialsResponse,
    summary="List all credentials",
)
async def list_credentials(
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> ListCredentialsResponse:
    """Return all credential records visible to the authenticated user.

    Includes the caller's own credentials plus any credentials shared to
    them through :class:`ResourceAccessPolicyBase`. Shared entries have
    their secret ``data`` payload masked — only the discriminator and
    display name survive in the response — while runtime resolution
    (e.g. the chat model service) still sees the full payload.

    Args:
        user_id (`str`):
            Injected authenticated user ID.
        access (`ResourceAccessService`):
            Injected resource access service.

    Returns:
        `ListCredentialsResponse`:
            All visible credentials paired with editability and
            (for shared entries) redacted data.
    """
    entries = await access.list_resource(user_id, ResourceKind.CREDENTIAL)
    return ListCredentialsResponse(
        credentials=entries,
        total=len(entries),
    )


@credential_router.post(
    "/",
    response_model=CreateCredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new credential",
)
async def create_credential(
    body: CreateCredentialRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
) -> CreateCredentialResponse:
    """Store a new credential.

    Args:
        body (`CreateCredentialRequest`): Credential payload to store.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.

    Returns:
        `CreateCredentialResponse`: The server-assigned credential identifier.
    """
    data = body.data.copy()
    data.pop("id", None)
    credential_id = await storage.upsert_credential(
        user_id,
        _validate_credential(data),
    )
    return CreateCredentialResponse(credential_id=credential_id)


@credential_router.patch(
    "/{credential_id}",
    response_model=CredentialView,
    summary="Update a credential",
)
async def update_credential(
    credential_id: str,
    body: UpdateCredentialRequest,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> CredentialView:
    """Replace the payload of an existing credential.

    Args:
        credential_id (`str`): The credential to update.
        body (`UpdateCredentialRequest`): New credential payload.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.
        access (`ResourceAccessService`): Injected access service — used
            to resolve the owning user and enforce the edit permission
            when a shared editor updates the credential.

    Returns:
        `CredentialView`: The updated credential record.

    Raises:
        `HTTPException`: 404 if the credential is not visible to the
            caller; 403 if visible but only readable.
    """
    owner_id, previous = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )

    data = body.data.copy()
    if data.get("type") == "newapi_credential" and not data.get("api_key"):
        try:
            base_url = NewAPICredential.validate_base_url(
                data.get("base_url", "")
            )
        except (AttributeError, ValueError) as exc:
            raise HTTPException(
                status_code=422, detail="Enter a valid gateway address."
            ) from exc
        data["api_key"] = _saved_newapi_key(previous.data, base_url)
    credential = _validate_credential(data)
    if isinstance(credential, NewAPICredential):
        connection_changed = credential.base_url != previous.data.get(
            "base_url"
        ) or credential.api_key.get_secret_value() != previous.data.get(
            "api_key"
        )
        if connection_changed:
            if (
                credential._model_names(credential.models)
                and not body.models_confirmed
            ):
                raise HTTPException(
                    status_code=409,
                    detail="The gateway changed. Confirm the chat models for the new connection.",
                )
            credential.embedding_models = {}
    credential.id = credential_id
    await storage.upsert_credential(owner_id, credential)
    return await access.get_resource(user_id, "credential", credential_id)


@credential_router.delete(
    "/{credential_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a credential",
)
async def delete_credential(
    credential_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> None:
    """Permanently delete a credential.

    Args:
        credential_id (`str`): The credential to delete.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.
        access (`ResourceAccessService`): Injected access service — used
            to resolve the owning user and enforce the edit permission
            when a shared editor deletes the credential.

    Raises:
        `HTTPException`: 404 if the credential is not visible to the
            caller; 403 if visible but only readable.
    """
    owner_id, _ = await access.resolve_for_edit(
        user_id,
        ResourceKind.CREDENTIAL,
        credential_id,
    )
    await storage.delete_credential(owner_id, credential_id)
