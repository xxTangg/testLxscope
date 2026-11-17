# -*- coding: utf-8 -*-
"""Request / response schemas for the credential router."""
from pydantic import BaseModel, Field, SecretStr, field_validator
from typing import Literal

from ..._service import CredentialView
from ....credential import NewAPICredential


class CreateCredentialRequest(BaseModel):
    """Request body for creating a new credential."""

    data: dict = Field(description="Credential payload (e.g. API keys).")


class CreateCredentialResponse(BaseModel):
    """Response body after creating a credential."""

    credential_id: str = Field(
        description="Server-assigned credential identifier.",
    )


class UpdateCredentialRequest(BaseModel):
    """Request body for updating an existing credential."""

    data: dict = Field(description="New credential payload.")
    models_confirmed: bool = False


class SetCredentialEnabledRequest(BaseModel):
    """Enable or disable an existing credential explicitly."""

    enabled: bool


class CheckCredentialModelRequest(BaseModel):
    """The configured model to test with a short chat completion."""

    model: str = Field(min_length=1)


class CheckCredentialModelResponse(BaseModel):
    """The result of the upstream chat completion test."""

    model: str
    status: Literal["passed", "failed"]
    detail: str = ""


class ListCredentialsResponse(BaseModel):
    """Response body for listing credentials."""

    credentials: list[CredentialView] = Field(
        description="Credential records.",
    )
    total: int = Field(description="Total number of credentials.")


class ListCredentialSchemasResponse(BaseModel):
    """Response body for listing credential type schemas."""

    schemas: list[dict] = Field(
        description="JSON schemas for all registered credential types.",
    )


class NewAPIGatewayRequest(BaseModel):
    """Connection settings for a New API gateway lookup."""

    base_url: str
    api_key: SecretStr | None = None
    credential_id: str | None = None

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return NewAPICredential.validate_base_url(value)


class NewAPIEmbeddingProbeRequest(NewAPIGatewayRequest):
    """Discover an embedding model's native vector dimension."""

    model: str = Field(min_length=1)


class NewAPIEmbeddingProbeResponse(BaseModel):
    """The vector dimension returned by the gateway."""

    dimensions: int
