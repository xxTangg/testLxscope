# -*- coding: utf-8 -*-
"""Cross-account rejection must precede all runtime and filesystem effects."""

import asyncio
import json
import os
import shutil
import socket
import tempfile
from pathlib import Path
from typing import Any
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipUnless

import httpx
import uvicorn
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

from agentscope.app import deps
from agentscope.app._router._chat import chat_router
from agentscope.app._router._session import session_router
from agentscope.app._router._workspace import (
    workspace_router,
    read_workspace_file,
)
from agentscope.app._service import (
    ChatService,
    SessionService,
    WorkspaceService,
    ResourceAccessService,
)
from agentscope.app._service._session_projection import SessionProjection
from agentscope.app._service._projectors import SubagentHitlProjector
from agentscope.app.access import DenyAllResourceAccessPolicy
from agentscope.app._manager import ChatRunRegistry
from agentscope.app.message_bus import InMemoryMessageBus, MessageBusKeys
from agentscope.app.storage import (
    SessionConfig,
    SessionRecord,
    AgentRecord,
    AgentData,
)
from agentscope.app.workspace_manager import LocalWorkspaceManager


class Storage:
    def __init__(self) -> None:
        self.sessions: dict[tuple[str, str, str], SessionRecord] = {}
        self.agents: dict[tuple[str, str], AgentRecord] = {}
        self.messages: dict[tuple[str, str], list[Any]] = {}
        self.teams: dict[tuple[str, str], Any] = {}

    async def get_session(self, owner: Any, agent: Any, sid: Any) -> Any:
        return self.sessions.get((owner, agent, sid))

    async def get_agent(self, owner: Any, agent: Any) -> Any:
        return self.agents.get((owner, agent))

    async def get_team(self, owner: Any, team: Any) -> Any:
        return self.teams.get((owner, team))

    async def delete_session(self, owner: Any, agent: Any, sid: Any) -> Any:
        return self.sessions.pop((owner, agent, sid), None) is not None

    async def upsert_message(self, owner: Any, sid: Any, message: Any) -> Any:
        self.messages.setdefault((owner, sid), []).append(message)


class Bus(InMemoryMessageBus):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled: list[Any] = []

    async def publish(self, channel: Any, payload: Any) -> Any:
        if channel == MessageBusKeys.session_cancel_channel():
            self.cancelled.append(payload)
        return await super().publish(channel, payload)


class UserIsolationSecurityTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.storage, self.bus = Storage(), Bus()
        self.manager = LocalWorkspaceManager(str(self.base))
        self.addAsyncCleanup(self.manager.close_all)
        self.workspaces = {}
        for owner in ("alice", "bob"):
            agent, sid = "agent-" + owner, "session-" + owner
            ws = await self.manager.get_workspace(owner, agent, sid)
            self.workspaces[owner] = ws
            Path(ws.workdir, "private.txt").write_text(owner + " private")
            self.storage.agents[owner, agent] = AgentRecord(
                id=agent, user_id=owner, data=AgentData(id=agent, name=owner)
            )
            self.storage.sessions[owner, agent, sid] = SessionRecord(
                id=sid,
                user_id=owner,
                agent_id=agent,
                config=SessionConfig(workspace_id=ws.workspace_id),
            )
        self.access = ResourceAccessService(
            self.storage, DenyAllResourceAccessPolicy()
        )
        self.workspace_service = WorkspaceService(
            self.storage, self.manager, "test-secret"
        )
        self.chat = ChatService(
            self.storage, self.manager, None, None, self.bus, self.access
        )
        self.sessions = SessionService(self.storage, self.bus)
        app = FastAPI()
        self.app = app
        for router in (chat_router, session_router, workspace_router):
            app.include_router(router)

        async def user(authorization: str = Header(default="")) -> Any:
            if authorization not in {"Bearer alice", "Bearer bob"}:
                raise HTTPException(401)
            return authorization.split()[1]

        app.dependency_overrides[deps.get_current_user_id] = user
        for key, value in (
            (deps.get_storage, self.storage),
            (deps.get_message_bus, self.bus),
            (deps.get_chat_service, self.chat),
            (deps.get_session_service, self.sessions),
            (deps.get_resource_access_service, self.access),
            (deps.get_chat_run_registry, ChatRunRegistry()),
            (deps.get_workspace_service, self.workspace_service),
        ):

            def bind(value: Any) -> Any:
                return lambda: value

            app.dependency_overrides[key] = bind(value)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer alice"},
        )
        self.addAsyncCleanup(self.client.aclose)
        self.foreign = {"agent_id": "agent-bob", "session_id": "session-bob"}

    async def test_foreign_chat_never_starts_or_publishes(self) -> None:
        response = await self.client.post(
            "/chat/", json={**self.foreign, "input": None}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            await self.bus.log_read(
                MessageBusKeys.session_events("session-bob")
            ),
            [],
        )
        self.assertEqual(self.storage.messages, {})

    async def test_background_chat_cannot_bypass_entrypoint_authorization(
        self,
    ) -> None:
        await self.chat.run("alice", "session-bob", "agent-bob")
        self.assertEqual(
            await self.bus.log_read(
                MessageBusKeys.session_events("session-bob")
            ),
            [],
        )
        self.assertEqual(self.storage.messages, {})

    async def test_foreign_confirmation_does_not_read_projection_or_enqueue(
        self,
    ) -> None:
        projection = SessionProjection(self.bus)
        pending = {
            "worker_session_id": "private-worker",
            "worker_agent_id": "private-agent",
            "reply_id": "reply-bob",
        }
        await projection.upsert(
            "session-bob", SubagentHitlProjector.KIND, "entry", pending
        )
        response = await self.client.post(
            "/chat/",
            json={
                **self.foreign,
                "input": {
                    "type": "USER_CONFIRM_RESULT",
                    "reply_id": "reply-bob",
                    "confirm_results": [],
                },
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("private-worker", response.text)
        self.assertEqual(
            await self.bus.queue_drain(MessageBusKeys.wakeup_queue()), []
        )
        self.assertEqual(
            await projection.list("session-bob", SubagentHitlProjector.KIND),
            [pending],
        )

    async def test_foreign_delete_has_no_side_effects(self) -> None:
        events = MessageBusKeys.session_events("session-bob")
        await self.bus.log_append(events, {"value": "unchanged"})
        projection = SessionProjection(self.bus)
        await projection.upsert(
            "session-bob",
            SubagentHitlProjector.KIND,
            "entry",
            {"reply_id": "pending"},
        )
        before_events = await self.bus.log_read(events)
        before_projection = await projection.list(
            "session-bob", SubagentHitlProjector.KIND
        )
        response = await self.client.delete(
            "/sessions/session-bob", params={"agent_id": "agent-bob"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(await self.bus.log_read(events), before_events)
        self.assertEqual(
            await projection.list("session-bob", SubagentHitlProjector.KIND),
            before_projection,
        )
        self.assertEqual(self.bus.cancelled, [])
        self.assertIn(
            ("bob", "agent-bob", "session-bob"), self.storage.sessions
        )

    async def test_owned_delete_still_cleans_events_and_record(self) -> None:
        await self.bus.log_append(
            MessageBusKeys.session_events("session-alice"), {"value": "old"}
        )
        response = await self.client.delete(
            "/sessions/session-alice", params={"agent_id": "agent-alice"}
        )
        self.assertEqual(response.status_code, 204)
        self.assertNotIn(
            ("alice", "agent-alice", "session-alice"), self.storage.sessions
        )
        self.assertEqual(
            await self.bus.log_read(
                MessageBusKeys.session_events("session-alice")
            ),
            [],
        )

    async def test_download_holds_open_file_through_directory_swap(
        self,
    ) -> None:
        ws = self.workspaces["alice"]
        folder = Path(ws.workdir, "switch")
        folder.mkdir()
        (folder / "private.txt").write_text("safe alice")
        path = "switch/private.txt"
        token, _ = self.workspace_service.sign_download_token(
            "alice", "agent-alice", "session-alice", path
        )
        response = await read_workspace_file(
            agent_id="agent-alice",
            session_id="session-alice",
            path=path,
            download=False,
            token=token,
            workspace_service=self.workspace_service,
        )
        folder.rename(folder.with_name("original"))
        folder.symlink_to(
            self.workspaces["bob"].workdir, target_is_directory=True
        )
        content = b"".join([part async for part in response.body_iterator])
        self.assertEqual(content, b"safe alice")

    async def test_swap_before_open_fails_closed(self) -> None:
        ws = self.workspaces["alice"]
        folder = Path(ws.workdir, "switch")
        folder.mkdir()
        path = str(folder / "private.txt")
        (folder / "private.txt").write_text("safe alice")
        folder.rename(folder.with_name("original"))
        folder.symlink_to(
            self.workspaces["bob"].workdir, target_is_directory=True
        )
        with self.assertRaises(PermissionError):
            async with ws.get_backend().open_read(path, root=ws.file_root):
                self.fail("A swapped symlink was opened")

    async def test_hardlinked_file_is_rejected(self) -> None:
        ws = self.workspaces["alice"]
        os.link(
            Path(self.workspaces["bob"].workdir, "private.txt"),
            Path(ws.workdir, "linked.txt"),
        )
        response = await self.client.post(
            "/workspace/files/download-token",
            params={
                "agent_id": "agent-alice",
                "session_id": "session-alice",
                "path": "linked.txt",
            },
        )
        self.assertEqual(response.status_code, 403)

    async def test_active_file_types_are_sandboxed_attachments(self) -> None:
        ws = self.workspaces["alice"]
        for name in ("attack.html", "attack.svg"):
            Path(ws.workdir, name).write_text(
                (
                    "<script>localStorage.getItem('agentscope_acce"
                    "ss_token')</script>"
                )
            )
            token, _ = self.workspace_service.sign_download_token(
                "alice", "agent-alice", "session-alice", name
            )
            response = await self.client.get(
                "/workspace/files",
                params={
                    "agent_id": "agent-alice",
                    "session_id": "session-alice",
                    "path": name,
                    "token": token,
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(
                response.headers["content-disposition"].startswith(
                    "attachment;"
                )
            )
            self.assertIn(
                "sandbox", response.headers["content-security-policy"]
            )

    @skipUnless(
        os.getenv("RUN_USER_SANDBOX_TESTS") == "1" and shutil.which("node"),
        "Requires the deployment's Node and Chromium runtimes",
    )
    async def test_browser_cannot_execute_downloaded_html_or_svg(self) -> None:
        urls = []
        for name in ("browser.html", "browser.svg"):
            Path(self.workspaces["alice"].workdir, name).write_text(
                "<svg xmlns='http://www.w3.org/2000/svg'><script>"
                "localStorage.setItem('stolen',"
                "localStorage.getItem('agentscope_access_token'))"
                "</script></svg>"
            )
            token, _ = self.workspace_service.sign_download_token(
                "alice", "agent-alice", "session-alice", name
            )
            urls.append(
                str(
                    httpx.URL(
                        "/workspace/files",
                        params={
                            "agent_id": "agent-alice",
                            "session_id": "session-alice",
                            "path": name,
                            "token": token,
                        },
                    )
                )
            )

        @self.app.get("/seed")
        async def seed() -> HTMLResponse:
            return HTMLResponse("<a id='file'>Open file</a>")

        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(self.app, log_level="error"))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            while not server.started:
                await asyncio.sleep(0.01)
            origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
            script = """
const {chromium}=require(
 '/usr/local/lib/node_modules/@playwright/mcp/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,
  executablePath:process.argv[2],args:['--no-sandbox']});
 try {
  const page=await browser.newPage();
  await page.goto(process.argv[1]+'/seed');
  await page.evaluate(()=>localStorage.setItem(
   'agentscope_access_token','SYNTHETIC_VICTIM_TOKEN'));
  const files=[];
  for(const path of JSON.parse(process.argv[3])) {
   await page.locator('#file').evaluate((e,url)=>e.href=url,
    process.argv[1]+path);
   const [download]=await Promise.all([
    page.waitForEvent('download'),page.locator('#file').click()]);
   await download.path(); files.push(download.suggestedFilename());
  }
  console.log(JSON.stringify({files,
   stolen:await page.evaluate(()=>localStorage.getItem('stolen'))}));
 } finally {await browser.close()}
})().catch(e=>{console.error(e);process.exit(1)});
"""
            binary = next(
                Path("/ms-playwright").glob("*/chrome-linux*/chrome")
            )
            process = await asyncio.create_subprocess_exec(
                "node",
                "-e",
                script,
                origin,
                str(binary),
                json.dumps(urls),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            output, errors = await asyncio.wait_for(process.communicate(), 30)
            self.assertEqual(process.returncode, 0, errors.decode())
            self.assertEqual(
                json.loads(output),
                {
                    "files": ["browser.html", "browser.svg"],
                    "stolen": None,
                },
            )
        finally:
            server.should_exit = True
            await serving
            listener.close()

    async def test_owned_team_confirmation_is_routed(self) -> None:
        leader = self.storage.sessions["alice", "agent-alice", "session-alice"]
        leader.team_id = "team-alice"
        self.storage.teams["alice", "team-alice"] = SimpleNamespace(
            id="team-alice", session_id=leader.id
        )
        self.storage.sessions["alice", "worker-alice", "worker-session"] = (
            SessionRecord(
                id="worker-session",
                user_id="alice",
                agent_id="worker-alice",
                team_id="team-alice",
                config=SessionConfig(workspace_id=leader.config.workspace_id),
            )
        )
        await SessionProjection(self.bus).upsert(
            leader.id,
            SubagentHitlProjector.KIND,
            "entry",
            {
                "reply_id": "reply",
                "worker_session_id": "worker-session",
                "worker_agent_id": "worker-alice",
            },
        )
        response = await self.client.post(
            "/chat/",
            json={
                "agent_id": leader.agent_id,
                "session_id": leader.id,
                "input": {
                    "type": "USER_CONFIRM_RESULT",
                    "reply_id": "reply",
                    "confirm_results": [],
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["session_id"], "worker-session")
        queued = await self.bus.queue_drain(MessageBusKeys.wakeup_queue())
        self.assertEqual(len(queued), 1)

    async def test_projection_cannot_forward_into_another_account(
        self,
    ) -> None:
        leader = self.storage.sessions["alice", "agent-alice", "session-alice"]
        leader.team_id = "team-alice"
        self.storage.teams["alice", "team-alice"] = SimpleNamespace(
            id="team-alice", session_id=leader.id
        )
        await SessionProjection(self.bus).upsert(
            leader.id,
            SubagentHitlProjector.KIND,
            "entry",
            {
                "reply_id": "reply",
                "worker_session_id": "session-bob",
                "worker_agent_id": "agent-bob",
            },
        )
        response = await self.client.post(
            "/chat/",
            json={
                "agent_id": leader.agent_id,
                "session_id": leader.id,
                "input": {
                    "type": "USER_CONFIRM_RESULT",
                    "reply_id": "reply",
                    "confirm_results": [],
                },
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            await self.bus.queue_drain(MessageBusKeys.wakeup_queue()), []
        )
