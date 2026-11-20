# -*- coding: utf-8 -*-
"""Workspace router — manage MCP clients and skills on a workspace."""

import asyncio
import mimetypes
from pathlib import Path
from typing import AsyncIterator

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError
from starlette.background import BackgroundTask

from ..deps import (
    get_current_user_id,
    get_skill_hubs,
    get_storage,
    get_workspace_service,
)
from ..hub import BuiltinSkillHub, SkillHubBase
from .._service import WorkspaceService, WorkspaceStatus
from .._service._file_response import file_headers
from .._service._download_token import DEFAULT_DOWNLOAD_TOKEN_TTL
from .._service._workspace import SkillUploadError, UploadManifest
from .._service._builtin_skills import (
    activate_workspace_builtin_skill,
    get_user_skill,
    list_workspace_skills,
)
from ..storage import MCPRecord, StorageBase
from ...mcp import MCPClient
from ...message import TextBlock
from ...skill import Skill
from ._schema import (
    AddFromLibraryRequest,
    AddFromLibraryResponse,
    AddSkillsFromLibraryRequest,
    DirectoryEntry,
    DirectoryListing,
    DownloadTokenResponse,
    MCPClientStatus,
    ToolInfo,
)
from ..._logging import logger
from ..._utils._common import _describe_exception

workspace_router = APIRouter(prefix="/workspace", tags=["workspace"])
_PREVIEW_TOKEN_TTL = 600


# ---------------------------------------------------------------------------
# MCP endpoints
# ---------------------------------------------------------------------------


