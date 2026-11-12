# -*- coding: utf-8 -*-
"""Skill router — the user's own library of installed skills.

The skill counterpart of :mod:`._mcp`: this is the user-level collection
an install lands in, distinct from ``/workspace/skill``, which manages
the skills present in one session's workspace.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from ..deps import get_current_user_id, get_storage, get_skill_hubs
from ..hub import SkillHubBase
from .._service._builtin_skills import (
    get_user_skill,
    list_user_skills,
    uninstall_user_skill,
)
from ..storage import SkillRecord, StorageBase
from ._schema import SkillView

skill_router = APIRouter(prefix="/skill", tags=["skill"])


@skill_router.get("")
async def list_skills(
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    hubs: dict[str, SkillHubBase] = Depends(get_skill_hubs),
) -> list[SkillView]:
    """Return every skill the user has installed, ordered by name."""
    records = await list_user_skills(storage, hubs, user_id)
    return sorted(
        (SkillView.from_record(r) for r in records),
        key=lambda view: view.name,
    )


@skill_router.get("/{skill_id}")
async def get_skill(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    hubs: dict[str, SkillHubBase] = Depends(get_skill_hubs),
) -> SkillRecord:
    """Return one installed skill, including its ``SKILL.md`` body."""
    record = await get_user_skill(storage, hubs, user_id, skill_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No installed skill with id {skill_id!r}.",
        )
    return record


@skill_router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
    storage: StorageBase = Depends(get_storage),
    hubs: dict[str, SkillHubBase] = Depends(get_skill_hubs),
) -> None:
    """Remove a skill from the user's library.

    Built-in opt-outs are persistent and apply to workspaces on their next
    skill discovery or chat turn. Ordinary uploaded skills keep their copies.
    """
    if not await uninstall_user_skill(storage, hubs, user_id, skill_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No installed skill with id {skill_id!r}.",
        )
