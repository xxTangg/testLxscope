# -*- coding: utf-8 -*-
"""Account initialization with real auth, storage and ownership routes."""

import asyncio
import json
from pathlib import Path
import sys
from unittest import IsolatedAsyncioTestCase

import fakeredis
import httpx
from fastapi import FastAPI

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "examples/agent_service")
)
from auth import JWTAuthService, RegisterRequest, _ACCOUNTS_KEY  # noqa: E402
from agentscope.app import deps  # noqa: E402
from agentscope.app._router._agent import agent_router  # noqa: E402
from agentscope.app._service import ResourceAccessService  # noqa: E402
from agentscope.app.access import DenyAllResourceAccessPolicy  # noqa: E402
from agentscope.app.storage import (  # noqa: E402
    AgentData,
    AgentRecord,
    RedisStorage,
)


class AccountOnboardingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.redis = fakeredis.FakeAsyncRedis(decode_responses=True)
        self.addAsyncCleanup(self.redis.aclose)
        self.storage = RedisStorage()
        self.storage._client = self.redis
        self.auth = JWTAuthService(
            self.storage, "synthetic-test-secret-" * 3, 60
        )
        app = FastAPI()
        app.include_router(self.auth.router)
        app.include_router(agent_router)
        app.dependency_overrides[deps.get_current_user_id] = (
            self.auth.get_current_user_id
        )
        app.dependency_overrides[deps.get_storage] = lambda: self.storage
        access = ResourceAccessService(
            self.storage, DenyAllResourceAccessPolicy()
        )
        app.dependency_overrides[deps.get_resource_access_service] = (
            lambda: access
        )
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://fixture"
        )
        self.addAsyncCleanup(self.client.aclose)

    async def register(self, username: str) -> dict:
        response = await self.client.post(
            "/auth/register",
            json={"username": username, "password": "synthetic-password"},
        )
        self.assertEqual(response.status_code, 201)
        return response.json()

    async def test_registration_creates_one_private_general_agent(
        self,
    ) -> None:
        alice, bob = await self.register("alice"), await self.register("bob")
        self.assertIs(alice["show_tour"], True)
        self.assertIs(bob["show_tour"], True)
        alice_agents = await self.storage.list_agents(alice["user"]["id"])
        bob_agents = await self.storage.list_agents(bob["user"]["id"])
        self.assertEqual(len(alice_agents), 1)
        self.assertEqual(len(bob_agents), 1)
        self.assertEqual(alice_agents[0].data.name, "通用智能体")
        self.assertEqual(bob_agents[0].data.name, "通用智能体")
        self.assertNotEqual(alice_agents[0].id, bob_agents[0].id)
        self.assertIsNone(
            await self.storage.get_agent(bob["user"]["id"], alice_agents[0].id)
        )
        response = await self.client.get(
            "/agent/",
            headers={"Authorization": "Bearer " + bob["access_token"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [entry["id"] for entry in response.json()["agents"]],
            [bob_agents[0].id],
        )

    async def test_concurrent_empty_account_logins_do_not_duplicate_agents(
        self,
    ) -> None:
        registered = await self.register("alice")
        owner = registered["user"]["id"]
        old = (await self.storage.list_agents(owner))[0]
        await self.storage.delete_agent(owner, old.id)
        responses = await asyncio.gather(
            *[
                self.client.post(
                    "/auth/login",
                    json={
                        "username": "alice",
                        "password": "synthetic-password",
                    },
                )
                for _ in range(8)
            ]
        )
        self.assertTrue(
            all(response.status_code == 200 for response in responses)
        )
        self.assertTrue(
            all(response.json()["show_tour"] is False for response in responses)
        )
        agents = await self.storage.list_agents(owner)
        self.assertEqual(len(agents), 1)
        self.assertEqual(agents[0].id, old.id)

    async def test_profile_refresh_initializes_a_signed_in_empty_account(
        self,
    ) -> None:
        registered = await self.register("alice")
        owner = registered["user"]["id"]
        old = (await self.storage.list_agents(owner))[0]
        await self.storage.delete_agent(owner, old.id)
        response = await self.client.get(
            "/auth/me",
            headers={"Authorization": "Bearer " + registered["access_token"]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("show_tour", response.json())
        self.assertEqual(len(await self.storage.list_agents(owner)), 1)

    async def test_login_preserves_existing_custom_agents(self) -> None:
        registered = await self.register("alice")
        owner = registered["user"]["id"]
        old = (await self.storage.list_agents(owner))[0]
        await self.storage.delete_agent(owner, old.id)
        custom = AgentRecord(
            user_id=owner, data=AgentData(name="My custom agent")
        )
        await self.storage.upsert_agent(owner, custom)
        response = await self.client.post(
            "/auth/login",
            json={"username": "alice", "password": "synthetic-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [a.id for a in await self.storage.list_agents(owner)], [custom.id]
        )

    async def test_failed_login_cannot_initialize_an_empty_account(
        self,
    ) -> None:
        registered = await self.register("alice")
        owner = registered["user"]["id"]
        await self.storage.delete_agent(
            owner, (await self.storage.list_agents(owner))[0].id
        )
        response = await self.client.post(
            "/auth/login",
            json={"username": "alice", "password": "incorrect-password"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(await self.storage.list_agents(owner), [])

    async def test_duplicate_registration_creates_no_extra_agent(self) -> None:
        registered = await self.register("alice")
        response = await self.client.post(
            "/auth/register",
            json={"username": "alice", "password": "synthetic-password"},
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            len(await self.storage.list_agents(registered["user"]["id"])), 1
        )
        self.assertEqual(
            len(await self.redis.keys("agentscope:user:*:agents")), 1
        )

    async def test_concurrent_logins_claim_a_pending_tour_once(self) -> None:
        # Pause the registration flow after saving the account, before the
        # automatic login response claims the tour. All requests see it pending.
        account = await self.auth._register(
            RegisterRequest(username="alice", password="synthetic-password"),
        )
        responses = await asyncio.gather(
            *(self.auth._login_response(account) for _ in range(8)),
        )
        self.assertEqual(sum(response.show_tour for response in responses), 1)

    async def test_legacy_account_without_marker_does_not_show_tour(
        self,
    ) -> None:
        await self.register("alice")
        record = json.loads(await self.redis.hget(_ACCOUNTS_KEY, "alice"))
        del record["chat_tour_claimed"]
        await self.redis.hset(_ACCOUNTS_KEY, "alice", json.dumps(record))

        response = await self.client.post(
            "/auth/login",
            json={"username": "alice", "password": "synthetic-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.json()["show_tour"], False)