@workspace_router.get("/mcp")
async def list_mcps(
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> list[MCPClientStatus]:
    """Return all MCP clients with live tool list and health status."""
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    clients = await workspace.list_mcps(
        agent_id=agent_id,
        session_id=session_id,
    )

    results = []
    for client in clients:
        base = client.model_dump()
        try:
            mcp_tools = await client.list_tools()
            tools = [
                ToolInfo(name=t.name, description=t.description)
                for t in mcp_tools
            ]
            results.append(
                MCPClientStatus(
                    **base,
                    is_healthy=True,
                    tools=tools,
                ),
            )
        except Exception as e:
            results.append(
                MCPClientStatus(
                    **base,
                    is_healthy=False,
                    error=_describe_exception(e),
                ),
            )

    return results


@workspace_router.post("/mcp", status_code=status.HTTP_201_CREATED)
async def add_mcp(
    mcp: MCPClient,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    """Add an MCP client to the session's workspace.

    The MCP is also recorded in the user's library, so one typed in by
    hand is reusable in the next session instead of being retyped. An
    existing record of the same name is left alone: the library is where
    that MCP is defined, and adding it to a second workspace must not
    silently redefine it.
    """
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    try:
        await workspace.add_mcp(mcp, agent_id=agent_id, session_id=session_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e

    if await storage.get_mcp_by_name(user_id, mcp.name) is None:
        # No hub_id or card_id — this one has no card behind it, which
        # is what tells the library it cannot be re-keyed or upgraded.
        await storage.upsert_mcp(
            user_id,
            MCPRecord(user_id=user_id, client=mcp),
        )


@workspace_router.post(
    "/mcp/from-library",
    status_code=status.HTTP_201_CREATED,
)
async def add_mcps_from_library(
    body: AddFromLibraryRequest,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> AddFromLibraryResponse:
    """Put MCPs the user has already installed into this workspace.

    The rendered config never leaves the server, so the client sends ids
    rather than configs — it has no way to reconstruct one.

    Adding is per-MCP: one that fails to connect does not cancel the
    rest, and the response says which ones landed.
    """
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    present = {
        client.name
        for client in await workspace.list_mcps(
            agent_id=agent_id,
            session_id=session_id,
        )
    }

    added: list[str] = []
    failed: dict[str, str] = {}
    for mcp_id in body.mcp_ids:
        record = await storage.get_mcp(user_id, mcp_id)
        if record is None:
            failed[mcp_id] = "Not in your library."
            continue
        if record.client.name in present:
            # Already there: not an error, just nothing to do.
            continue
        try:
            await workspace.add_mcp(
                record.client,
                agent_id=agent_id,
                session_id=session_id,
            )
        except Exception as e:
            failed[record.client.name] = _describe_exception(e)
            continue
        added.append(record.client.name)

    return AddFromLibraryResponse(added=added, failed=failed)


@workspace_router.delete(
    "/mcp/{mcp_name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_mcp(
    mcp_name: str,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    """Remove an MCP client from the session's workspace by name."""
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    await workspace.remove_mcp(
        mcp_name,
        agent_id=agent_id,
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Skill endpoints
# ---------------------------------------------------------------------------


@workspace_router.get("/skill")
async def list_skills(
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> list[Skill]:
    """Return all skills available in the session's workspace."""
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    return await list_workspace_skills(workspace, agent_id)


@workspace_router.post(
    "/skill/upload",
    status_code=status.HTTP_201_CREATED,
)
async def upload_skill(
    manifest: str = Form(
        description=(
            "JSON ``{entries: [{path, size}]}`` describing the parts, "
            "in the order they are sent."
        ),
    ),
    files: list[UploadFile] = File(description="The folder's files."),
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    """Install a skill from an uploaded folder.

    The parts are re-tarred on the fly and piped into the workspace, so
    the archive is never held whole. The manifest is what the client
    claims; every limit in it is re-checked here, and the byte counts
    are verified as the tar is built.
    """
    try:
        parsed = UploadManifest.model_validate_json(manifest)
        workspace_service.validate_manifest(parsed, len(files))
    except (ValidationError, SkillUploadError) as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(e),
        ) from e

    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    try:
        # The name is unused: the tar members already carry the picked
        # folder as their first path segment.
        await workspace_service.install_skill(
            workspace,
            workspace_service.tar_stream(parsed, files),
            "tar",
            "skill",
            agent_id=agent_id,
        )
    except (SkillUploadError, ValueError) as e:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            str(e),
        ) from e


@workspace_router.post(
    "/skill/from-library",
    status_code=status.HTTP_201_CREATED,
)
async def add_skills_from_library(
    body: AddSkillsFromLibraryRequest,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
    skill_hubs: dict[str, SkillHubBase] = Depends(get_skill_hubs),
) -> AddFromLibraryResponse:
    """Put skills the user has already installed into this workspace.

    Reuse an existing bundled copy or download the skill into the workspace.
    Adding is per-skill, and the response says which ones landed.
    """
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )

    added: list[str] = []
    failed: dict[str, str] = {}
    for skill_id in body.skill_ids:
        record = await get_user_skill(storage, skill_hubs, user_id, skill_id)
        if record is None or not record.enabled:
            failed[skill_id] = "Not in your library."
            continue
        hub = skill_hubs.get(record.hub_id or "")
        if hub is None:
            failed[record.name] = (
                f"Its hub {record.hub_id!r} is no longer registered."
            )
            continue
        try:
            if isinstance(hub, BuiltinSkillHub) and (
                await activate_workspace_builtin_skill(
                    workspace, agent_id, record
                )
            ):
                added.append(record.name)
                continue
            archive = await hub.download(
                user_id,
                record.card_id or record.name,
                record.version,
            )
            await workspace_service.install_skill(
                workspace,
                archive.stream,
                archive.format,
                record.name,
                agent_id=agent_id,
            )
        except Exception as e:  # pylint: disable=broad-except
            failed[record.name] = _describe_exception(e)
            continue
        added.append(record.name)

    return AddFromLibraryResponse(added=added, failed=failed)


@workspace_router.delete(
    "/skill/{skill_name}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_skill(
    skill_name: str,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> None:
    """Remove a skill from the session's workspace by name."""
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    try:
        await workspace.remove_skill(skill_name, agent_id=agent_id)
    except KeyError:
        # ``LocalWorkspace`` already treats a missing skill as a no-op.
        # Keep DELETE idempotent for the other workspace implementations.
        return


# ---------------------------------------------------------------------------
# File browsing endpoints
# ---------------------------------------------------------------------------


@workspace_router.get("/directories")
async def list_workspace_directory(
    agent_id: str = Query(...),
    session_id: str = Query(...),
    path: str = Query(
        default="",
        description=(
            "Personal-space path (~), or a path relative to this Agent. "
            "Empty opens the Agent workspace."
        ),
    ),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> DirectoryListing:
    """List a directory inside the authenticated account personal space."""
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    backend = workspace.get_backend()
    target = await workspace_service.resolve_path(workspace, path)

    entry = await backend.stat(target)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Directory not found.",
        )
    if not entry.is_dir:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requested path is a file, not a directory.",
        )

    virtual_path = workspace.virtual_file_path(target)
    labels = (
        await workspace_service.directory_names(user_id)
        if virtual_path == "~/agents"
        else {}
    )
    entries = []
    for child in await backend.scandir(target):
        try:
            await workspace.resolve_file_path(
                backend.join_path(target, child.name)
            )
        except (PermissionError, ValueError):
            continue
        entries.append(
            DirectoryEntry(
                name=child.name,
                display_name=labels.get(child.name, child.name),
                is_dir=child.is_dir,
                size_bytes=child.size_bytes,
                updated_at=child.mtime,
            )
        )
    return DirectoryListing(
        path=virtual_path,
        parent_path=(
            None if virtual_path == "~" else virtual_path.rsplit("/", 1)[0]
        ),
        entries=entries,
    )


@workspace_router.get("/status")
async def get_workspace_status(
    agent_id: str = Query(...),
    session_id: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceStatus:
    """Report where a session is pointed, and the git state of that place.

    The directory comes from the session's own ``cwd`` rather than a
    query parameter: it is the session's anchor, and resolving a
    relative one needs the workspace root the client cannot see.

    Git is best-effort. A directory that is not a repository is the
    normal case, not an error, and the sandboxed backends differ in how
    they report a missing binary or an unreachable container — so every
    failure collapses to ``git: null`` and the rest of the response is
    still served.
    """
    return await workspace_service.read_status(
        user_id,
        agent_id,
        session_id,
    )


@workspace_router.post("/files/download-token")
async def create_download_token(
    agent_id: str = Query(...),
    session_id: str = Query(...),
    path: str = Query(..., description="The path the token will authorize."),
    preview: bool = Query(
        default=False,
        description="Use a longer token lifetime for paged browser previews.",
    ),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> DownloadTokenResponse:
    """Authorize the file before issuing a session-bound download token."""
    workspace = await workspace_service.resolve(user_id, agent_id, session_id)
    target = await workspace_service.resolve_path(workspace, path)
    async with workspace_service.open_file(workspace, target):
        pass
    token, expires_at = workspace_service.sign_download_token(
        user_id,
        agent_id,
        session_id,
        path,
        ttl=_PREVIEW_TOKEN_TTL if preview else DEFAULT_DOWNLOAD_TOKEN_TTL,
    )
    return DownloadTokenResponse(token=token, expires_at=expires_at)


@workspace_router.get("/files")
async def read_workspace_file(
    agent_id: str = Query(...),
    session_id: str = Query(...),
    path: str = Query(
        ...,
        description="Personal-space (~) or Agent-relative file path.",
    ),
    download: bool = Query(
        default=False,
        description="Force a Content-Disposition attachment.",
    ),
    token: str = Query(..., description="Signed file download capability."),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> StreamingResponse:
    """Stream one file out of a session's workspace.

    The body is piped chunk by chunk rather than read whole: the API
    process is shared, so one large download must not be able to
    exhaust it for everyone else.
    """
    try:
        user_id = workspace_service.verify_download_token(
            token, agent_id, session_id, path
        )
    except ValueError as exc:
        raise HTTPException(401, "Invalid or expired download token.") from exc

    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    backend = workspace.get_backend()
    target = await workspace_service.resolve_path(workspace, path)
    basename = backend.basename(target) or "download"

    context = workspace_service.open_file(workspace, target)
    opened = await context.__aenter__()
    closed = False

    async def close() -> None:
        nonlocal closed
        if not closed:
            closed = True
            await context.__aexit__(None, None, None)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in opened.stream:
                yield chunk
        finally:
            await close()

    media_type = (
        mimetypes.guess_type(basename)[0] or "application/octet-stream"
    )
    headers = file_headers(basename, media_type, download)
    headers["Content-Length"] = str(opened.size)
    return StreamingResponse(
        body(),
        media_type=media_type,
        headers=headers,
        background=BackgroundTask(close),
    )


_MAX_WORKSPACE_PREVIEW_BYTES = 10 * 1024 * 1024
_MAX_WORKSPACE_PREVIEW_CHARS = 500_000
_MAX_WORKSPACE_PREVIEW_PDF_BYTES = 50 * 1024 * 1024
_OFFICE_PREVIEW_TIMEOUT_SECONDS = 45
_OFFICE_PREVIEW_EXTENSIONS = {
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
}
_OFFICE_PREVIEW_SEMAPHORE = asyncio.Semaphore(1)


@workspace_router.get("/files/preview-pdf")
async def preview_workspace_file_pdf(
    agent_id: str = Query(...),
    session_id: str = Query(...),
    path: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> Response:
    """Render an Office file to a temporary PDF for inline preview."""
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    backend = workspace.get_backend()
    target = await workspace_service.resolve_path(workspace, path)
    basename = backend.basename(target) or "preview"
    extension = Path(basename).suffix.lower()
    if extension not in _OFFICE_PREVIEW_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="This file type does not support Office preview.",
        )

    import uuid

    temporary = backend.join_path("/tmp", "preview-" + uuid.uuid4().hex)
    source = backend.join_path(temporary, "source" + extension)
    output = backend.join_path(temporary, "output")
    try:
        async with workspace_service.open_file(workspace, target) as opened:
            if opened.size > _MAX_WORKSPACE_PREVIEW_BYTES:
                raise HTTPException(
                    413, "File is too large for an inline preview."
                )
            await backend.write_stream(source, opened.stream)
        await backend.exec_shell(["mkdir", "-p", output])
        async with _OFFICE_PREVIEW_SEMAPHORE:
            result = await backend.exec_shell(
                [
                    "soffice",
                    "-env:UserInstallation=file://" + temporary + "/profile",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--norestore",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    output,
                    source,
                ],
                timeout=_OFFICE_PREVIEW_TIMEOUT_SECONDS,
            )
        if not result.ok():
            raise HTTPException(422, "Office preview conversion failed.")
        pdf_path = backend.join_path(output, "source.pdf")
        async with backend.open_read(pdf_path, root=temporary) as opened:
            if opened.size > _MAX_WORKSPACE_PREVIEW_PDF_BYTES:
                raise HTTPException(413, "Rendered preview is too large.")
            content = b"".join([chunk async for chunk in opened.stream])
        return Response(
            content,
            media_type="application/pdf",
            headers=file_headers(
                Path(basename).stem + ".pdf", "application/pdf", False
            ),
        )
    finally:
        await backend.delete_path(temporary)


@workspace_router.get("/files/preview-text")
async def preview_workspace_file_text(
    request: Request,
    agent_id: str = Query(...),
    session_id: str = Query(...),
    path: str = Query(...),
    user_id: str = Depends(get_current_user_id),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, str | bool]:
    """Extract a bounded text preview from a generated workspace file.

    Browser-native formats use ``GET /workspace/files`` directly. This
    endpoint reuses the application's configured parsers for office formats
    such as Word, Excel, and PowerPoint, without creating a knowledge-base
    document or moving the file.
    """
    workspace = await workspace_service.resolve(
        user_id,
        agent_id,
        session_id,
    )
    backend = workspace.get_backend()
    target = await workspace_service.resolve_path(workspace, path)
    basename = backend.basename(target) or "preview"
    entry = await backend.stat(target)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found.",
        )
    if entry.is_dir:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Requested path is a directory, not a file.",
        )
    if (
        entry.size_bytes is not None
        and entry.size_bytes > _MAX_WORKSPACE_PREVIEW_BYTES
    ):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File is too large for an inline preview.",
        )

    extension = Path(basename).suffix.lower()
    parsers = getattr(request.app.state, "knowledge_parsers", None) or []
    parser_list = (
        list(parsers.values()) if isinstance(parsers, dict) else parsers
    )
    parser = next(
        (
            candidate
            for candidate in parser_list
            if extension in candidate.supported_extensions()
        ),
        None,
    )

    payload = bytearray()
    async with workspace_service.open_file(workspace, target) as opened:
        async for chunk in opened.stream:
            if len(payload) + len(chunk) > _MAX_WORKSPACE_PREVIEW_BYTES:
                raise HTTPException(
                    413, "File is too large for an inline preview."
                )
            payload.extend(chunk)

    if parser is not None:
        try:
            sections = await parser.parse(bytes(payload), basename)
            parts: list[str] = []
            for section in sections:
                if not isinstance(section.content, TextBlock):
                    continue
                text = section.content.text.strip()
                if not text:
                    continue
                labels = [
                    f"{key}: {value}"
                    for key, value in section.metadata.items()
                    if key != "media_type"
                ]
                if labels:
                    text = f"[{', '.join(labels)}]\n{text}"
                parts.append(text)
            content = "\n\n".join(parts)
            if content:
                truncated = len(content) > _MAX_WORKSPACE_PREVIEW_CHARS
                if truncated:
                    content = content[:_MAX_WORKSPACE_PREVIEW_CHARS].rstrip()
                return {
                    "text": content,
                    "truncated": truncated,
                    "mode": "document",
                }
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Could not parse workspace file %r for preview: %s",
                basename,
                exc,
            )

    payload_bytes = bytes(payload)
    try:
        decoded = payload_bytes.decode("utf-8-sig")
        printable = sum(
            char.isprintable() or char in "\r\n\t" for char in decoded
        )
        if not decoded or printable / len(decoded) >= 0.9:
            truncated = len(decoded) > _MAX_WORKSPACE_PREVIEW_CHARS
            return {
                "text": decoded[:_MAX_WORKSPACE_PREVIEW_CHARS],
                "truncated": truncated,
                "mode": "text",
            }
    except UnicodeDecodeError:
        pass

    # Unknown binary formats still get a small raw preview. The original
    # file remains available through the adjacent download action.
    sample = payload_bytes[:2048]
    lines = []
    for offset in range(0, len(sample), 16):
        row = sample[offset : offset + 16]
        hex_bytes = " ".join(f"{byte:02x}" for byte in row)
        readable = "".join(
            chr(byte) if 32 <= byte < 127 else "." for byte in row
        )
        lines.append(f"{offset:08x}  {hex_bytes:<47}  {readable}")
    return {
        "text": "\n".join(lines) or "(empty file)",
        "truncated": len(payload_bytes) > len(sample),
        "mode": "hex",
    }
