# -*- coding: utf-8 -*-
"""The model router."""

from fastapi import APIRouter, Depends, HTTPException, status

from ._schema import ListModelsResponse, ListModelsRequest
from ..deps import get_current_user_id, get_resource_access_service
from .._service import ResourceAccessService
from ...credential import CredentialFactory, NewAPICredential

model_router = APIRouter(
    prefix="/model",
    tags=["model"],
    responses={404: {"description": "Not found"}},
)


@model_router.get(
    "/",
    response_model=ListModelsResponse,
    summary="List all candidate models under the given credential type",
)
async def list_models(
    body: ListModelsRequest = Depends(),
    user_id: str = Depends(get_current_user_id),
    access: ResourceAccessService = Depends(get_resource_access_service),
) -> ListModelsResponse:
    """Return all candidate models under the given credential type.

    Args:
        body (ListModelsRequest): The request body.

    Returns:
        `ListModelsResponse`: The response body.
    """
    credential_cls = CredentialFactory.get_credential_class(body.provider)
    if credential_cls is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{body.provider}' not found.",
        )

    if credential_cls is NewAPICredential:
        if body.credential_id is None:
            return ListModelsResponse(models=[], total=0)
        record = await access.resolve_credential(user_id, body.credential_id)
        credential = CredentialFactory.from_dict(record.data)
        if not isinstance(credential, NewAPICredential):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Credential does not belong to this provider.",
            )
        models = credential.configured_models()
    else:
        models = credential_cls.get_chat_model_class().list_models()
    return ListModelsResponse(models=models, total=len(models))
