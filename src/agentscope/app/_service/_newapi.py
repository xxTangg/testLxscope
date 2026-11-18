# -*- coding: utf-8 -*-
"""Model discovery and embedding probes for New API gateways."""

import asyncio
from time import monotonic
from typing import TYPE_CHECKING, Any, Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from ..._logging import logger
from ...credential import NewAPICredential
from ._access import ResourceAccessService
from ._errors import UpstreamDiagnostic, log_upstream_failure

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
) -> HTTPException:
    """Log the failure without logging credentials or upstream content."""
    logger.warning(
        "New API request failed: endpoint=%s model=%r detail=%s",
        endpoint,
        model,
        detail,
    )
    return HTTPException(status_code=502, detail=detail)


class GatewayRequestError(HTTPException):
    """Preserve the existing gateway HTTP error and its diagnostic."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        diagnostic: UpstreamDiagnostic,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.diagnostic = diagnostic


class GatewayConnectionResult(BaseModel):
    """Outcome of a lightweight gateway connection check."""

    status: Literal["passed", "failed"]
    elapsed_ms: int
    diagnostic_id: str | None = None
    code: str | None = None
    http_status: int | None = None


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

    async def check_connection(self) -> GatewayConnectionResult:
        """Check the models endpoint without running inference."""
        started_at = monotonic()
        try:
            await self._request("models")
        except GatewayRequestError as exc:
            diagnostic = exc.diagnostic
            return GatewayConnectionResult(
                status="failed",
                elapsed_ms=diagnostic.elapsed_ms or 0,
                diagnostic_id=diagnostic.diagnostic_id,
                code=diagnostic.code,
                http_status=diagnostic.http_status,
            )
        return GatewayConnectionResult(
            status="passed",
            elapsed_ms=round((monotonic() - started_at) * 1000),
        )

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
        result = await self._request_json(endpoint, payload, expect_data=True)
        return result["data"]

    async def _request_json(
        self,
        endpoint: str,
        payload: dict | None = None,
        *,
        expect_data: bool = False,
    ) -> dict:
        model = payload.get("model") if payload else None
        started_at = monotonic()
        response = None
        invalid_response_detail = (
            "The gateway did not return a valid response."
        )
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
                if expect_data and not isinstance(result.get("data"), list):
                    invalid_response_detail = (
                        "Gateway returned no model list or embedding vector."
                    )
                    raise ValueError(invalid_response_detail)
                return result
        except (
            httpx.HTTPError,
            httpx.InvalidURL,
            TimeoutError,
            ValueError,
        ) as exc:
            diagnostic = log_upstream_failure(
                exc,
                operation="gateway",
                started_at=started_at,
                url=self._base_url,
                endpoint=endpoint,
                model=model,
                response=response,
            )
            if diagnostic.code == "timeout":
                status_code, detail = 504, "The gateway timed out."
            elif isinstance(exc, httpx.HTTPStatusError):
                status_code = 502
                detail = f"Gateway returned HTTP {exc.response.status_code}."
            else:
                status_code, detail = 502, invalid_response_detail
            raise GatewayRequestError(status_code, detail, diagnostic) from exc
