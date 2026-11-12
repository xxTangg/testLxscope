# -*- coding: utf-8 -*-
"""Default skills, persistent user opt-outs and offline workspace loading."""

import asyncio
import io
import json
from pathlib import Path
import tempfile
from unittest import TestCase, IsolatedAsyncioTestCase
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

from hub_router_test import _fake_backends
from agentscope.app import create_app
from agentscope.app.hub import BuiltinSkillHub
from agentscope.app.storage import SkillRecord
from agentscope.app.workspace_manager import LocalWorkspaceManager
from agentscope.app._service._builtin_skills import (
    activate_workspace_builtin_skill,
    list_user_skills,
    list_workspace_skills,
    uninstall_user_skill,
)


def make_catalog(root: Path) -> BuiltinSkillHub:
    """Create two file-backed skills, including a companion script."""
    skills = []
    for name in ("alpha", "beta"):
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: 内网{name}\n---\n# {name}\n",
            encoding="utf-8",
        )
        (directory / "helper.py").write_text(
            "print('local')\n", encoding="utf-8"
        )
        skills.append({"name": name, "display_name": name, "license": "MIT"})
    (root / "manifest.json").write_text(
        json.dumps({"skills": skills}), encoding="utf-8"
    )
    return BuiltinSkillHub(root)


