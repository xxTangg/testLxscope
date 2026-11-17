# -*- coding: utf-8 -*-
"""NewAPI credential and per-credential model catalogue tests."""
import json
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from agentscope.app._router._credential import (
    check_credential_model,
    credential_router,
    probe_newapi_embedding,
    set_credential_enabled,
    update_credential,
)
from agentscope.app._router._knowledge_base import (
    discover_kb_embedding_models,
    knowledge_base_router,
    list_kb_embedding_models,
    probe_kb_embedding,
)
from agentscope.app._router._model import list_models
from agentscope.app._router._schema._credential import (
    CheckCredentialModelRequest,
    NewAPIEmbeddingProbeRequest,
    SetCredentialEnabledRequest,
    UpdateCredentialRequest,
)
from agentscope.app._router._schema._model import ListModelsRequest
from agentscope.app._router._schema._knowledge_base import (
    KbEmbeddingProbeRequest,
)
from agentscope.app.deps import (
    get_current_user_id,
    get_knowledge_base_service,
    get_storage,
)
from agentscope.app.access import DenyAllResourceAccessPolicy
from agentscope.app._service import CredentialView, ResourceAccessService
from agentscope.app._service._embedding import build_embedding_model
from agentscope.app._service._knowledge_base import KnowledgeBaseService
from agentscope.app._service._model import get_model
from agentscope.app.rag.knowledge_base_manager import DimensionPolicy
from agentscope.app.storage import (
    ChatModelConfig,
    CredentialRecord,
    EmbeddingModelConfig,
)
from agentscope.app.storage._utils import _dump_with_secrets
from agentscope.app._service._newapi import get_owned_newapi_gateway
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
    def test_model_list_accepts_english_chinese_and_mixed_separators(
        self,
    ) -> None:
        """Typed and pasted model lists produce the same picker cards."""
        for models in (
            "qwen3, deepseek-v3",
            "qwen3，deepseek-v3",
            "qwen3\ndeepseek-v3",
            "\r\n， qwen3,， deepseek-v3\r\nqwen3， ,\n",
        ):
            with self.subTest(models=models):
                credential = NewAPICredential.model_validate(
                    {**_DATA, "models": models},
                )
                self.assertEqual(
                    ["qwen3", "deepseek-v3"],
                    [card.name for card in credential.configured_models()],
                )

    def test_factory_and_configured_cards(self) -> None:
        credential = CredentialFactory.from_dict(_DATA)
        self.assertIsInstance(credential, NewAPICredential)
        self.assertEqual("http://newapi.internal:3000/v1", credential.base_url)
        cards = credential.configured_models()
        self.assertEqual(["qwen3", "deepseek-v3"], [c.name for c in cards])
        self.assertEqual(65536, cards[0].context_size)
        self.assertEqual(8192, cards[0].output_size)

    def test_url_must_be_valid_and_model_selection_is_optional(self) -> None:
        with self.assertRaises(ValidationError):
            NewAPICredential.model_validate(
                {**_DATA, "base_url": "newapi.internal"}
            )
        credential = NewAPICredential.model_validate({**_DATA, "models": ""})
        self.assertEqual([], credential.configured_models())
        self.assertEqual({}, credential.embedding_models)


