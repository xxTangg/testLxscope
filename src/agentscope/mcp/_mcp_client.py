# -*- coding: utf-8 -*-
"""Unified MCP client implementation for AgentScope."""
import asyncio
import re
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
    AsyncExitStack,
)
from typing import Any, AsyncGenerator, ClassVar, TYPE_CHECKING
from urllib.parse import urlsplit

import anyio
import httpx
import mcp.types
from mcp import ClientSession, stdio_client, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.streamable_http import (
    create_mcp_http_client,
    streamable_http_client,
)
from pydantic import Field, BaseModel, PrivateAttr

from ._config import StdioMCPConfig, HttpMCPConfig
from .._logging import logger

if TYPE_CHECKING:
    from ..tool import MCPTool, ToolBase
else:
    MCPTool = Any
    ToolBase = Any


class MCPClient(BaseModel):
    """The unified MCP client in AgentScope.

    This class provides a unified interface for MCP connections, handling both
    stateful (persistent) and stateless (ephemeral) connections.

    - Stateful: Requires explicit connect() and close(), maintains session
    - Stateless: No connect() needed, creates temporary session per call

    Private attributes:
    - _client: The underlying MCP client context manager
    - _session: The MCP ClientSession (for stateful connections only)
    - _lifecycle_task: Owns the stateful connection's async contexts
    - _is_connected: Connection state flag
    - _cached_tools: Cached list of tools
    - _http_client: The live HTTP client, while one is open
    - _static_headers: Its headers before any runtime override
    - _runtime_headers: See :meth:`set_runtime_headers`

    Example:

    .. code-block:: python

        # Stateful connection (STDIO or HTTP)
        client = MCPClient(
            name="file_system",
            is_stateful=True,
            mcp_config=StdioMCPConfig(
                command="mcp-server-filesystem"
            )
        )
        await client.connect()
        tools = await client.list_tools()
        await client.close()

        # Stateless connection (HTTP only)
        client = MCPClient(
            name="weather_search",
            is_stateful=False,
            mcp_config=HttpMCPConfig(
                url="https://api.weather.com/mcp"
            )
        )
        # No connect() needed
        tools = await client.list_tools()

    """

    # httpx derives these from the request URL and body with setdefault,
    # so a client-level value silently wins and breaks routing or framing.
    # The headers MCP itself sends are set per request and need no guard.
    _RESERVED_HEADERS: ClassVar[frozenset[str]] = frozenset(
        {"connection", "content-length", "host", "transfer-encoding"},
    )
    # RFC 7230 token, and a field value of visible ASCII plus tab.
    _HEADER_NAME: ClassVar[re.Pattern[str]] = re.compile(
        r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+",
    )
    _HEADER_VALUE: ClassVar[re.Pattern[str]] = re.compile(r"[\t\x20-\x7e]*")

    name: str = Field(
        title="MCP Name",
        description="The MCP name.",
    )

    is_stateful: bool = Field(
        title="Stateful",
        description=(
            "Whether this is a stateful connection that requires explicit "
            "connect() and close(). STDIO MCP must be stateful. HTTP MCP "
            "can be either stateful or stateless."
        ),
    )

    mcp_config: StdioMCPConfig | HttpMCPConfig = Field(
        discriminator="type",
        title="MCP Config",
        description="The MCP server configuration.",
    )

    enable_tools: list[str] | None = None
    """The tools enabled in this MCP, which will be returned in the
    `list_tools` function. If `None`, all tools from the MCP server will be
    returned."""

    disable_tools: list[str] | None = None
    """The tools disabled in this MCP, which will be filtered out in the
    `list_tools` function."""

    execution_timeout: float | None = None
    """The execution timeout in seconds for calling the tools from this MCP."""

    # Private attributes
    _client: Any = PrivateAttr(default=None)
    _session: ClientSession | None = PrivateAttr(default=None)
    _lifecycle_task: asyncio.Task[None] | None = PrivateAttr(default=None)
    _close_requested: asyncio.Event | None = PrivateAttr(default=None)
    _is_connected: bool = PrivateAttr(default=False)
    _cached_tools: list[mcp.types.Tool] | None = PrivateAttr(default=None)
    _tool_list_generation: int = PrivateAttr(default=0)
    _discovery_task: asyncio.Task[list[mcp.types.Tool]] | None = PrivateAttr(
        default=None,
    )
    _discovery_waiters: int = PrivateAttr(default=0)
    _http_client: httpx.AsyncClient | None = PrivateAttr(default=None)
    _static_headers: httpx.Headers | None = PrivateAttr(default=None)
    _runtime_headers: dict[str, str] = PrivateAttr(default_factory=dict)

    @property
    def is_connected(self) -> bool:
        """Whether the client is currently connected.

        Returns:
            True if connected, False otherwise.
        """
        return self._is_connected

    def model_post_init(self, __context: Any) -> None:
        """Validate configuration and initialize client."""
        # MCP name is used to compose model-facing tool names
        # (mcp__{name}__{tool}), which must match ^[a-zA-Z0-9_-]+$.
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", self.name):
            raise ValueError(
                f"MCPClient name '{self.name}' contains characters not "
                f"allowed by LLM providers (only [a-zA-Z0-9_-] are "
                f"permitted). Please rename it.",
            )

        # STDIO MCP must be stateful
        if self.mcp_config.type == "stdio_mcp" and not self.is_stateful:
            raise ValueError(
                "STDIO MCP must be stateful (is_stateful=True).",
            )

        # Check arguments for self.enable_tools and disable_tools
        if self.enable_tools is not None:
            if not isinstance(self.enable_tools, list) or any(
                not isinstance(_, str) for _ in self.enable_tools
            ):
                raise ValueError(
                    "Enable tools should be a list of strings, but got "
                    f"{self.enable_tools}.",
                )

        if self.disable_tools is not None:
            if not isinstance(self.disable_tools, list) or any(
                not isinstance(_, str) for _ in self.disable_tools
            ):
                raise ValueError(
                    "Disable tools should be a list of strings, but got "
                    f"{self.disable_tools}.",
                )

        if self.enable_tools is not None and self.disable_tools is not None:
            intersection = set(self.enable_tools).intersection(
                set(self.disable_tools),
            )
            if len(intersection) != 0:
                raise ValueError(
                    f"The tools in enable_tools and disable_tools "
                    f"should not overlap, but got {intersection}.",
                )

        # Initialize the underlying client
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Pre-build the stdio client context manager."""
        if self.mcp_config.type == "stdio_mcp":
            config = self.mcp_config
            self._client = stdio_client(
                StdioServerParameters(
                    command=config.command,
                    args=config.args or [],
                    env=config.env,
                    cwd=str(config.cwd) if config.cwd else None,
                    encoding="utf-8",
                    encoding_error_handler=config.encoding_error_handler,
                ),
            )

    def _create_http_client(
        self,
    ) -> AbstractAsyncContextManager[Any]:
        """Create an HTTP MCP client (SSE or streamable HTTP)."""
        config = self.mcp_config
        if self._is_sse:
            return sse_client(
                url=config.url,
                headers=config.headers,
                timeout=config.timeout,
            )

        return self._create_streamable_http_client()

    @property
    def _is_sse(self) -> bool:
        """Whether the configured URL points at the SSE transport. Only
        the path is inspected, so a query string (``/sse?key=...``) still
        resolves to SSE rather than falling through to streamable HTTP.
        """
        path = urlsplit(self.mcp_config.url).path
        return path.endswith("/sse") or path.endswith("/messages/")

    @asynccontextmanager
    async def _create_streamable_http_client(
        self,
    ) -> AsyncGenerator[Any, None]:
        """Create an owned HTTP client that runtime headers can update."""
        config = self.mcp_config
        # Use the SDK factory to keep the transport's own client defaults
        client = create_mcp_http_client(
            headers=config.headers,
            timeout=(
                httpx.Timeout(config.timeout)
                if config.timeout is not None
                else None
            ),
        )
        # Snapshot before overlaying: clearing runtime headers restores it.
        self._static_headers = httpx.Headers(client.headers)
        client.headers.update(self._runtime_headers)
        self._http_client = client

        try:
            async with client:
                async with streamable_http_client(
                    url=config.url,
                    http_client=client,
                ) as transport:
                    yield transport
        finally:
            if self._http_client is client:
                self._http_client = None

    async def set_runtime_headers(
        self,
        headers: dict[str, str],
    ) -> None:
        """Replace the headers sent with subsequent HTTP requests.

        The map is replaced rather than merged: an empty map drops all
        runtime overrides, so the static headers from :attr:`mcp_config`
        apply again. Runtime headers are live instance state, excluded
        from ``model_dump`` and workspace persistence.

        The update reaches the next outbound request without reconnecting.
        Two things it cannot reach: a call already under way, which keeps
        the snapshot it started with, and the long-lived GET stream of a
        Streamable HTTP session, whose headers are fixed when the stream
        is established. Headers MCP sends itself (``mcp-session-id``,
        ``content-type``, ...) are set per request and always win over
        the ones set here; the few httpx derives from the URL and body
        are rejected outright.

        Args:
            headers (`dict[str, str]`):
                The complete runtime header map. An empty dict clears it.

        Raises:
            `ValueError`:
                The client is not Streamable HTTP, or a header is
                invalid or owned by the HTTP layer.
        """
        if self.mcp_config.type != "http_mcp" or self._is_sse:
            raise ValueError(
                "Runtime headers require a Streamable HTTP MCP client.",
            )
        if not isinstance(headers, dict):
            raise ValueError("Runtime headers must be a dict.")

        # httpx accepts illegal names and CRLF in values, and only h11
        # rejects them mid-request, so validate before storing.
        for name, value in headers.items():
            if (
                not isinstance(name, str)
                or not isinstance(value, str)
                or not self._HEADER_NAME.fullmatch(name)
                or not self._HEADER_VALUE.fullmatch(value)
            ):
                raise ValueError(f"Runtime header {name!r} is invalid.")
            if name.lower() in self._RESERVED_HEADERS:
                raise ValueError(
                    f"Runtime header {name!r} is owned by the HTTP layer.",
                )

        self._runtime_headers = dict(headers)
        if self._http_client is not None:
            merged = httpx.Headers(self._static_headers)
            merged.update(self._runtime_headers)
            self._http_client.headers = merged

    async def connect(self) -> None:
        """Connect to the MCP server (for stateful connections only).

        For stateless connections, this method does nothing.

        Raises:
            RuntimeError: If already connected or a connection is in progress.
        """
        if not self.is_stateful:
            logger.debug(
                "Stateless MCP '%s' does not require explicit connect.",
                self.name,
            )
            return

        if self._is_connected:
            raise RuntimeError(
                f"MCP '{self.name}' is already connected. "
                "Call close() before reconnecting.",
            )
        if self._lifecycle_task is not None:
            if not self._lifecycle_task.done():
                raise RuntimeError(
                    f"MCP '{self.name}' connection is already in progress.",
                )
            if not self._lifecycle_task.cancelled():
                self._lifecycle_task.exception()

        ready: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        close_requested = asyncio.Event()
        self._close_requested = close_requested
        task = asyncio.create_task(
            self._run_connection(ready, close_requested),
            name=f"mcp:{self.name}",
        )
        self._lifecycle_task = task
        try:
            await asyncio.shield(ready)
        except BaseException:
            if not ready.done():
                ready.cancel()
            if not task.done():
                task.cancel()
            with anyio.CancelScope(shield=True):
                await asyncio.gather(task, return_exceptions=True)
            self._lifecycle_task = None
            self._close_requested = None
            if not ready.cancelled():
                ready.exception()
            raise

    def _create_session(self, context: Any) -> ClientSession:
        """Create an SDK 1.x session with tool-list notifications enabled."""
        return ClientSession(
            context[0],
            context[1],
            message_handler=self._handle_server_message,
        )

    async def _handle_server_message(self, message: Any) -> None:
        """Invalidate cached tool descriptors when the server changes them."""
        if isinstance(message, mcp.types.ServerNotification):
            message = message.root
        if isinstance(message, mcp.types.ToolListChangedNotification):
            self._tool_list_generation += 1
            self._cached_tools = None

    async def _run_connection(
        self,
        ready: asyncio.Future[None],
        close_requested: asyncio.Event,
    ) -> None:
        """Enter and exit the SDK contexts on the same task."""
        try:
            if self._client is None:
                if self.mcp_config.type == "http_mcp":
                    self._client = self._create_http_client()
                else:
                    self._initialize_client()
            assert self._client is not None
            async with AsyncExitStack() as stack:
                context = await stack.enter_async_context(self._client)
                self._session = await stack.enter_async_context(
                    self._create_session(context),
                )
                await self._session.initialize()
                if not ready.done():
                    self._is_connected = True
                    logger.info("MCP connected: %s", self.name)
                    ready.set_result(None)
                    await close_requested.wait()
        except BaseException as exc:
            if not ready.done():
                ready.set_exception(exc)
            else:
                raise
        finally:
            self._client = None
            self._session = None
            self._is_connected = False
            self._tool_list_generation += 1
            self._cached_tools = None

    async def close(self, ignore_errors: bool = True) -> None:
        """Close the MCP connection (for stateful connections only).

        For stateless connections, this method does nothing.

        Args:
            ignore_errors: Whether to ignore errors during cleanup.

        Raises:
            RuntimeError: If not connected.
        """
        if not self.is_stateful:
            logger.debug(
                "Stateless MCP '%s' does not require explicit close.",
                self.name,
            )
            return

        if not self._is_connected:
            raise RuntimeError(
                f"MCP '{self.name}' is not connected. "
                "Call connect() first.",
            )

        task = self._lifecycle_task
        assert task is not None and self._close_requested is not None
        self._close_requested.set()
        try:
            await asyncio.shield(task)
        except Exception as exc:
            if not ignore_errors:
                raise
            logger.warning("Error closing MCP '%s': %s", self.name, exc)
        finally:
            if task.done() and self._lifecycle_task is task:
                self._lifecycle_task = None
                self._close_requested = None
        logger.info("MCP closed: %s", self.name)

    def _get_client_gen(self) -> AbstractAsyncContextManager[Any]:
        """Get client generator for stateless connections."""
        if self.mcp_config.type == "stdio_mcp":
            return self._client
        else:
            return self._create_http_client()

    async def list_raw_tools(self) -> list[mcp.types.Tool]:
        """List available tools from the MCP server in raw
        :class:`mcp.types.Tool` form, applying ``enable_tools`` and
        ``disable_tools`` filtering.

        The full (unfiltered) tool list is cached on ``_cached_tools`` so
        :meth:`get_tool` can resolve names that were filtered out as well.

        Returns:
            `list[mcp.types.Tool]`:
                Raw MCP tool descriptors after filtering.

        Raises:
            RuntimeError: If not connected (for stateful connections).
        """
        available_tools = await self._discover_tools()
        if self.enable_tools is not None:
            available_tools = [
                tool
                for tool in available_tools
                if tool.name in self.enable_tools
            ]
        if self.disable_tools is not None:
            available_tools = [
                _ for _ in available_tools if _.name not in self.disable_tools
            ]
        return available_tools

    async def _discover_tools(self) -> list[mcp.types.Tool]:
        """Share stateless discovery without sharing caller cancellation."""
        if self.is_stateful:
            return await self._fetch_tools()

        task = self._discovery_task
        if task is None or task.done():
            task = asyncio.create_task(self._fetch_tools())
            self._discovery_task = task
            self._discovery_waiters = 0
        self._discovery_waiters += 1
        try:
            return await asyncio.shield(task)
        finally:
            if self._discovery_task is task:
                self._discovery_waiters -= 1
                if self._discovery_waiters == 0:
                    self._discovery_task = None
                    if not task.done():
                        task.cancel()
                        await asyncio.gather(task, return_exceptions=True)
                    elif not task.cancelled():
                        task.exception()

    async def _fetch_tools(self) -> list[mcp.types.Tool]:
        """Retry once if a notification invalidates an in-flight listing."""
        for _ in range(2):
            if self.is_stateful:
                self._validate_connection()
                generation = self._tool_list_generation
                result = await self._session.list_tools()
            else:
                async with self._get_client_gen() as context:
                    async with self._create_session(context) as session:
                        await session.initialize()
                        generation = self._tool_list_generation
                        result = await session.list_tools()
            if generation == self._tool_list_generation:
                self._cached_tools = result.tools
                return result.tools
        raise RuntimeError(
            f"MCP '{self.name}' tool list changed during discovery; "
            "retry the lookup.",
        )

    async def list_tools(self) -> list[ToolBase]:
        """List available tools from the MCP server as wrapped
        :class:`ToolBase` instances. If `enable_tools` and `disable_tools`
        are not `None` in the constructor, the returned tools will be
        filtered accordingly.

        Returns:
            `list[ToolBase]`:
                List of available MCP tools.

        Raises:
            RuntimeError: If not connected (for stateful connections).
        """
        raw_tools = await self.list_raw_tools()
        return [await self.get_tool(_.name) for _ in raw_tools]

    async def get_tool(
        self,
        name: str,
    ) -> MCPTool:
        """Get a tool by name from the MCP server.

        The returned MCPTool object implements ToolProtocol and can be:
        - Called directly: `await tool(arg1=val1)`
        - Registered to toolkit: `toolkit.register_tool(tool)`

        Args:
            name: The name of the tool function to get.

        Returns:
            A tool object that implements ToolProtocol.

        Raises:
            ValueError: If the tool is not found.
            RuntimeError: If not connected (for stateful connections).
        """
        # Avoid circular import by importing here
        from ..tool import MCPTool

        tools = self._cached_tools
        if tools is None:
            tools = await self._discover_tools()
        target_tool = next((tool for tool in tools if tool.name == name), None)

        if target_tool is None:
            raise ValueError(
                f"Tool '{name}' not found in MCP server " f"'{self.name}'",
            )

        # Create MCPTool based on stateful/stateless
        if not self.is_stateful:
            # Stateless: pass client generator
            return MCPTool(
                mcp_name=self.name,
                tool=target_tool,
                client_gen=self._get_client_gen,
                timeout=self.execution_timeout,
            )
        else:
            # Stateful: pass session
            self._validate_connection()
            return MCPTool(
                mcp_name=self.name,
                tool=target_tool,
                session=self._session,
                timeout=self.execution_timeout,
            )

    def _validate_connection(self) -> None:
        """Validate connection state for stateful connections.

        Raises:
            RuntimeError: If not connected or session not initialized.
        """
        if not self._is_connected:
            raise RuntimeError(
                f"MCP '{self.name}' is not connected. "
                "Call connect() first.",
            )
        if not self._session:
            raise RuntimeError(
                f"MCP '{self.name}' session is not initialized. "
                "Call connect() first.",
            )
