# -*- coding: utf-8 -*-
"""One container and filesystem volume per authenticated account."""

import asyncio
import hashlib
import re
from typing import Any, Self

from ..._logging import logger
from ..._utils._common import _generate_id
from ...workspace._user_workspace import UserWorkspace
from ...workspace._docker._docker_backend import DockerBackend
from ...workspace._gateway_client import GatewayClient
from ._base import WorkspaceManagerBase, IsolationPolicy


class UserWorkspaceManager(WorkspaceManagerBase):
    """The service's tool boundary. There is no local-execution fallback."""

    def __init__(
        self,
        *,
        image: str,
        prefix: str,
        egress_container: str,
        default_mcps: list | None = None,
    ) -> None:
        super().__init__(isolation=IsolationPolicy.PER_AGENT)
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", prefix):
            raise ValueError("Invalid sandbox prefix.")
        self._image, self._prefix, self._egress = (
            image,
            prefix,
            egress_container,
        )
        self._default_mcps = default_mcps or []
        self._client: Any = None
        self._runtimes: dict[str, Any] = {}
        self._workspaces: dict[str, UserWorkspace] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def _component(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid workspace identity.")
        return value

    async def assign_workspace_id(
        self, *, user_id: str, agent_id: str, session_id: str
    ) -> str:
        return f"{self._component(user_id)}/agents/{self._component(agent_id)}"

    async def new_workspace_id(self, *, user_id: str) -> str:
        return f"{self._component(user_id)}/sessions/{_generate_id()}"

    def _name(self, user_id: str) -> str:
        return (
            self._prefix
            + "-user-"
            + hashlib.sha256(user_id.encode()).hexdigest()[:24]
        )

    async def __aenter__(self) -> Self:
        import aiodocker

        self._client = aiodocker.Docker()
        await self._client.version()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close_all()
        if self._client:
            await self._client.close()
            self._client = None

    async def _start_user(self, user_id: str) -> Any:
        name = self._name(user_id)
        labels = {
            "agentscope.user": user_id,
            "agentscope.deployment": self._prefix,
        }
        # A private internal network has no route to the app, host or internet.
        # Only the shared, filtering HTTP proxy is attached to this network.
        networks = await self._client.networks.list(filters={"name": [name]})
        network = next((n for n in networks if n["Name"] == name), None)
        if network is None:
            options = {
                "com.docker.network.bridge.gateway_mode_ipv4": "isolated",
            }
            network = await self._client.networks.create(
                {
                    "Name": name,
                    "Driver": "bridge",
                    "Internal": True,
                    "Labels": labels,
                    "Options": options,
                }
            )
        account_network = await self._client.networks.get(name)
        config = {
            "Image": self._image,
            "User": "1000:1000",
            "WorkingDir": "/workspace",
            "Labels": labels,
            "Env": [
                "HOME=/workspace/.home",
                "HTTP_PROXY=http://egress:3128",
                "HTTPS_PROXY=http://egress:3128",
                "http_proxy=http://egress:3128",
                "https_proxy=http://egress:3128",
                "NO_PROXY=127.0.0.1,localhost",
                "PYTHONDONTWRITEBYTECODE=1",
            ],
            "HostConfig": {
                "NetworkMode": name,
                "ReadonlyRootfs": True,
                "CapDrop": ["ALL"],
                "SecurityOpt": ["no-new-privileges:true"],
                "PidsLimit": 256,
                "Memory": 1073741824,
                "NanoCpus": 2000000000,
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,size=268435456,mode=1777"},
                "Mounts": [
                    {"Type": "volume", "Source": name, "Target": "/workspace"}
                ],
            },
        }
        container = None
        try:
            details = await account_network.show()
            if not any(
                value.get("Name") == self._egress
                for value in details.get("Containers", {}).values()
            ):
                await account_network.connect(
                    {
                        "Container": self._egress,
                        "EndpointConfig": {"Aliases": ["egress"]},
                    }
                )
            await self._client.volumes.create({"Name": name, "Labels": labels})
            container = await self._client.containers.create_or_replace(
                name=name, config=config
            )
            await container.start()
            backend = DockerBackend(container, "/workspace")
            gateway = GatewayClient(backend, 5600)
            try:
                for _ in range(100):
                    if await gateway.health():
                        return container
                    await asyncio.sleep(0.1)
                try:
                    async with asyncio.timeout(2):
                        state = (await container.show()).get("State", {})
                except Exception as exc:
                    logger.warning(
                        "Could not inspect unready tool container %r (%s).",
                        name,
                        type(exc).__name__,
                    )
                else:
                    logger.error(
                        "Tool container %r did not become ready: "
                        "state=%r exit_code=%r oom_killed=%r",
                        name,
                        state.get("Status"),
                        state.get("ExitCode"),
                        state.get("OOMKilled"),
                    )
                raise RuntimeError("Account tool container failed to start.")
            finally:
                await gateway.aclose()
        except BaseException:
            try:
                await self._stop_user(user_id, container)
            except Exception:
                logger.exception("Failed to clean up tool container %r.", name)
            raise

    async def _stop_user(self, user_id: str, container: Any) -> None:
        """Remove runtime resources and retain the account's data volume."""
        if container is not None:
            await container.delete(force=True)
        network = await self._client.networks.get(self._name(user_id))
        details = await network.show()
        if any(
            value.get("Name") == self._egress
            for value in details.get("Containers", {}).values()
        ):
            await network.disconnect(
                {"Container": self._egress, "Force": True}
            )
        await network.delete()

    async def get_workspace(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str | None = None,
    ) -> UserWorkspace:
        workspace_id = workspace_id or await self.assign_workspace_id(
            user_id=user_id, agent_id=agent_id, session_id=session_id
        )
        parts = workspace_id.split("/")
        if (
            len(parts) != 3
            or parts[0] != user_id
            or parts[1] not in {"agents", "sessions"}
        ):
            raise PermissionError("Workspace does not belong to this account.")
        for part in parts:
            self._component(part)
        async with self._lock:
            if workspace_id in self._workspaces:
                return self._workspaces[workspace_id]
            if user_id not in self._runtimes:
                self._runtimes[user_id] = await self._start_user(user_id)
            container = self._runtimes[user_id]
            backend = DockerBackend(container, "/workspace")
            await backend.exec_shell(
                ["mkdir", "-p", "/workspace/shared", "/workspace/.home"]
            )
            workspace = UserWorkspace(
                container,
                workspace_id,
                "/workspace/" + "/".join(parts[1:]),
                default_mcps=self._default_mcps,
            )
            await workspace.initialize()
            self._workspaces[workspace_id] = workspace
            return workspace

    async def close(self, workspace_id: str) -> None:
        async with self._lock:
            workspace = self._workspaces.pop(workspace_id, None)
            if workspace:
                await workspace.close()

    async def close_all(self) -> None:
        for workspace in list(self._workspaces.values()):
            await workspace.close()
        self._workspaces.clear()
        for user_id, container in list(self._runtimes.items()):
            await self._stop_user(user_id, container)
        self._runtimes.clear()
