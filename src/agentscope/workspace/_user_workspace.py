# -*- coding: utf-8 -*-
"""An Agent workspace inside its account's container."""

from typing import Any

from ._sandboxed_base import SandboxedWorkspaceBase
from ._docker._docker_backend import DockerBackend
from ._gateway_client import GatewayClient


class UserWorkspace(SandboxedWorkspaceBase):
    """Agent state is separate; files and gateway belong to one account."""

    _gateway_home = "/opt/runner"

    def __init__(
        self, container: Any, workspace_id: str, workdir: str, **kwargs: Any
    ) -> None:
        super().__init__(workspace_id=workspace_id, **kwargs)
        self.workdir = workdir
        self.gateway_port = 5600
        self._backend = DockerBackend(container, workdir)

    @property
    def file_root(self) -> str:
        return "/workspace"

    async def _provision_backend(self) -> None:
        # The manager owns the account container, not this Agent view.
        pass

    async def _teardown_backend(self) -> None:
        pass

    async def _setup_mcp_gateway(self) -> None:
        self._gateway = GatewayClient(self.get_backend(), self.gateway_port)
        if not await self._gateway.health():
            raise RuntimeError("The account tool gateway is not ready.")

    async def close(self) -> None:
        """Release this view's MCPs while the account runtime stays alive."""
        await self._close_all_mcp_instances()
        await super().close()

    async def get_instructions(self) -> str:
        return (
            f"Your working directory is {self.workdir}. "
            "Your personal files are under /workspace. "
            "Tools run in your account container. "
            "Internet HTTP access uses the configured proxy."
        )
