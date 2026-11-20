# -*- coding: utf-8 -*-
"""Credential router — CRUD endpoints for API key credentials."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from ..access import ResourceKind
from ..deps import (
    get_credential_verification_secret,
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
    NewAPIChatModelProbeRequest,
    NewAPIEmbeddingProbeRequest,
    NewAPIEmbeddingProbeResponse,
    NewAPIGatewayRequest,
    SetCredentialEnabledRequest,
)
from .._service import CredentialView, ResourceAccessService
from .._service._newapi import (
    GatewayConnectionResult,
    GatewayRequestError,
    NewAPIGateway,
)
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


async def _check_chat_model(
    gateway: NewAPIGateway,
    model: str,
) -> CheckCredentialModelResponse:
    try:
        await gateway.check_chat_model(model)
    except GatewayRequestError as exc:
        return CheckCredentialModelResponse(
            model=model,
            status="failed",
            detail=str(exc.detail),
            code=exc.diagnostic.code,
            http_status=exc.diagnostic.http_status,
            diagnostic_id=exc.diagnostic.diagnostic_id,
        )
    except HTTPException as exc:
        return CheckCredentialModelResponse(
            model=model,
            status="failed",
            detail=str(exc.detail),
            code="invalid_response",
        )
    return CheckCredentialModelResponse(model=model, status="passed")


@credential_router.post(
    "/newapi/check-model",
    response_model=CheckCredentialModelResponse,
    response_model_exclude_none=True,
)
async def check_newapi_model(
    body: NewAPIChatModelProbeRequest,
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
    secret: str = Depends(get_credential_verification_secret),
) -> CheckCredentialModelResponse:
    """Run a short completion using the draft connection and model."""
    gateway = await _resolve_newapi_gateway(body, user_id, access)
    result = await _check_chat_model(gateway, body.model)
    if result.status == "passed":
        result.verification = gateway.sign_model_verification(
            secret,
            user_id,
            body.model,
            body.credential_id,
        )
    return result


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
    response_model_exclude_none=True,
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
    return await _check_chat_model(gateway, body.model)


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


def _gateway_changed(credential: NewAPICredential, previous: dict) -> bool:
    return (
        credential.base_url != previous.get("base_url")
        or credential.api_key.get_secret_value() != previous.get("api_key")
    )


def _require_model_verifications(
    credential: NewAPICredential,
    verifications: dict[str, str],
    user_id: str,
    secret: str,
    *,
    credential_id: str | None = None,
    previous: dict | None = None,
) -> None:
    models = credential._model_names(credential.models)
    if not models:
        raise HTTPException(422, "Enter at least one chat model ID.")
    key = credential.api_key.get_secret_value()
    if not key:
        raise HTTPException(422, "Enter the gateway API key.")
    if (
        previous is not None
        and previous.get("type") == credential.type
        and not _gateway_changed(credential, previous)
        and models == credential._model_names(previous.get("models") or "")
    ):
        return
    gateway = NewAPIGateway(credential.base_url, key)
    if not all(
        gateway.verify_model_verification(
            secret,
            user_id,
            model,
            credential_id,
            verifications.get(model, ""),
        )
        for model in models
    ):
        raise HTTPException(409, "Test every chat model before saving.")


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
    secret: str = Depends(get_credential_verification_secret),
) -> CreateCredentialResponse:
    """Store a new credential.

    Args:
        body (`CreateCredentialRequest`): Credential payload to store.
        user_id (`str`): Injected authenticated user ID.
        storage (`StorageBase`): Injected storage backend.
        secret (`str`): Secret used to validate model verification tokens.

    Returns:
        `CreateCredentialResponse`: The server-assigned credential identifier.
    """
    data = body.data.copy()
    data.pop("id", None)
    credential = _validate_credential(data)
    if isinstance(credential, NewAPICredential):
        _require_model_verifications(
            credential,
            body.model_verifications,
            user_id,
            secret,
        )
    credential_id = await storage.upsert_credential(user_id, credential)
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
    secret: str = Depends(get_credential_verification_secret),
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
        secret (`str`): Secret used to validate model verification tokens.

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
        _require_model_verifications(
            credential,
            body.model_verifications,
            user_id,
            secret,
            credential_id=credential_id,
            previous=previous.data,
        )
        if _gateway_changed(credential, previous.data):
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
