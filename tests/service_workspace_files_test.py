# -*- coding: utf-8 -*-
"""Account boundaries exercised through real file APIs and local workspaces."""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from agentscope.app._router._workspace import workspace_router
from agentscope.app._service import WorkspaceService, ChatService
from agentscope.message import Msg, TextBlock
from agentscope.app.deps import get_current_user_id, get_workspace_service
from agentscope.app.workspace_manager import (
    LocalWorkspaceManager,
    IsolationPolicy,
)


class _Storage:
    def __init__(self) -> None:
        self.sessions = {}

    async def get_session(
        self, user_id: str, agent_id: str, session_id: str
    ) -> SimpleNamespace | None:
        return self.sessions.get((user_id, agent_id, session_id))

    async def list_agents(self, user_id: str) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                id=agent, data=SimpleNamespace(name=f"Assistant {agent}")
            )
            for user, agent, _ in self.sessions
            if user == user_id
        ]


class WorkspaceFileEndpointTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.manager = LocalWorkspaceManager(str(self.base))
        self.addAsyncCleanup(self.manager.close_all)
        self.storage = _Storage()
        self.service = WorkspaceService(
            self.storage, self.manager, "test-secret"
        )
        self.workspaces = {}
        for user, agent in (("alice", "a1"), ("alice", "a2"), ("bob", "b1")):
            ws = await self.manager.get_workspace(user, agent, "session")
            Path(ws.workdir, "notes.txt").write_text(f"private:{user}:{agent}")
            self.workspaces[agent] = ws
            self.storage.sessions[user, agent, "session"] = SimpleNamespace(
                user_id=user,
                agent_id=agent,
                config=SimpleNamespace(workspace_id=ws.workspace_id, cwd=None),
            )
        app = FastAPI()
        app.include_router(workspace_router)

        async def authenticated_user(
            authorization: str = Header(default=""),
        ) -> str:
            # The file APIs must use the application's auth dependency;
            # a raw X-User-ID header must never bypass it.
            if authorization not in {"Bearer alice", "Bearer bob"}:
                raise HTTPException(401, "Sign in required")
            return authorization.removeprefix("Bearer ")

        app.dependency_overrides[get_current_user_id] = authenticated_user
        app.dependency_overrides[get_workspace_service] = lambda: self.service
        self.client = self.enterContext(TestClient(app))
        self.scope = {"agent_id": "a1", "session_id": "session"}
        self.headers = {"Authorization": "Bearer alice"}

    def browse(self, path: str = "") -> Any:
        return self.client.get(
            "/workspace/directories",
            params={**self.scope, "path": path},
            headers=self.headers,
        )

    def mint(self, path: str = "notes.txt", **scope: Any) -> Any:
        return self.client.post(
            "/workspace/files/download-token",
            params={**self.scope, "path": path, **scope},
            headers=self.headers,
        )

    def download(self, path: str = "notes.txt", **scope: Any) -> Any:
        minted = self.mint(path)
        self.assertEqual(minted.status_code, 200, minted.text)
        return self.client.get(
            "/workspace/files",
            params={
                **self.scope,
                "path": path,
                "token": minted.json()["token"],
                **scope,
            },
        )

    def test_default_directory_and_personal_root(self) -> None:
        result = self.browse().json()
        self.assertEqual(result["path"], "~/agents/a1")
        self.assertEqual(result["parent_path"], "~/agents")
        root = self.browse("~").json()
        self.assertIsNone(root["parent_path"])
        self.assertEqual(
            {e["name"] for e in root["entries"]}, {"agents", "shared"}
        )
        self.assertNotIn(str(self.base), str(root))

    def test_own_agents_have_friendly_names(self) -> None:
        result = self.browse("~/agents").json()
        self.assertEqual({e["name"] for e in result["entries"]}, {"a1", "a2"})
        self.assertEqual(
            {e["display_name"] for e in result["entries"]},
            {"Assistant a1", "Assistant a2"},
        )

    def test_can_read_own_other_agent_and_shared_directory(self) -> None:
        self.assertEqual(
            self.download("~/agents/a2/notes.txt").text, "private:alice:a2"
        )
        Path(self.base, "alice", "shared", "report.txt").write_text("shared")
        self.assertEqual(self.download("~/shared/report.txt").text, "shared")

    def test_parent_navigation_stops_at_personal_root(self) -> None:
        self.assertEqual(self.browse("..").json()["path"], "~/agents")
        for path in (
            "~/..",
            "../../..",
            str(self.base),
            str(self.base / "bob"),
            "~/../alice-extra",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.browse(path).status_code, 403)

    def test_all_file_entry_points_reject_other_accounts(self) -> None:
        path = str(Path(self.workspaces["b1"].workdir, "notes.txt"))
        self.assertEqual(self.mint(path).status_code, 403)
        for endpoint in ("preview-text", "preview-pdf"):
            result = self.client.get(
                f"/workspace/files/{endpoint}",
                params={**self.scope, "path": path},
                headers=self.headers,
            )
            self.assertEqual(result.status_code, 403)
        # A valid signature cannot bypass path authorization.
        token, _ = self.service.sign_download_token(
            "alice", "a1", "session", path
        )
        result = self.client.get(
            "/workspace/files",
            params={**self.scope, "path": path, "token": token},
        )
        self.assertEqual(result.status_code, 403)

    def test_symlink_escape_is_hidden_and_unreadable(self) -> None:
        link = Path(self.workspaces["a1"].workdir, "external")
        try:
            link.symlink_to(
                self.workspaces["b1"].workdir, target_is_directory=True
            )
        except OSError:
            self.skipTest("Symlink creation unavailable")
        self.assertNotIn(
            "external", {e["name"] for e in self.browse().json()["entries"]}
        )
        self.assertEqual(self.browse("external").status_code, 403)
        self.assertEqual(self.mint("external/notes.txt").status_code, 403)

    async def test_new_file_parent_symlink_cannot_escape(self) -> None:
        link = Path(self.workspaces["a1"].workdir, "external")
        try:
            link.symlink_to(
                self.workspaces["b1"].workdir, target_is_directory=True
            )
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaises(PermissionError):
            await self.workspaces["a1"].resolve_file_path("external/new.txt")

    def test_retargeted_symlink_is_rechecked_on_download(self) -> None:
        link = Path(self.workspaces["a1"].workdir, "linked.txt")
        try:
            link.symlink_to(Path(self.workspaces["a1"].workdir, "notes.txt"))
        except OSError:
            self.skipTest("Symlink creation unavailable")
        token = self.mint("linked.txt").json()["token"]
        link.unlink()
        link.symlink_to(Path(self.workspaces["b1"].workdir, "notes.txt"))
        result = self.client.get(
            "/workspace/files",
            params={**self.scope, "path": "linked.txt", "token": token},
        )
        self.assertEqual(result.status_code, 403)

    def test_download_token_is_bound_to_agent_session_and_path(self) -> None:
        self.assertEqual(self.download().text, "private:alice:a1")
        token = self.mint().json()["token"]
        for changes in (
            {"agent_id": "a2"},
            {"session_id": "other"},
            {"path": "~/agents/a2/notes.txt"},
        ):
            result = self.client.get(
                "/workspace/files",
                params={
                    **self.scope,
                    "path": "notes.txt",
                    "token": token,
                    **changes,
                },
            )
            self.assertEqual(result.status_code, 401)
        token, _ = self.service.sign_download_token(
            "alice", "a1", "session", "notes.txt", ttl=-1
        )
        result = self.client.get(
            "/workspace/files",
            params={**self.scope, "path": "notes.txt", "token": token},
        )
        self.assertEqual(result.status_code, 401)

    def test_authentication_cannot_be_spoofed_with_user_header(self) -> None:
        for endpoint in (
            "/workspace/directories",
            "/workspace/files/preview-text",
        ):
            result = self.client.get(
                endpoint,
                params={**self.scope, "path": "notes.txt"},
                headers={"X-User-ID": "bob"},
            )
            self.assertEqual(result.status_code, 401)
        result = self.client.get(
            "/workspace/files",
            params={**self.scope, "path": "notes.txt"},
            headers={"X-User-ID": "alice"},
        )
        self.assertEqual(result.status_code, 422)

    def test_missing_files_and_wrong_types_are_rejected(self) -> None:
        self.assertEqual(self.browse("missing").status_code, 404)
        self.assertEqual(self.browse("notes.txt").status_code, 400)
        self.assertEqual(self.mint("missing").status_code, 404)
        self.assertEqual(self.mint("~").status_code, 403)

    def test_preview_and_attachment_download_still_work(self) -> None:
        result = self.client.get(
            "/workspace/files/preview-text",
            params={**self.scope, "path": "notes.txt"},
            headers=self.headers,
        )
        self.assertEqual(result.json()["text"], "private:alice:a1")
        result = self.download(download=True)
        self.assertIn("attachment", result.headers["content-disposition"])
        self.assertEqual(result.headers["x-content-type-options"], "nosniff")

    async def test_forged_workspace_binding_is_rejected_before_cache_hit(
        self,
    ) -> None:
        self.storage.sessions["alice", "a1", "session"].config.workspace_id = (
            self.workspaces["b1"].workspace_id
        )
        self.assertEqual(self.browse().status_code, 403)
        await self.manager.close_all()
        self.assertEqual(self.browse().status_code, 403)

    async def test_sessions_keep_distinct_directories_when_requested(
        self,
    ) -> None:
        manager = LocalWorkspaceManager(
            str(self.base), isolation=IsolationPolicy.PER_SESSION
        )
        self.addAsyncCleanup(manager.close_all)
        first = await manager.get_workspace("alice", "a1", "s1")
        second = await manager.get_workspace("alice", "a1", "s2")
        self.assertNotEqual(first.workdir, second.workdir)
        self.assertEqual(first.file_root, second.file_root)

    def upload(self) -> Any:
        content = (
            b"---\nname: example\ndescription: An example skill\n---\nHello"
        )
        return self.client.post(
            "/workspace/skill/upload",
            params=self.scope,
            headers=self.headers,
            data={
                "manifest": json.dumps(
                    {
                        "entries": [
                            {"path": "example/SKILL.md", "size": len(content)}
                        ]
                    }
                )
            },
            files=[("files", ("SKILL.md", content, "text/plain"))],
        )

    def test_upload_stays_inside_the_account(self) -> None:
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.text)
        self.assertTrue(
            Path(
                self.workspaces["a1"].workdir,
                "skills",
                "a1",
                "example",
                "SKILL.md",
            ).is_file()
        )
        self.assertFalse(
            Path(self.workspaces["b1"].workdir, "skills", "a1").exists()
        )

    def test_upload_rejects_symlinked_destination(self) -> None:
        link = Path(self.workspaces["a1"].workdir, "skills", "a1")
        try:
            link.symlink_to(
                self.workspaces["b1"].workdir, target_is_directory=True
            )
        except OSError:
            self.skipTest("Symlink creation unavailable")
        self.assertEqual(self.upload().status_code, 403)
        self.assertFalse(
            Path(self.workspaces["b1"].workdir, "example").exists()
        )

    async def test_generated_attachment_paths_are_logical_and_confined(
        self,
    ) -> None:
        workspace = self.workspaces["a1"]
        link = Path(workspace.workdir, "external.txt")
        try:
            link.symlink_to(Path(self.workspaces["b1"].workdir, "notes.txt"))
        except OSError:
            self.skipTest("Symlink creation unavailable")
        reply = Msg(
            name="Assistant",
            role="assistant",
            finished_at="2026-11-16T00:00:00Z",
            content=[
                TextBlock(
                    text=(
                        f"Files: {workspace.workdir}/notes.txt "
                        f"and {workspace.workdir}/external.txt"
                    )
                )
            ],
        )
        chat = ChatService.__new__(ChatService)
        chat._message_bus = object()
        with patch(
            "agentscope.app._service._chat.publish_session_event",
            new=AsyncMock(return_value="event"),
        ):
            await chat._attach_workspace_artifacts(
                session_id="session", workspace=workspace, reply=reply
            )
        self.assertEqual(
            [f["path"] for f in reply.metadata["generated_files"]],
            ["~/agents/a1/notes.txt"],
        )

    async def test_fresh_sop_workspace_is_account_owned(self) -> None:
        workspace_id = await self.manager.new_workspace_id(user_id="alice")
        workspace = await self.manager.get_workspace(
            "alice", "a1", "sop", workspace_id
        )
        self.assertTrue(
            workspace.workdir.startswith(str(self.base / "alice" / "sessions"))
        )
        with self.assertRaises(PermissionError):
            await self.manager.get_workspace("bob", "b1", "sop", workspace_id)
