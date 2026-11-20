# -*- coding: utf-8 -*-
"""Request / response schemas for the credential router."""
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    SecretStr,
    StringConstraints,
    field_validator,
)

from ..._service import CredentialView
from ....credential import NewAPICredential


class CreateCredentialRequest(BaseModel):
    """Request body for creating a new credential."""

    data: dict = Field(description="Credential payload (e.g. API keys).")
    model_verifications: dict[str, str] = Field(default_factory=dict)


class CreateCredentialResponse(BaseModel):
    """Response body after creating a credential."""

    credential_id: str = Field(
        description="Server-assigned credential identifier.",
    )


class UpdateCredentialRequest(BaseModel):
    """Request body for updating an existing credential."""

    data: dict = Field(description="New credential payload.")
    model_verifications: dict[str, str] = Field(default_factory=dict)


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
    code: str | None = None
    http_status: int | None = None
    diagnostic_id: str | None = None
    verification: str | None = None


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


class NewAPIChatModelProbeRequest(NewAPIGatewayRequest):
    """Test one chat model with a gateway configuration before saving it."""

    model: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            pattern=r"^[^\r\n,，]+$",
        ),
    ]


class NewAPIEmbeddingProbeResponse(BaseModel):
    """The vector dimension returned by the gateway."""

    dimensions: int
