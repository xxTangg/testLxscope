# -*- coding: utf-8 -*-
"""Credentials for a self-hosted NewAPI OpenAI-compatible gateway."""
from typing import Literal, Type, TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field, SecretStr, field_validator

from ._base import CredentialBase

if TYPE_CHECKING:
    from ..model import ChatModelBase, ModelCard


class NewAPICredential(CredentialBase):
    """An OpenAI-compatible NewAPI gateway with user-configured model IDs."""

    model_config = ConfigDict(title="NewAPI / OpenAI-compatible")

    type: Literal["newapi_credential"] = "newapi_credential"
    api_key: SecretStr = Field(description="The NewAPI access token.")
    base_url: str = Field(
        description="NewAPI API base URL, for example http://newapi.internal:3000/v1.",
    )
    models: str = Field(
        description="Model IDs enabled for this key, one per line or separated by commas.",
        json_schema_extra={"format": "textarea"},
    )
    context_size: int = Field(
        default=32768,
        gt=0,
        description="Context window for these models, in tokens.",
    )
    output_size: int = Field(
        default=4096,
        gt=0,
        description="Maximum output tokens for these models.",
    )

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Enter a valid http:// or https:// API base URL.")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Base URL cannot contain credentials, a query, or a fragment.")
        return value

    @field_validator("models")
    @classmethod
    def validate_models(cls, value: str) -> str:
        if not cls._model_names(value):
            raise ValueError("Enter at least one model ID.")
        return value

    @staticmethod
    def _model_names(value: str) -> list[str]:
        parts = value.replace("\r", "\n").replace(",", "\n").split("\n")
        return list(dict.fromkeys(name for part in parts if (name := part.strip())))

    @classmethod
    def get_chat_model_class(cls) -> Type["ChatModelBase"]:
        from ..model import OpenAIChatModel

        return OpenAIChatModel

    @classmethod
    def get_embedding_model_class(cls) -> None:
        return None

    @classmethod
    def get_tts_model_classes(cls) -> list:
        return []

    @classmethod
    def get_asr_model_classes(cls) -> list:
        return []

    @classmethod
    def get_realtime_model_classes(cls) -> list:
        return []

    def configured_models(self) -> list["ModelCard"]:
        """Build picker cards for the IDs configured on this credential."""
        from ..model import ModelCard, OpenAIChatModel

        schema = OpenAIChatModel.Parameters.model_json_schema()
        properties = schema["properties"]
        parameter_schema = {
            "type": "object",
            "properties": {
                key: properties[key]
                for key in ("max_tokens", "temperature", "top_p", "parallel_tool_calls")
            },
            "required": [],
        }
        parameter_schema["properties"]["max_tokens"]["maximum"] = self.output_size
        return [
            ModelCard(
                name=name,
                label=name,
                status="active",
                context_size=self.context_size,
                output_size=self.output_size,
                parameter_schema=parameter_schema,
                parameters_overrides={},
            )
            for name in self._model_names(self.models)
        ]
