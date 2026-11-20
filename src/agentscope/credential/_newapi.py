# -*- coding: utf-8 -*-
"""Credentials for a self-hosted NewAPI OpenAI-compatible gateway."""
from typing import Literal, Type, TYPE_CHECKING
from urllib.parse import urlsplit

from pydantic import (
    ConfigDict,
    Field,
    PositiveInt,
    SecretStr,
    field_validator,
)

from ._base import CredentialBase

if TYPE_CHECKING:
    from ..embedding import EmbeddingModelCard, OpenAIEmbeddingModel
    from ..model import ChatModelBase, ModelCard


class NewAPICredential(CredentialBase):
    """An OpenAI-compatible NewAPI gateway with user-configured model IDs."""

    model_config = ConfigDict(title="NewAPI / OpenAI-compatible")

    type: Literal["newapi_credential"] = "newapi_credential"
    api_key: SecretStr = Field(description="The gateway API key.")
    base_url: str = Field(
        default="http://lxcoreaihub.cnecc.com:5000/v1",
        description="Gateway API base URL, for example https://gateway.example.com/v1.",
    )
    models: str = Field(
        default="",
        description=(
            "Enabled chat model IDs separated by newlines, "
            "English or Chinese commas."
        ),
        json_schema_extra={"format": "textarea"},
    )
    embedding_models: dict[str, PositiveInt] = Field(
        default_factory=dict,
        description="Legacy embedding model dimensions saved by older clients.",
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

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: SecretStr) -> SecretStr:
        return SecretStr(value.get_secret_value().strip())

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Enter a valid http:// or https:// API base URL.")
        if parsed.username is not None or parsed.query or parsed.fragment:
            raise ValueError(
                "Base URL cannot contain credentials, a query, or a fragment."
            )
        # Accessing .port also validates the port syntax and range.
        if parsed.port == 0:
            raise ValueError("Base URL must use a valid port.")
        return value

    @field_validator("embedding_models")
    @classmethod
    def validate_embedding_models(
        cls, value: dict[str, int]
    ) -> dict[str, int]:
        if any(not name or name != name.strip() for name in value):
            raise ValueError("Enter a valid embedding model ID.")
        return value

    @staticmethod
    def _model_names(value: str) -> list[str]:
        parts = (
            value.replace("\r", "\n")
            .replace(",", "\n")
            .replace("，", "\n")
            .split("\n")
        )
        return list(
            dict.fromkeys(name for part in parts if (name := part.strip()))
        )

    @classmethod
    def get_chat_model_class(cls) -> Type["ChatModelBase"]:
        from ..model import OpenAIChatModel

        return OpenAIChatModel

    @classmethod
    def get_embedding_model_class(cls) -> Type["OpenAIEmbeddingModel"]:
        from ..embedding import OpenAIEmbeddingModel

        return OpenAIEmbeddingModel

    def configured_embedding_models(self) -> list["EmbeddingModelCard"]:
        """List the enabled embedding models with their gateway dimensions."""
        from ..embedding import EmbeddingModelCard

        return [
            EmbeddingModelCard(
                name=name,
                label=name,
                dimensions=dimensions,
                pass_dimensions=False,
            )
            for name, dimensions in self.embedding_models.items()
        ]

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
                for key in (
                    "max_tokens",
                    "temperature",
                    "top_p",
                    "parallel_tool_calls",
                )
            },
            "required": [],
        }
        parameter_schema["properties"]["max_tokens"][
            "maximum"
        ] = self.output_size
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
