# -*- coding: utf-8 -*-
"""Real user containers; opt in with RUN_USER_SANDBOX_TESTS=1."""

import json
import os
import uuid
from typing import Any
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, skipUnless

from agentscope.app.workspace_manager import UserWorkspaceManager
from agentscope.app._service import WorkspaceService
from agentscope.app._router._workspace import preview_workspace_file_pdf
from agentscope.mcp import MCPClient, StdioMCPConfig
from agentscope.state import AgentState


@skipUnless(
    os.getenv("RUN_USER_SANDBOX_TESTS") == "1",
    "Requires isolated Docker test services",
)
class UserSandboxIntegrationTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.prefix = "isolation-check-" + uuid.uuid4().hex[:10]
        self.manager = UserWorkspaceManager(
            image=os.getenv("TEST_SANDBOX_IMAGE", "isolation-fix-sandbox:dev"),
            prefix=self.prefix,
            egress_container=os.environ["TEST_EGRESS_CONTAINER"],
        )
        await self.manager.__aenter__()
        self.addAsyncCleanup(self.cleanup)
        self.alice = await self.manager.get_workspace(
            "alice", "agent-alice", "session-alice"
        )
        self.bob = await self.manager.get_workspace(
            "bob", "agent-bob", "session-bob"
        )
        await self.alice.get_backend().write_file(
            self.alice.workdir + "/private.txt", b"alice-only"
        )
        await self.bob.get_backend().write_file(
            self.bob.workdir + "/private.txt", b"bob-only"
        )

    async def cleanup(self) -> None:
        import aiodocker

        await self.manager.__aexit__()
        async with aiodocker.Docker() as docker:
            for owner in ("alice", "bob"):
                name = self.manager._name(owner)
                assert name.startswith(self.prefix + "-user-")
                volume = await docker.volumes.get(name)
                await volume.delete()

    async def test_builtin_read_cannot_see_other_account(self) -> None:
        read = next(
            t for t in await self.alice.list_tools() if t.name == "Read"
        )
        result = await read(
            file_path=self.bob.workdir + "/private.txt",
            _agent_state=AgentState(),
        )
        self.assertNotIn(
            "bob-only", json.dumps(result.model_dump(mode="json"))
        )
        self.assertIn(
            "does not exist", json.dumps(result.model_dump(mode="json"))
        )
        result = await self.alice.get_backend().exec_shell(
            [
                "python3",
                "-c",
                (
                    "import os,json; print(json.dumps({'uid':os.ge"
                    "tuid(),'secret':os.getenv('AUDIT_SERVICE_SECR"
                    "ET'),'socket':os.path.exists('/var/run/docker"
                    ".sock'),'app':os.path.exists('/app')}))"
                ),
            ]
        )
        self.assertEqual(
            json.loads(result.stdout),
            {"uid": 1000, "secret": None, "socket": False, "app": False},
        )
        write = await self.alice.get_backend().exec_shell(
            ["python3", "-c", "open('/etc/escape','w').write('x')"]
        )
        self.assertFalse(write.ok())

    async def test_same_account_agent_roots_and_streams(self) -> None:
        other = await self.manager.get_workspace(
            "alice", "other-agent", "other-session"
        )
        self.assertNotEqual(other.workdir, self.alice.workdir)
        self.assertEqual(
            await other.get_backend().read_file(
                self.alice.workdir + "/private.txt"
            ),
            b"alice-only",
        )
        with self.assertRaises(PermissionError):
            await self.manager.get_workspace(
                "bob", "agent-bob", "s", self.alice.workspace_id
            )
        payload = bytes(range(256)) * 12000
        await other.get_backend().write_file(
            other.workdir + "/large.bin", payload
        )
        async with other.get_backend().open_read(
            other.workdir + "/large.bin", root=other.file_root
        ) as opened:
            self.assertEqual(opened.size, len(payload))
            self.assertEqual(
                b"".join([x async for x in opened.stream]), payload
            )

    async def test_account_network_blocks_peers_and_private_proxy_targets(
        self,
    ) -> None:
        details = await self.manager._runtimes["bob"].show()
        address = next(iter(details["NetworkSettings"]["Networks"].values()))[
            "IPAddress"
        ]
        # Listen on the peer interface to make this a real network test.
        listener = await self.bob.get_backend().exec_shell(
            [
                "python3",
                "-c",
                """
import socket,subprocess,time
subprocess.Popen(['python3','-m','http.server','19080','--bind','0.0.0.0'],
 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
for _ in range(50):
 try:
  with socket.create_connection(('127.0.0.1',19080),timeout=.1): break
 except OSError: time.sleep(.05)
else: raise RuntimeError('Peer fixture did not start')
""",
            ],
            timeout=5,
        )
        self.assertTrue(listener.ok(), listener.stderr)
        own_probe = await self.bob.get_backend().exec_shell(
            [
                "python3",
                "-c",
                "import socket,sys; s=socket.socket();s.settimeout(1);"
                "print(s.connect_ex((sys.argv[1],19080)))",
                address,
            ]
        )
        self.assertEqual(int(own_probe.stdout), 0)
        probe = await self.alice.get_backend().exec_shell(
            [
                "python3",
                "-c",
                (
                    "import socket,sys; s=socket.socket();s.settim"
                    "eout(1);print(s.connect_ex((sys.argv[1],19080)"
                    "))"
                ),
                address,
            ]
        )
        self.assertNotEqual(int(probe.stdout), 0)
        network = await self.manager._client.networks.get(
            self.manager._name("alice")
        )
        topology = await network.show()
        self.assertEqual(
            topology["Options"]["com.docker.network.bridge.gateway_mode_ipv4"],
            "isolated",
        )
        # Isolated bridge mode does not assign a host-side bridge address.
        route = await self.alice.get_backend().exec_shell(
            ["python3", "-c", "print(open('/proc/net/route').read())"]
        )
        self.assertFalse(
            any(
                line.split()[1] == "00000000"
                for line in route.stdout.decode().strip().splitlines()[1:]
            )
        )
        probe = await self.alice.get_backend().exec_shell(
            [
                "python3",
                "-c",
                (
                    "import http.client; c=http.client.HTTPConnect"
                    "ion('egress',3128,timeout=5);c.request('GET',"
                    "'http://169.254.169.254/latest/meta-data/');p"
                    "rint(c.getresponse().status)"
                ),
            ]
        )
        self.assertEqual(probe.stdout.strip(), b"403")
        probe = await self.alice.get_backend().exec_shell(
            [
                "python3",
                "-c",
                (
                    "import http.client; c=http.client.HTTPConnect"
                    "ion('egress',3128,timeout=5);c.request('GET',"
                    "'cache_object://localhost/info');print(c.getr"
                    "esponse().status)"
                ),
            ]
        )
        self.assertEqual(probe.stdout.strip(), b"403")
        probe = await self.alice.get_backend().exec_shell(
            [
                "python3",
                "-c",
                (
                    "import http.client; c=http.client.HTTPConnect"
                    "ion('egress',3128,timeout=5);c.request('CONNE"
                    "CT','127.0.0.1:8000');print(c.getresponse().s"
                    "tatus)"
                ),
            ]
        )
        self.assertEqual(probe.stdout.strip(), b"403")
        public = await self.alice.get_backend().exec_shell(
            [
                "python3",
                "-c",
                (
                    "import urllib.request; print(urllib.request.u"
                    "rlopen('https://example.com',timeout=15).stat"
                    "us)"
                ),
            ],
            timeout=20,
        )
        self.assertTrue(public.ok(), public.stderr)
        self.assertEqual(public.stdout.strip(), b"200")

    async def test_mcp_executes_in_account_container(self) -> None:
        path = self.alice.workdir + "/test_mcp.py"
        script = (
            "from mcp.server.fastmcp import FastMCP\nimport"
            " os\nm=FastMCP('audit')\n@m.tool()\ndef identity"
            "()->str: return str(os.getuid())+':'+str(os.g"
            "etenv('AUDIT_SERVICE_SECRET'))\nm.run(transpor"
            "t='stdio')\n"
        )
        await self.alice.get_backend().write_file(path, script.encode())
        client = await self.alice.add_mcp(
            MCPClient(
                name="audit",
                mcp_config=StdioMCPConfig(command="python3", args=[path]),
                is_stateful=True,
            ),
            agent_id="agent-alice",
            session_id="session-alice",
        )
        tool = await client.get_tool("identity")
        result = await tool()
        self.assertIn("1000:None", json.dumps(result.model_dump(mode="json")))
        await self.manager.close(self.alice.workspace_id)
        reopened = await self.manager.get_workspace(
            "alice", "agent-alice", "session-alice", self.alice.workspace_id
        )
        clients = await reopened.list_mcps(
            agent_id="agent-alice", session_id="session-alice"
        )
        restored = next(client for client in clients if client.name == "audit")
        result = await (await restored.get_tool("identity"))()
        self.assertIn("1000:None", json.dumps(result.model_dump(mode="json")))

    async def test_office_preview_stays_in_account_runtime(self) -> None:
        path = self.alice.workdir + "/sample.docx"
        result = await self.alice.get_backend().exec_shell(
            [
                "python3",
                "-c",
                (
                    "from docx import Document;import sys;d=Docume"
                    "nt();d.add_paragraph('Isolated office preview"
                    "');d.save(sys.argv[1])"
                ),
                path,
            ]
        )
        self.assertTrue(result.ok(), result.stderr)

        class Storage:
            async def get_session(
                inner, owner: Any, agent: Any, sid: Any
            ) -> Any:
                return SimpleNamespace(
                    user_id=owner,
                    agent_id=agent,
                    config=SimpleNamespace(
                        workspace_id=self.alice.workspace_id
                    ),
                )

        service = WorkspaceService(Storage(), self.manager, "test")
        response = await preview_workspace_file_pdf(
            agent_id="agent-alice",
            session_id="session-alice",
            path=path,
            user_id="alice",
            workspace_service=service,
        )
        self.assertTrue(response.body.startswith(b"%PDF"))

    async def test_runtime_and_volume_survive_workspace_eviction(self) -> None:
        identity = self.alice.workspace_id
        await self.manager.close(identity)
        reopened = await self.manager.get_workspace(
            "alice", "agent-alice", "session-alice", identity
        )
        self.assertEqual(
            await reopened.get_backend().read_file(
                reopened.workdir + "/private.txt"
            ),
            b"alice-only",
        )

    async def test_failed_runtime_start_removes_network_and_keeps_only_volume(
        self,
    ) -> None:
        self.manager._image = (
            "agentscope-test-image-that-does-not-exist:invalid"
        )
        with self.assertRaises(Exception):
            await self.manager.get_workspace(
                "startup-failure", "agent", "session"
            )
        name = self.manager._name("startup-failure")
        self.assertNotIn("startup-failure", self.manager._runtimes)
        networks = await self.manager._client.networks.list(
            filters={"name": [name]}
        )
        self.assertFalse(any(n["Name"] == name for n in networks))
        volume = await self.manager._client.volumes.get(name)
        await volume.delete()

    async def test_browser_mcp_uses_proxy_and_installed_binary(self) -> None:
        client = await self.alice.add_mcp(
            MCPClient(
                name="browser-check",
                mcp_config=StdioMCPConfig(
                    command="playwright-mcp",
                    args=[
                        "--headless",
                        "--browser",
                        "chromium",
                        "--no-sandbox",
                        "--proxy-server",
                        "http://egress:3128",
                        "--executable-path",
                        "/usr/local/bin/agentscope-chromium",
                        "--isolated",
                    ],
                ),
                is_stateful=True,
            ),
            agent_id="agent-alice",
            session_id="browser-session",
        )
        navigate = await client.get_tool("browser_navigate")
        result = await navigate(url="https://example.com")
        rendered = json.dumps(result.model_dump(mode="json"))
        self.assertIn("Example Domain", rendered)
        self.assertNotIn("isError", rendered)
