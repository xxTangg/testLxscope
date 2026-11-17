# -*- coding: utf-8 -*-
"""Document downloads require a signed browser capability."""

from types import SimpleNamespace
from typing import AsyncIterator
from unittest import TestCase
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentscope.app._router._knowledge_base import knowledge_base_router
from agentscope.app._service._download_token import sign_download_token
from agentscope.app.deps import get_knowledge_base_service


class DocumentDownloadAuthTests(TestCase):
    def setUp(self) -> None:
        async def content() -> AsyncIterator[bytes]:
            yield b"private document"

        self.service = SimpleNamespace(
            stream_document_content=AsyncMock(
                return_value=(
                    SimpleNamespace(
                        data=SimpleNamespace(
                            content_type="text/plain", filename="notes.txt"
                        )
                    ),
                    len(b"private document"),
                    content(),
                )
            )
        )
        app = FastAPI()
        app.state.download_secret = "test-secret"
        app.include_router(knowledge_base_router)
        app.dependency_overrides[get_knowledge_base_service] = (
            lambda: self.service
        )
        self.client = self.enterContext(TestClient(app))
        self.path = "/knowledge_bases/kb/documents/doc"

    def test_user_header_cannot_replace_download_capability(self) -> None:
        response = self.client.get(self.path, headers={"X-User-ID": "bob"})
        self.assertEqual(response.status_code, 422)
        self.service.stream_document_content.assert_not_awaited()

    def test_signature_must_match_the_document(self) -> None:
        token, _ = sign_download_token("test-secret", "alice", "kb/other/doc")
        response = self.client.get(self.path, params={"token": token})
        self.assertEqual(response.status_code, 401)
        self.service.stream_document_content.assert_not_awaited()

    def test_valid_capability_uses_its_verified_owner(self) -> None:
        token, _ = sign_download_token("test-secret", "alice", "kb/kb/doc")
        response = self.client.get(
            self.path, params={"token": token}, headers={"X-User-ID": "bob"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"private document")
        self.service.stream_document_content.assert_awaited_once_with(
            user_id="alice", knowledge_base_id="kb", document_id="doc"
        )