class BuiltinSkillRouterTest(TestCase):
    """Exercise the public library, restore and workspace APIs."""

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.hub = make_catalog(self.root / "catalog")
        self.storage, bus = _fake_backends()
        self.app = create_app(
            storage=self.storage,
            message_bus=bus,
            workspace_manager=LocalWorkspaceManager(
                str(self.root / "workspaces")
            ),
            skill_hubs=[self.hub],
            enable_index_worker=False,
        )
        self.client = self.enterContext(TestClient(self.app))

    def library(self, user="alice"):
        response = self.client.get("/skill", headers={"X-User-ID": user})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def scope(self, user="alice"):
        headers = {"X-User-ID": user}
        agent = self.client.post(
            "/agent/",
            json={"name": user, "system_prompt": "hi"},
            headers=headers,
        )
        agent_id = agent.json()["agent_id"]
        session = self.client.post(
            "/sessions/", json={"agent_id": agent_id}, headers=headers
        )
        return {
            "agent_id": agent_id,
            "session_id": session.json()["session_id"],
        }

    def test_defaults_for_every_account_without_registration_hook(self):
        self.assertEqual(
            [x["name"] for x in self.library()], ["alpha", "beta"]
        )
        self.assertEqual(
            [x["name"] for x in self.library("new-user")], ["alpha", "beta"]
        )
        self.assertNotEqual(
            self.library()[0]["id"], self.library("new-user")[0]["id"]
        )

    def test_uninstall_is_scoped_persistent_and_reinstallable(self):
        skill_id = self.library()[0]["id"]
        headers = {"X-User-ID": "alice"}
        self.assertEqual(
            self.client.delete(
                f"/skill/{skill_id}", headers=headers
            ).status_code,
            204,
        )
        self.assertEqual([x["name"] for x in self.library()], ["beta"])
        # A new catalog instance models restart/update; persisted opt-out wins.
        self.app.state.skill_hubs["builtin"] = BuiltinSkillHub(
            self.root / "catalog"
        )
        self.assertEqual([x["name"] for x in self.library()], ["beta"])
        self.assertEqual(len(self.library("bob")), 2)
        self.assertEqual(
            self.client.get(f"/skill/{skill_id}", headers=headers).status_code,
            404,
        )
        restored = self.client.post(
            "/hub/skill/builtin/cards/alpha/install", headers=headers
        )
        self.assertEqual(restored.status_code, 201, restored.text)
        self.assertEqual(restored.json()["id"], skill_id)
        self.assertEqual(len(self.library()), 2)

    def test_other_user_cannot_uninstall_using_another_accounts_id(self):
        skill_id = self.library()[0]["id"]
        response = self.client.delete(
            f"/skill/{skill_id}", headers={"X-User-ID": "bob"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(len(self.library()), 2)
        self.assertEqual(len(self.library("bob")), 2)

    def test_defaults_are_only_in_library_until_added(self):
        scope = self.scope()
        headers = {"X-User-ID": "alice"}
        response = self.client.get(
            "/workspace/skill", params=scope, headers=headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), [])
        skill_id = self.library()[0]["id"]
        self.client.delete(f"/skill/{skill_id}", headers=headers)
        for _ in range(2):
            response = self.client.get(
                "/workspace/skill", params=scope, headers=headers
            )
            self.assertEqual(response.json(), [])
        response = self.client.post(
            "/workspace/skill/from-library",
            params=scope,
            json={"skill_ids": [skill_id]},
            headers=headers,
        )
        self.assertIn(skill_id, response.json()["failed"])

    def test_workspace_add_and_remove_leave_account_library_intact(self):
        scope = self.scope()
        headers = {"X-User-ID": "alice"}
        response = self.client.post(
            "/workspace/skill/from-library",
            params=scope,
            json={"skill_ids": [self.library()[0]["id"]]},
            headers=headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["added"], ["alpha"])
        response = self.client.get(
            "/workspace/skill", params=scope, headers=headers
        )
        self.assertEqual([x["name"] for x in response.json()], ["alpha"])
        response = self.client.delete(
            "/workspace/skill/alpha", params=scope, headers=headers
        )
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual([x["name"] for x in self.library()], ["alpha", "beta"])
        response = self.client.get(
            "/workspace/skill", params=scope, headers=headers
        )
        self.assertEqual(response.json(), [])

    def test_catalog_browse_and_search_allow_offline_restore(self):
        headers = {"X-User-ID": "alice"}
        hubs = self.client.get("/hub/skill", headers=headers).json()
        self.assertEqual(hubs[0]["display_name"], "系统内置")
        cards = self.client.get(
            "/hub/skill/builtin/cards", params={"q": "alpha"}, headers=headers
        ).json()
        self.assertEqual([x["name"] for x in cards["cards"]], ["alpha"])
        self.assertIsNone(cards["cards"][0]["markdown"])


class BuiltinSkillServiceTest(IsolatedAsyncioTestCase):
    """No read-time writes, uploads are preserved, archives are complete."""

    async def asyncSetUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.hub = make_catalog(self.root / "catalog")
        self.hubs = {"builtin": self.hub}
        self.storage, _ = _fake_backends()
        await self.storage.__aenter__()
        self.addAsyncCleanup(self.storage.aclose)

    async def test_reads_do_not_write_or_resurrect_preferences(self):
        await list_user_skills(self.storage, self.hubs, "alice")
        self.assertEqual(await self.storage.list_skills("alice"), [])
        record = self.hub.record("alice", "alpha")
        await uninstall_user_skill(self.storage, self.hubs, "alice", record.id)
        stored = await self.storage.get_skill("alice", record.id)
        self.assertFalse(stored.enabled)
        records = await asyncio.gather(
            *[
                list_user_skills(self.storage, self.hubs, "alice")
                for _ in range(6)
            ]
        )
        self.assertTrue(
            all([x.name for x in items] == ["beta"] for items in records)
        )

    async def test_existing_personal_skill_with_same_name_is_preserved(self):
        uploaded = SkillRecord(
            user_id="alice", name="alpha", markdown="personal"
        )
        await self.storage.upsert_skill("alice", uploaded)
        records = await list_user_skills(self.storage, self.hubs, "alice")
        alpha = next(x for x in records if x.name == "alpha")
        self.assertEqual(alpha.id, uploaded.id)
        self.assertIsNone(alpha.hub_id)

    async def test_archive_contains_companions_and_marker_without_network(
        self,
    ):
        with patch(
            "socket.socket.connect",
            side_effect=AssertionError("Unexpected network"),
        ):
            archive = await self.hub.download("alice", "alpha")
            payload = b"".join([chunk async for chunk in archive.stream])
        with zipfile.ZipFile(io.BytesIO(payload)) as bundle:
            self.assertIn("helper.py", bundle.namelist())
            marker = json.loads(bundle.read(".agentscope-builtin.json"))
            self.assertEqual(marker["card_id"], "alpha")
            self.assertIs(marker["added_to_workspace"], True)

    async def test_legacy_copy_is_hidden_until_added_and_preserves_edits(
        self,
    ):
        manager = LocalWorkspaceManager(str(self.root / "workspaces"))
        workspace = await manager.get_workspace(
            "alice", "agent", "session", None
        )
        record = self.hub.record("alice", "alpha")
        archive = await self.hub.download("alice", "alpha")
        await workspace.add_skill_archive(
            archive.stream, archive.format, "alpha", agent_id="agent"
        )
        (alpha,) = await workspace.list_skills(agent_id="agent")
        backend = workspace.get_backend()
        marker_path = backend.join_path(alpha.dir, ".agentscope-builtin.json")
        marker = json.loads(await backend.read_file(marker_path))
        del marker["added_to_workspace"]
        await backend.write_file(marker_path, json.dumps(marker).encode())
        helper_path = backend.join_path(alpha.dir, "helper.py")
        await backend.write_file(helper_path, b"print('custom')\n")

        self.assertEqual(await list_workspace_skills(workspace, "agent"), [])
        self.assertTrue(
            await activate_workspace_builtin_skill(workspace, "agent", record)
        )
        skills = await list_workspace_skills(workspace, "agent")
        self.assertEqual(
            [skill.name for skill in skills], ["alpha"]
        )
        self.assertEqual(await backend.read_file(helper_path), b"print('custom')\n")

    async def test_real_catalog_has_ten_valid_self_contained_skills(self):
        hub = BuiltinSkillHub(
            Path(__file__).resolve().parents[1] / "assets/builtin_skills"
        )
        self.assertEqual(len(hub.cards), 10)
        for card in hub.cards.values():
            self.assertTrue(card.description)
            self.assertTrue(card.display_name)
            self.assertIn("内", card.description + (card.markdown or ""))

    async def test_sql_preferences_survive_storage_reopen(self):
        from agentscope.app.storage import AsyncSQLAlchemyStorage

        url = f"sqlite+aiosqlite:///{self.root / 'skills.db'}"
        async with AsyncSQLAlchemyStorage(url) as storage:
            record = self.hub.record("alice", "alpha")
            await uninstall_user_skill(storage, self.hubs, "alice", record.id)
        async with AsyncSQLAlchemyStorage(url) as storage:
            records = await list_user_skills(storage, self.hubs, "alice")
            self.assertEqual([x.name for x in records], ["beta"])
            self.assertEqual(
                len(await list_user_skills(storage, self.hubs, "bob")), 2
            )
