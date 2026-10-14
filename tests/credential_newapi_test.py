# -*- coding: utf-8 -*-
"""NewAPI credential and per-credential model catalogue tests."""
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock

from fastapi import HTTPException
from pydantic import ValidationError

from agentscope.app._router._model import list_models
from agentscope.app._router._schema._model import ListModelsRequest
from agentscope.app._service._model import get_model
from agentscope.app.storage import ChatModelConfig
from agentscope.credential import CredentialFactory, NewAPICredential


_DATA = {
    "type": "newapi_credential",
    "api_key": "test-token",
    "base_url": "http://newapi.internal:3000/v1/",
    "models": "qwen3, deepseek-v3\nqwen3",
    "context_size": 65536,
    "output_size": 8192,
}


class NewAPICredentialTest(TestCase):
    def test_factory_and_configured_cards(self) -> None:
        credential = CredentialFactory.from_dict(_DATA)
        self.assertIsInstance(credential, NewAPICredential)
        self.assertEqual("http://newapi.internal:3000/v1", credential.base_url)
        cards = credential.configured_models()
        self.assertEqual(["qwen3", "deepseek-v3"], [c.name for c in cards])
        self.assertEqual(65536, cards[0].context_size)
        self.assertEqual(8192, cards[0].output_size)

    def test_url_and_models_are_required(self) -> None:
        with self.assertRaises(ValidationError):
            NewAPICredential.model_validate({**_DATA, "base_url": "newapi.internal"})
        with self.assertRaises(ValidationError):
            NewAPICredential.model_validate({**_DATA, "models": " , \n "})


class NewAPIModelTest(IsolatedAsyncioTestCase):
    async def test_catalog_is_scoped_to_credential(self) -> None:
        access = MagicMock(
            resolve_credential=AsyncMock(return_value=SimpleNamespace(data=_DATA)),
        )
        response = await list_models(
            ListModelsRequest(
                provider="newapi_credential",
                credential_id="cred-1",
            ),
            user_id="user-1",
            access=access,
        )
        self.assertEqual(2, response.total)
        access.resolve_credential.assert_awaited_once_with("user-1", "cred-1")

    async def test_catalog_rejects_another_provider_credential(self) -> None:
        access = MagicMock(
            resolve_credential=AsyncMock(return_value=SimpleNamespace(data={
                "type": "openai_credential", "api_key": "test-token",
            })),
        )
        with self.assertRaises(HTTPException) as error:
            await list_models(
                ListModelsRequest(
                    provider="newapi_credential",
                    credential_id="cred-1",
                ),
                user_id="user-1",
                access=access,
            )
        self.assertEqual(400, error.exception.status_code)

    async def test_chat_uses_gateway_context_size(self) -> None:
        access = MagicMock(
            resolve_credential=AsyncMock(return_value=SimpleNamespace(data=_DATA)),
        )
        model = await get_model(
            "user-1",
            ChatModelConfig(
                type="newapi_credential",
                credential_id="cred-1",
                model="qwen3",
                parameters={},
            ),
            access,
        )
        self.assertEqual(65536, model.context_size)
        self.assertEqual("http://newapi.internal:3000/v1", str(model.client.base_url).rstrip("/"))
