# -*- coding: utf-8 -*-
"""Docker container :class:`BackendBase` implementation.

Wraps the ``aiodocker`` exec API into the backend primitives (``exec_shell``,
``read_file``, ``write_file``) so that builtin tools (Bash, Read,
Write, Edit, Grep, Glob) can operate inside a Docker container
transparently.  All derived filesystem helpers (``file_exists``,
``is_dir``, ``list_dir``, ``stat_mtime``, ``delete_path``) are
inherited from :class:`BackendBase`, which implements them via
``exec_shell``.
"""

from __future__ import annotations

import asyncio
import json
import struct
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from ...tool import BackendBase, ExecResult
from ...tool._builtin._backend import OpenedFile, _SAFE_READ_SHIM


class DockerBackend(BackendBase):
    """Backend that delegates to a running Docker container.

    Only the three abstract primitives (``exec_shell``, ``read_file``,
    ``write_file``) are implemented here; the derived filesystem helpers
    are inherited from :class:`BackendBase`.

    Args:
        container (`Any`):
            An ``aiodocker`` container object (must already be started).
        workdir (`str`):
            Default working directory for ``exec_shell`` calls inside
            the container.
    """

    def __init__(self, container: Any, workdir: str) -> None:
        """Initialize the Docker backend.

        Args:
            container (`Any`):
                A started ``aiodocker`` container object.
            workdir (`str`):
                Default working directory for ``exec_shell`` calls
                inside the container.
        """
        self._container = container
        self._workdir = workdir

    @asynccontextmanager
    async def open_read(
        self, path: str, *, root: str
    ) -> AsyncIterator[OpenedFile]:
        execution = await self._container.exec(
            cmd=["python3", "-c", _SAFE_READ_SHIM, root, path]
        )
        async with execution.start() as transport:
            buffer = b""
            while b"\n" not in buffer:
                message = await transport.read_out()
                if message is None:
                    raise OSError(
                        "File reader stopped before opening the file."
                    )
                if message.stream == 1:
                    buffer += message.data
            header, buffer = buffer.split(b"\n", 1)
            metadata = json.loads(header)
            if metadata.get("error") == 404:
                raise FileNotFoundError(path)
            if metadata.get("error"):
                raise PermissionError(
                    "File is outside the personal space or is a link."
                )

            async def content() -> AsyncIterator[bytes]:
                if buffer:
                    yield buffer
                while message := await transport.read_out():
                    if message.stream == 1:
                        yield message.data

            yield OpenedFile(metadata["size"], content())

    # ── exec ───────────────────────────────────────────────────────

    async def getcwd(self) -> str:
        """Return the container's default working directory.

        Overrides the base class default (which would shell out to
        ``pwd``) with the cached ``workdir`` supplied at construction,
        avoiding a per-call container ``exec`` round-trip.

        Returns:
            `str`:
                The container's default working directory.
        """
        return self._workdir

    async def exec_shell(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
        """Run a program directly inside the container.

        *command* is an argv list executed via the container ``exec``
        API without an intervening shell. Callers needing shell features
        wrap their command line as ``["sh", "-c", line]``.

        Args:
            command (`list[str]`):
                Executable path/name followed by its arguments.
            cwd (`str | None`, optional):
                Working directory inside the container. When ``None``
                the backend's default ``workdir`` is used.
            timeout (`float | None`, optional):
                Maximum number of seconds to wait before returning an
                ``exit_code`` of ``-1``. When ``None`` the call waits
                indefinitely.

        Returns:
            `ExecResult`:
                The captured exit code, stdout, and stderr.
        """

        async def _run() -> ExecResult:
            exec_obj = await self._container.exec(
                cmd=command,
                workdir=cwd or self._workdir,
            )
            stdout_parts: list[bytes] = []
            stderr_parts: list[bytes] = []
            async with exec_obj.start() as stream:
                while True:
                    msg = await stream.read_out()
                    if msg is None:
                        break
                    if msg.stream == 1:
                        stdout_parts.append(msg.data)
                    else:
                        stderr_parts.append(msg.data)
            inspect = await exec_obj.inspect()
            code = inspect.get("ExitCode", -1)
            if code is None:
                code = -1
            return ExecResult(
                exit_code=int(code),
                stdout=b"".join(stdout_parts),
                stderr=b"".join(stderr_parts),
            )

        if timeout is None:
            return await _run()
        try:
            return await asyncio.wait_for(_run(), timeout=timeout)
        except asyncio.TimeoutError:
            return ExecResult(
                exit_code=-1,
                stdout=b"",
                stderr=b"timed out",
            )

    # ── file I/O ───────────────────────────────────────────────────

    async def read_file(self, path: str) -> bytes:
        """Read as the sandbox user, never through the daemon archive API."""
        result = await self.exec_shell(
            [
                "python3",
                "-c",
                "import sys; "
                "sys.stdout.buffer.write(open(sys.argv[1],'rb').read())",
                path,
            ]
        )
        if not result.ok():
            raise FileNotFoundError(path)
        return result.stdout

    async def write_file(self, path: str, data: bytes) -> None:
        async def content() -> AsyncIterator[bytes]:
            yield data

        await self.write_stream(path, content())

    async def write_stream(
        self, path: str, stream: AsyncIterator[bytes]
    ) -> None:
        """Frame streamed input to a process running with the sandbox UID."""
        script = """
import os,sys,struct
path=sys.argv[1]
os.makedirs(os.path.dirname(path),exist_ok=True)
with open(path,'wb') as f:
 while True:
  header=sys.stdin.buffer.read(8)
  if len(header)!=8: raise EOFError('Incomplete upload')
  size=struct.unpack('!Q',header)[0]
  if size==0: break
  while size:
   data=sys.stdin.buffer.read(min(size,1048576))
   if not data: raise EOFError('Incomplete upload')
   f.write(data);size-=len(data)
"""
        execution = await self._container.exec(
            cmd=["python3", "-c", script, path], stdin=True
        )
        async with execution.start() as transport:
            async for chunk in stream:
                if chunk:
                    await transport.write_in(
                        struct.pack("!Q", len(chunk)) + chunk
                    )
            await transport.write_in(struct.pack("!Q", 0))
            errors = []
            while message := await transport.read_out():
                if message.stream == 2:
                    errors.append(message.data)
        info = await execution.inspect()
        if info.get("ExitCode") != 0:
            raise OSError(b"".join(errors).decode(errors="replace"))
