# -*- coding: utf-8 -*-
"""The local workspace manager."""

import asyncio
import os
import re
import time

from ..._logging import logger
from ..._utils._common import _generate_id
from ...workspace import LocalWorkspace
from ._base import WorkspaceManagerBase, IsolationPolicy


class LocalWorkspaceManager(WorkspaceManagerBase):
    """Account-owned local workspaces, cached by their qualified identity.

    IDs name paths below basedir: user/agents/agent, user/sessions/id,
    or user/shared. Team members may reuse an owner's workspace identity.
    """

    def __init__(
        self,
        basedir: str,
        *,
        isolation: IsolationPolicy = IsolationPolicy.PER_AGENT,
        default_mcps: list | None = None,
        skill_paths: list[str] | None = None,
        ttl: float = 3600.0,
    ) -> None:
        """Initialize the local workspace manager.

        Args:
            basedir (`str`):
                Root directory under which per-agent workdir are
                created.
            isolation (`IsolationPolicy`, defaults to `PER_AGENT`):
                Isolation grain for :meth:`assign_workspace_id`. See
                :class:`DockerWorkspaceManager` for semantics.
            default_mcps (`list | None`, optional):
                MCP clients seeded into brand-new workspaces.
            skill_paths (`list[str] | None`, optional):
                Skill directories seeded into brand-new workspaces.
            ttl (`float`, defaults to `3600.0`):
                Seconds before an idle cached workspace is evicted.
        """
        self._basedir = os.path.abspath(basedir)
        self._default_mcps = default_mcps or []
        self._skill_paths = skill_paths or []
        self._ttl = ttl
        # workspace_id → (workspace, last_access_monotonic)
        self._cache: dict[str, tuple[LocalWorkspace, float]] = {}
        self._lock = asyncio.Lock()
        super().__init__(isolation=isolation)

    def _pop_expired(self, now: float) -> list[LocalWorkspace]:
        """Pop every cache entry whose last-access exceeds ``ttl``.

        Caller is responsible for closing the returned workspaces
        *outside* the manager lock so a slow ``close()`` does not stall
        unrelated ``get_workspace`` callers.
        """
        expired_ids = [
            wid for wid, (_, ts) in self._cache.items() if now - ts > self._ttl
        ]
        return [self._cache.pop(wid)[0] for wid in expired_ids]

    @staticmethod
    def _validate_component(value: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
            raise ValueError("Invalid workspace identity.")

    def user_root(self, user_id: str) -> str:
        """Return an account's root without following an external symlink."""
        self._validate_component(user_id)
        root = os.path.join(self._basedir, user_id)
        if os.path.realpath(root) != os.path.join(
            os.path.realpath(self._basedir), user_id
        ):
            raise PermissionError("Personal space cannot be a symbolic link.")
        return root

    async def assign_workspace_id(
        self,
        *,
        user_id: str,
        agent_id: str,
        session_id: str,
    ) -> str:
        """Issue an identity whose owner remains verifiable after eviction."""
        self._validate_component(user_id)
        self._validate_component(agent_id)
        if self._isolation is IsolationPolicy.PER_USER:
            return f"{user_id}/shared"
        if self._isolation is IsolationPolicy.PER_SESSION:
            return await self.new_workspace_id(user_id=user_id)
        return f"{user_id}/agents/{agent_id}"

    async def new_workspace_id(self, *, user_id: str) -> str:
        """Issue a fresh, account-owned workspace for a session or SOP run."""
        self._validate_component(user_id)
        return f"{user_id}/sessions/{_generate_id()}"

    async def get_workspace(
        self,
        user_id: str,
        agent_id: str,
        session_id: str,
        workspace_id: str | None = None,
    ) -> LocalWorkspace:
        """Return an initialized workspace, reconstructing from
        disk on cache miss.

        Mirrors the Docker / E2B managers' double-check pattern: a
        first lock acquisition handles the cache-hit fast path and
        collects expired entries; expired entries are then closed in
        parallel *outside* the lock; on a miss a second acquisition
        runs ``initialize()`` while holding the lock so two concurrent
        cache misses for the same ``workspace_id`` cannot create two
        workspaces.
        """
        if not workspace_id:
            workspace_id = await self.assign_workspace_id(
                user_id=user_id,
                agent_id=agent_id,
                session_id=session_id,
            )

        parts = workspace_id.split("/")
        for part in parts:
            self._validate_component(part)
        if parts[0] != user_id:
            raise PermissionError("Workspace does not belong to this account.")
        if not (
            (len(parts) == 3 and parts[1] in {"agents", "sessions"})
            or (len(parts) == 2 and parts[1] == "shared")
        ):
            raise ValueError("Invalid workspace identity.")
        root = self.user_root(user_id)
        workdir = os.path.join(self._basedir, *parts)
        if os.path.realpath(workdir) != os.path.join(
            os.path.realpath(self._basedir), *parts
        ):
            raise PermissionError("Workspace cannot be a symbolic link.")

        # Phase 1: cache hit + collect expired.
        async with self._lock:
            now = time.monotonic()
            expired = self._pop_expired(now)
            cached = self._cache.get(workspace_id)
            if cached is not None:
                ws, _ = cached
                self._cache[workspace_id] = (ws, now)
                hit: LocalWorkspace | None = ws
            else:
                hit = None

        # Phase 2: close expired entries outside the lock, in parallel,
        # so a slow stdio MCP shutdown does not block unrelated callers.
        if expired:
            await asyncio.gather(
                *(self._safe_close(ws) for ws in expired),
                return_exceptions=True,
            )

        if hit is not None:
            return hit

        # Phase 3: build under the lock to prevent two concurrent
        # get_workspace(workspace_id=X) calls from creating two
        # workspaces for the same id.
        async with self._lock:
            cached = self._cache.get(workspace_id)
            if cached is not None:
                ws, _ = cached
                self._cache[workspace_id] = (ws, time.monotonic())
                return ws

            os.makedirs(os.path.join(root, "shared"), exist_ok=True)
            ws = LocalWorkspace(
                workspace_id=workspace_id,
                workdir=workdir,
                file_root=root,
                default_mcps=self._default_mcps,
                skill_paths=self._skill_paths,
            )
            await ws.initialize()
            self._cache[workspace_id] = (ws, time.monotonic())
            return ws

    async def close(self, workspace_id: str) -> None:
        """Close and evict a single workspace from the cache."""
        async with self._lock:
            entry = self._cache.pop(workspace_id, None)
        if entry is None:
            return
        ws, _ = entry
        await self._safe_close(ws)

    async def close_all(self) -> None:
        """Close every cached workspace in parallel.

        Stdio MCP shutdown can be slow per workspace; doing it
        sequentially on app shutdown produces a noticeable stall, so
        we fan the calls out with :func:`asyncio.gather` (mirrors the
        Docker / E2B managers).
        """
        async with self._lock:
            entries = list(self._cache.values())
            self._cache.clear()
        if not entries:
            return
        await asyncio.gather(
            *(self._safe_close(ws) for ws, _ in entries),
            return_exceptions=True,
        )

    @staticmethod
    async def _safe_close(ws: LocalWorkspace) -> None:
        """Close a workspace, logging any failure instead of raising."""
        try:
            await ws.close()
        except Exception:
            logger.exception(
                "Failed to close LocalWorkspace %s",
                ws.workspace_id,
            )
