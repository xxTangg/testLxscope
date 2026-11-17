# -*- coding: utf-8 -*-
"""Model discovery and embedding probes for New API gateways."""

import asyncio
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from ..._logging import logger
from ...credential import NewAPICredential
from ._access import ResourceAccessService

if TYPE_CHECKING:
    from ..storage import StorageBase

_MODEL_ENDPOINT_CAPABILITIES: dict[str, Literal["chat", "embedding"]] = {
    "openai": "chat",
    "embeddings": "embedding",
}


def _gateway_failure(
    endpoint: str,
    detail: str,
    *,
    model: str | None = None,
    cause: Exception | None = None,
    status_code: int = 502,
) -> HTTPException:
    """Log the failure without logging credentials or upstream content."""
    logger.warning(
        "New API request failed: endpoint=%s model=%r cause=%s detail=%s",
        endpoint,
        model,
        type(cause).__name__ if cause is not None else "InvalidResponse",
        detail,
    )
    return HTTPException(status_code=status_code, detail=detail)


async def get_owned_newapi_gateway(
    user_id: str,
    credential_id: str,
    storage: "StorageBase",
) -> "NewAPIGateway":
    """Resolve the gateway credential that a knowledge base owner can pin."""
    record = await storage.get_credential(user_id, credential_id)
    if record is None or record.data.get("type") != "newapi_credential":
        raise HTTPException(
            status_code=404, detail="Gateway credential not found."
        )
    ResourceAccessService.ensure_credential_enabled(record)
    credential = NewAPICredential.model_validate(record.data)
    return NewAPIGateway(
        credential.base_url,
        credential.api_key.get_secret_value(),
    )


class NewAPIModelCandidate(BaseModel):
    """A model and the compatible API endpoints advertised by its gateway."""

    id: str
    capabilities: list[Literal["chat", "embedding"]]
    capabilities_known: bool


class NewAPIGateway:
    """Read a gateway catalogue or probe its embeddings with one key."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url
        self._api_key = api_key

    async def check_chat_model(self, model: str) -> None:
        """Send a short chat completion to verify the configured model."""
        response = await self._request_json(
            "chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": "Reply OK."}],
                "max_tokens": 16,
                "stream": False,
            },
        )
        if (
            not isinstance(response.get("choices"), list)
            or not response["choices"]
        ):
            raise _gateway_failure(
                "chat/completions",
                "The gateway returned no chat completion.",
                model=model,
            )

    async def list_models(self) -> list[NewAPIModelCandidate]:
        """List accessible models and merge capabilities for duplicate IDs."""
        entries = await self._request("models")
        endpoints_by_id: dict[str, set[str]] = {}
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(
                entry.get("id"),
                str,
            ):
                continue
            model_id = entry["id"].strip()
            if not model_id:
                continue
            endpoints = endpoints_by_id.setdefault(model_id, set())
            advertised = entry.get("supported_endpoint_types")
            if isinstance(advertised, list):
                endpoints.update(
                    value for value in advertised if isinstance(value, str)
                )

        return [
            NewAPIModelCandidate(
                id=model_id,
                capabilities=[
                    capability
                    for endpoint, capability in (
                        _MODEL_ENDPOINT_CAPABILITIES.items()
                    )
                    if endpoint in endpoints
                ],
                capabilities_known=bool(endpoints),
            )
            for model_id, endpoints in sorted(endpoints_by_id.items())
        ]

    async def embedding_dimensions(self, model: str) -> int:
        """Measure the native dimension with a single short embedding call."""
        entries = await self._request(
            "embeddings",
            {"model": model, "input": ["test"], "encoding_format": "float"},
        )
        if len(entries) == 1 and isinstance(entries[0], dict):
            vector = entries[0].get("embedding") or entries[0].get(
                "dense_embedding"
            )
            if (
                isinstance(vector, list)
                and vector
                and all(type(value) in (int, float) for value in vector)
            ):
                return len(vector)
        raise _gateway_failure(
            "embeddings",
            "The gateway returned no embedding vector.",
            model=model,
        )

    async def _request(
        self,
        endpoint: str,
        payload: dict | None = None,
    ) -> list[Any]:
        result = await self._request_json(endpoint, payload)
        if not isinstance(result.get("data"), list):
            raise _gateway_failure(
                endpoint,
                "Gateway returned no model list or embedding vector.",
                model=payload.get("model") if payload else None,
            )
        return result["data"]

    async def _request_json(
        self,
        endpoint: str,
        payload: dict | None = None,
    ) -> dict:
        model = payload.get("model") if payload else None
        try:
            async with asyncio.timeout(12), httpx.AsyncClient(
                headers={"Authorization": f"Bearer {self._api_key}"},
                follow_redirects=False,
                timeout=httpx.Timeout(12, connect=5),
            ) as client:
                response = await client.request(
                    "GET" if payload is None else "POST",
                    f"{self._base_url}/{endpoint}",
                    json=payload,
                )
                response.raise_for_status()
                result = response.json()
                if (
                    not isinstance(result, dict)
                    or result.get("success") is False
                ):
                    raise ValueError("Invalid gateway response")
                return result
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise _gateway_failure(
                endpoint,
                "The gateway timed out.",
                model=model,
                cause=exc,
                status_code=504,
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise _gateway_failure(
                endpoint,
                f"Gateway returned HTTP {exc.response.status_code}.",
                model=model,
                cause=exc,
            ) from exc
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
            raise _gateway_failure(
                endpoint,
                "The gateway did not return a valid response.",
                model=model,
                cause=exc,
            ) from exc