class NewAPIModelTest(IsolatedAsyncioTestCase):
    async def test_catalog_is_scoped_to_credential(self) -> None:
        access = MagicMock(
            resolve_credential=AsyncMock(
                return_value=SimpleNamespace(data=_DATA)
            ),
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
        access.resolve_credential.assert_awaited_once_with(
            "user-1",
            "cred-1",
            allow_disabled=True,
        )

    async def test_catalog_rejects_another_provider_credential(self) -> None:
        access = MagicMock(
            resolve_credential=AsyncMock(
                return_value=SimpleNamespace(
                    data={
                        "type": "openai_credential",
                        "api_key": "test-token",
                    }
                )
            ),
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
            resolve_credential=AsyncMock(
                return_value=SimpleNamespace(data=_DATA)
            ),
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
        self.assertEqual(
            "http://newapi.internal:3000/v1",
            str(model.client.base_url).rstrip("/"),
        )


class NewAPIGatewayTest(IsolatedAsyncioTestCase):
    async def test_repeated_create_ignores_existing_id(self) -> None:
        records = {}

        async def save(user_id, credential):
            records[credential.id] = credential
            return credential.id

        app = FastAPI()
        app.include_router(credential_router)
        storage = MagicMock(upsert_credential=AsyncMock(side_effect=save))
        app.dependency_overrides[get_current_user_id] = lambda: "user-1"
        app.dependency_overrides[get_storage] = lambda: storage
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://app.test",
        ) as client:
            first = await client.post(
                "/credential/", json={"data": {**_DATA, "name": "A"}}
            )
            first_id = first.json()["credential_id"]
            second = await client.post(
                "/credential/",
                json={
                    "data": {
                        **_DATA,
                        "id": first_id,
                        "name": "B",
                        "models": "model-b",
                    }
                },
            )
        self.assertEqual(201, first.status_code)
        self.assertEqual(201, second.status_code)
        second_id = second.json()["credential_id"]
        self.assertNotEqual(first_id, second_id)
        self.assertEqual(2, len(records))
        self.assertEqual("A", records[first_id].name)
        self.assertEqual("B", records[second_id].name)
        self.assertEqual("model-b", records[second_id].models)

    async def test_gateway_change_requires_model_confirmation(self) -> None:
        previous = CredentialRecord(
            id="cred-1",
            user_id="user-1",
            data={**_DATA, "base_url": _DATA["base_url"].rstrip("/")},
        )
        access = MagicMock(
            resolve_for_edit=AsyncMock(return_value=("user-1", previous)),
            get_resource=AsyncMock(
                return_value=CredentialView(
                    **previous.model_dump(),
                    editable=True,
                )
            ),
        )
        storage = MagicMock(upsert_credential=AsyncMock())
        data = {
            **previous.data,
            "base_url": "https://new-gateway.test/v1",
            "api_key": "new-key",
            "models": "model-new",
            "embedding_models": {"old-embedding": 768},
        }
        with self.assertRaises(HTTPException) as error:
            await update_credential(
                "cred-1",
                UpdateCredentialRequest(data=data),
                "user-1",
                storage,
                access,
            )
        self.assertEqual(409, error.exception.status_code)
        storage.upsert_credential.assert_not_awaited()
        await update_credential(
            "cred-1",
            UpdateCredentialRequest(data=data, models_confirmed=True),
            "user-1",
            storage,
            access,
        )
        saved = storage.upsert_credential.call_args.args[1]
        self.assertEqual("model-new", saved.models)
        self.assertEqual({}, saved.embedding_models)

    async def test_disabled_credentials_reject_runtime_and_can_be_reenabled(
        self,
    ) -> None:
        record = CredentialRecord(
            id="cred-1", user_id="user-1", data=_DATA.copy()
        )

        async def save(user_id, credential):
            record.data = _dump_with_secrets(credential)
            return record.id

        storage = MagicMock(
            get_credential=AsyncMock(return_value=record),
            upsert_credential=AsyncMock(side_effect=save),
        )
        access = ResourceAccessService(storage, DenyAllResourceAccessPolicy())
        view = await set_credential_enabled(
            "cred-1",
            SetCredentialEnabledRequest(enabled=False),
            "user-1",
            storage,
            access,
        )
        self.assertFalse(view.enabled)
        with self.assertRaises(HTTPException) as error:
            await access.resolve_credential("user-1", "cred-1")
        self.assertEqual(403, error.exception.status_code)
        with self.assertRaises(HTTPException):
            await get_owned_newapi_gateway("user-1", "cred-1", storage)
        with self.assertRaises(HTTPException):
            build_embedding_model(
                record,
                EmbeddingModelConfig(
                    type="newapi_credential",
                    credential_id="cred-1",
                    model="embed",
                    dimensions=3,
                ),
            )
        await set_credential_enabled(
            "cred-1",
            SetCredentialEnabledRequest(enabled=True),
            "user-1",
            storage,
            access,
        )
        self.assertIs(
            record, await access.resolve_credential("user-1", "cred-1")
        )

    async def test_chat_checks_report_actual_gateway_results(self) -> None:
        record = CredentialRecord(
            id="cred-1",
            user_id="user-1",
            data={**_DATA, "models": "chat-model,embedding-model"},
        )
        access = MagicMock(
            resolve_for_edit=AsyncMock(return_value=("user-1", record))
        )
        client_class = httpx.AsyncClient

        def gateway(request):
            self.assertTrue(request.url.path.endswith("/chat/completions"))
            payload = json.loads(request.content)
            if payload["model"] == "embedding-model":
                return httpx.Response(
                    400, json={"error": {"message": "not a chat model"}}
                )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"role": "assistant", "content": "OK"}}
                    ]
                },
            )

        with patch(
            "agentscope.app._service._newapi.httpx.AsyncClient",
            side_effect=lambda **kwargs: client_class(
                transport=httpx.MockTransport(gateway), **kwargs
            ),
        ):
            passed = await check_credential_model(
                "cred-1",
                CheckCredentialModelRequest(model="chat-model"),
                "user-1",
                access,
            )
            with self.assertLogs("as", level="WARNING") as logs:
                failed = await check_credential_model(
                    "cred-1",
                    CheckCredentialModelRequest(model="embedding-model"),
                    "user-1",
                    access,
                )
        self.assertEqual("passed", passed.status)
        self.assertEqual("failed", failed.status)
        self.assertIn("HTTP 400", failed.detail)
        self.assertEqual(1, len(logs.output))
        self.assertIn("endpoint=chat/completions", logs.output[0])
        self.assertIn("model='embedding-model'", logs.output[0])
        self.assertIn("HTTP 400", logs.output[0])
        self.assertNotIn(_DATA["api_key"], logs.output[0])
        self.assertNotIn("not a chat model", logs.output[0])

    async def test_embedding_probe_uses_saved_gateway(
        self,
    ) -> None:
        gateway_url = _DATA["base_url"].rstrip("/")
        access = MagicMock(
            resolve_for_edit=AsyncMock(
                return_value=(
                    "user-1",
                    SimpleNamespace(data={**_DATA, "base_url": gateway_url}),
                )
            )
        )

        def gateway(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                "Bearer test-token", request.headers["Authorization"]
            )
            self.assertEqual(f"{gateway_url}/embeddings", str(request.url))
            self.assertEqual(
                {
                    "model": "embed-alias",
                    "input": ["test"],
                    "encoding_format": "float",
                },
                json.loads(request.content),
            )
            return httpx.Response(
                200, json={"data": [{"embedding": [0.2, 0.4]}]}
            )

        transport = httpx.MockTransport(gateway)
        async_client = httpx.AsyncClient
        with patch(
            "agentscope.app._service._newapi.httpx.AsyncClient",
            side_effect=lambda **kwargs: async_client(
                transport=transport, **kwargs
            ),
        ) as client:
            settings = {"base_url": gateway_url, "credential_id": "cred-1"}
            result = await probe_newapi_embedding(
                NewAPIEmbeddingProbeRequest(model="embed-alias", **settings),
                "user-1",
                access,
            )
            self.assertEqual(2, result.dimensions)
            with self.assertRaises(HTTPException) as error:
                await probe_newapi_embedding(
                    NewAPIEmbeddingProbeRequest(
                        model="embed-alias",
                        **{**settings, "base_url": "https://other.test/v1"},
                    ),
                    "user-1",
                    access,
                )
            self.assertEqual(400, error.exception.status_code)
            self.assertEqual(1, client.call_count)

    async def test_edit_without_key_preserves_saved_secret(self) -> None:
        gateway_url = _DATA["base_url"].rstrip("/")
        record = CredentialView(
            id="cred-1",
            user_id="user-1",
            editable=True,
            data={**_DATA, "base_url": gateway_url},
        )
        access = MagicMock(
            resolve_for_edit=AsyncMock(return_value=("user-1", record)),
            get_resource=AsyncMock(return_value=record),
        )
        storage = MagicMock(upsert_credential=AsyncMock())
        data = {
            **record.data,
            "models": "",
            "embedding_models": {"embed-alias": 768},
        }
        del data["api_key"]
        await update_credential(
            "cred-1",
            UpdateCredentialRequest(data=data),
            "user-1",
            storage,
            access,
        )
        owner, saved = storage.upsert_credential.call_args.args
        self.assertEqual("user-1", owner)
        self.assertEqual("test-token", saved.api_key.get_secret_value())
        self.assertEqual([], saved.configured_models())
        self.assertEqual({"embed-alias": 768}, saved.embedding_models)

    async def test_kb_picker_creation_and_runtime_use_enabled_embedding(
        self,
    ) -> None:
        record = CredentialView(
            id="cred-1",
            user_id="user-1",
            editable=True,
            data={
                **_DATA,
                "embedding_models": {"embed-alias": 768, "other-embed": 1024},
            },
        )
        manager = MagicMock(
            get_dimension_policy=AsyncMock(
                return_value=DimensionPolicy(
                    kind="fixed",
                    dimension=768,
                )
            ),
            create_knowledge_base=AsyncMock(
                return_value=SimpleNamespace(id="kb-1")
            ),
        )
        access = MagicMock(list_resource=AsyncMock(return_value=[record]))
        catalogue = await list_kb_embedding_models("user-1", access, manager)
        self.assertEqual(
            ["embed-alias"], [c.name for c in catalogue.providers[0].models]
        )
        self.assertNotIn("api_key", catalogue.providers[0].credential.data)

        config = EmbeddingModelConfig(
            type="newapi_credential",
            credential_id="cred-1",
            model="embed-alias",
            dimensions=768,
        )
        service = KnowledgeBaseService(
            storage=MagicMock(get_credential=AsyncMock(return_value=record)),
            knowledge_base_manager=manager,
            blob_store=MagicMock(),
            message_bus=MagicMock(),
            resource_access_service=access,
        )
        with self.assertRaises(HTTPException) as error:
            await service.create_knowledge_base(
                "user-1",
                "KB",
                "",
                config.model_copy(update={"dimensions": 1024}),
            )
        self.assertEqual(409, error.exception.status_code)
        manager.create_knowledge_base.assert_not_awaited()
        await service.create_knowledge_base("user-1", "KB", "", config)
        manager.create_knowledge_base.assert_awaited_once()

        model = build_embedding_model(record, config)
        self.assertEqual(768, model.dimensions)
        self.assertFalse(model.pass_dimensions)
        self.assertEqual(_DATA["base_url"], str(model.client.base_url))
        await model.client.close()

    async def test_kb_discovers_and_probes_without_preregistering_models(
        self,
    ) -> None:
        record = SimpleNamespace(data={**_DATA, "models": ""})
        storage = MagicMock(get_credential=AsyncMock(return_value=record))
        client_class = httpx.AsyncClient

        def gateway(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                "Bearer test-token", request.headers["Authorization"]
            )
            if request.url.path.endswith("/models"):
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "id": "chat-only",
                                "supported_endpoint_types": ["openai"],
                            },
                            {
                                "id": "new-embedding",
                                "supported_endpoint_types": ["embeddings"],
                            },
                            {"id": "custom-alias"},
                        ]
                    },
                )
            return httpx.Response(
                200, json={"data": [{"embedding": [0.1] * 3}]}
            )

        with patch(
            "agentscope.app._service._newapi.httpx.AsyncClient",
            side_effect=lambda **kwargs: client_class(
                transport=httpx.MockTransport(gateway),
                **kwargs,
            ),
        ):
            candidates = await discover_kb_embedding_models(
                "cred-1", "user-1", storage
            )
            self.assertEqual(
                ["custom-alias", "new-embedding"],
                [model.id for model in candidates],
            )
            dimensions = await probe_kb_embedding(
                "cred-1",
                KbEmbeddingProbeRequest(model="new-embedding"),
                "user-1",
                storage,
            )
            self.assertEqual(3, dimensions.dimensions)
            manager = MagicMock(
                get_dimension_policy=AsyncMock(
                    return_value=DimensionPolicy(kind="any")
                ),
                create_knowledge_base=AsyncMock(
                    return_value=SimpleNamespace(id="kb-1")
                ),
            )
            service = KnowledgeBaseService(
                storage,
                manager,
                MagicMock(),
                MagicMock(),
                MagicMock(),
            )
            app = FastAPI()
            app.include_router(knowledge_base_router)
            app.dependency_overrides[get_current_user_id] = lambda: "user-1"
            app.dependency_overrides[
                get_knowledge_base_service
            ] = lambda: service
            async with client_class(
                transport=httpx.ASGITransport(app=app),
                base_url="http://app.test",
            ) as client:
                response = await client.post(
                    "/knowledge_bases/",
                    json={
                        "name": "KB",
                        "embedding_model_config": {
                            "type": "newapi_credential",
                            "credential_id": "cred-1",
                            "model": "new-embedding",
                        },
                    },
                )
            self.assertEqual(201, response.status_code, response.text)
            pinned = manager.create_knowledge_base.call_args.kwargs[
                "embedding_model_config"
            ]
            self.assertEqual(3, pinned.dimensions)
            self.assertIsInstance(pinned, EmbeddingModelConfig)

        storage.get_credential.assert_awaited_with("user-1", "cred-1")
        storage.get_credential.return_value = None
        with self.assertRaises(HTTPException) as error:
            await discover_kb_embedding_models(
                "other-user-credential", "user-1", storage
            )
        self.assertEqual(404, error.exception.status_code)

    async def test_empty_gateway_catalogue_is_available_to_kb_creation(
        self,
    ) -> None:
        record = CredentialView(
            id="cred-1",
            user_id="user-1",
            editable=True,
            data={**_DATA, "models": ""},
        )
        result = await list_kb_embedding_models(
            "user-1",
            MagicMock(list_resource=AsyncMock(return_value=[record])),
            MagicMock(
                get_dimension_policy=AsyncMock(
                    return_value=DimensionPolicy(kind="any")
                )
            ),
        )
        self.assertEqual(1, len(result.providers))
        self.assertEqual([], result.providers[0].models)
        self.assertNotIn("api_key", result.providers[0].credential.data)
