# -*- coding: utf-8 -*-
"""Schemas for equipping a workspace with MCPs and skills."""

from pydantic import BaseModel, Field

from ....mcp import MCPClient


class AddFromLibraryRequest(BaseModel):
    """The request to put library MCPs into a workspace."""

    mcp_ids: list[str] = Field(
        description="The installed-MCP record ids to add.",
    )


class AddSkillsFromLibraryRequest(BaseModel):
    """The request to put library skills into a workspace."""

    skill_ids: list[str] = Field(
        description="The installed-skill record ids to add.",
    )


class AddFromLibraryResponse(BaseModel):
    """What landed, and what did not.

    Reported per item rather than as one status: installing is done one
    at a time, so a bad API key on the third pick must not throw away
    the two that worked.
    """

    added: list[str] = Field(
        default_factory=list,
        description=(
            "The names now in the workspace. Excludes ones already "
            "present, which are skipped rather than re-added."
        ),
    )
    failed: dict[str, str] = Field(
        default_factory=dict,
        description="Whatever could not be added, mapped to why.",
    )


class DirectoryEntry(BaseModel):
    """One entry in a workspace directory listing."""

    name: str = Field(
        description="The entry name, without any leading directory.",
    )
    display_name: str = Field(
        description="Human-readable label; name remains the path component."
    )
    is_dir: bool = Field(
        description="Whether the entry is itself a directory.",
    )
    size_bytes: int | None = Field(
        default=None,
        description=(
            "File size in bytes. Always null for a directory, and null "
            "for a file the backend could not stat."
        ),
    )
    updated_at: float | None = Field(
        default=None,
        description="Last modification time as a Unix timestamp.",
    )


class DirectoryListing(BaseModel):
    """One directory level, plus the path it actually resolved to."""

    path: str = Field(description="Logical personal-space path, rooted at ~.")
    parent_path: str | None = Field(
        description="Authorized parent path; null at the personal root."
    )
    entries: list[DirectoryEntry] = Field(
        description="The directory's immediate children, unsorted.",
    )


class DownloadTokenResponse(BaseModel):
    """A capability authorizing one download of one path."""

    token: str = Field(
        description="Capability bound to user, Agent, session and file."
    )
    expires_at: float = Field(
        description="Unix timestamp after which the token is refused.",
    )


class ToolInfo(BaseModel):
    """The tool info."""

    name: str
    description: str | None = None


class MCPClientStatus(MCPClient):
    """MCPClient enriched with live tool list and health status."""

    is_healthy: bool = False
    tools: list[ToolInfo] = Field(default_factory=list)
    error: str | None = Field(
        default=None,
        description=(
            "Why listing this MCP's tools failed. A red dot alone leaves "
            "the user with nothing to act on — a wrong API key, an "
            "unreachable host and a missing command all look the same."
        ),
    )
