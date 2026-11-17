# -*- coding: utf-8 -*-
"""Check direct model access and the tool proxy's private network policy."""

import asyncio
import os
import socket
import uuid
from unittest import IsolatedAsyncioTestCase, skipUnless
from unittest.mock import patch

import httpx
import uvicorn
from fastapi import FastAPI

from agentscope.app._service._newapi import NewAPIGateway


@skipUnless(
    os.getenv("RUN_USER_SANDBOX_TESTS") == "1",
    "Requires isolated Docker test services",
)
class EgressPolicyIntegrationTests(IsolatedAsyncioTestCase):
    async def test_backend_reaches_private_gateway_and_tool_proxy_denies_it(
        self,
    ) -> None:
        import aiodocker

        app = FastAPI()

        @app.get("/v1/models")
        async def models() -> dict:
            return {"data": [{"id": "synthetic-private-model"}]}

        listener = socket.socket()
        listener.bind(("0.0.0.0", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        proxy = None
        docker = aiodocker.Docker()
        try:
            while not server.started:
                await asyncio.sleep(0.01)
            host = os.environ["TEST_GATEWAY_HOST"]
            proxy = await docker.containers.create(
                name="isolation-policy-" + uuid.uuid4().hex[:10],
                config={
                    "Image": "testlxscope-egress:latest",
                    "HostConfig": {
                        "NetworkMode": os.environ["TEST_CONTROL_NETWORK"],
                        "Ulimits": [
                            {"Name": "nofile", "Soft": 8192, "Hard": 8192},
                        ],
                    },
                },
            )
            await proxy.start()
            info = await proxy.show()
            address = next(iter(info["NetworkSettings"]["Networks"].values()))[
                "IPAddress"
            ]
            proxy_url = f"http://{address}:3128"
            target = f"http://{host}:{port}/v1"
            async with httpx.AsyncClient(proxy=proxy_url, timeout=5) as client:
                for attempt in range(50):
                    try:
                        response = await client.get(target + "/models")
                        break
                    except httpx.ConnectError:
                        if attempt == 49:
                            raise
                        await asyncio.sleep(0.1)
                self.assertEqual(response.status_code, 403)
                for blocked in (
                    f"http://127.0.0.1:{port}/v1/models",
                    "http://localhost/",
                    "http://169.254.169.254/",
                    "http://[::]/",
                    "http://[::1]/",
                    "http://[::ffff:127.0.0.1]/",
                ):
                    response = await client.get(blocked)
                    self.assertEqual(response.status_code, 403, blocked)
            with patch.dict(
                os.environ,
                HTTP_PROXY=proxy_url,
                http_proxy=proxy_url,
                NO_PROXY="*",
                no_proxy="*",
            ):
                result = await NewAPIGateway(target, "synthetic-key")._request(
                    "models"
                )
                self.assertEqual(result, [{"id": "synthetic-private-model"}])
        finally:
            if proxy is not None:
                await proxy.delete(force=True)
            await docker.close()
            server.should_exit = True
            await serving
            listener.close()
