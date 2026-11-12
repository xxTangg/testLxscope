# -*- coding: utf-8 -*-
"""Default library overlay and per-account uninstall preferences.

Defaults are virtual, while explicit installs/uninstalls use normal SkillRecord
rows. Read paths never write defaults, so concurrent reads cannot resurrect an
uninstalled default. The same storage contract works with Redis and SQL.
"""

import json

from ..hub import BuiltinSkillHub, SkillHubBase
from ..hub._skill._builtin_hub import BUILTIN_MARKER
from ..storage import SkillRecord, StorageBase
from ...skill import Skill
from ...workspace import WorkspaceBase


async def list_user_skills(
    storage: StorageBase,
    hubs: dict[str, SkillHubBase],
    user_id: str,
) -> list[SkillRecord]:
    """Overlay local defaults with persistent, user-scoped preferences."""
    stored = await storage.list_skills(user_id)
    records = {record.id: record for record in stored}
    occupied = {record.name for record in stored}
    for hub in hubs.values():
        if not isinstance(hub, BuiltinSkillHub):
            continue
        for card_id in hub.cards:
            default = hub.record(user_id, card_id)
            preference = records.get(default.id)
            if preference is not None:
                # Refresh bundled content while preserving explicit opt-out.
                default.enabled = preference.enabled
                default.created_at = preference.created_at
                records[default.id] = default
            elif default.name not in occupied:
                records[default.id] = default
                occupied.add(default.name)
    return [
        record
        for record in records.values()
        if not (
            isinstance(hubs.get(record.hub_id or ""), BuiltinSkillHub)
            and not record.enabled
        )
    ]


async def get_user_skill(
    storage, hubs, user_id, skill_id
) -> SkillRecord | None:
    """Resolve only a skill visible in the caller's library."""
    return next(
        (
            record
            for record in await list_user_skills(storage, hubs, user_id)
            if record.id == skill_id
        ),
        None,
    )


async def uninstall_user_skill(storage, hubs, user_id, skill_id) -> bool:
    """Retain opt-outs for defaults; delete ordinary user installations."""
    record = await get_user_skill(storage, hubs, user_id, skill_id)
    if record is None:
        return False
    hub = hubs.get(record.hub_id or "")
    if isinstance(hub, BuiltinSkillHub):
        record.enabled = False
        await storage.upsert_skill(user_id, record)
        return True
    return await storage.delete_skill(user_id, skill_id)


async def _read_builtin_marker(
    workspace: WorkspaceBase,
    skill: Skill,
) -> dict | None:
    backend = workspace.get_backend()
    path = backend.join_path(skill.dir, BUILTIN_MARKER)
    if not await backend.file_exists(path):
        return None
    try:
        marker = json.loads(await backend.read_file(path))
    except (ValueError, OSError):
        return None
    if isinstance(marker, dict) and all(
        isinstance(marker.get(key), str) and marker[key]
        for key in ("hub_id", "card_id", "version")
    ):
        return marker
    return None


async def list_workspace_skills(
    workspace: WorkspaceBase,
    agent_id: str,
) -> list[Skill]:
    """Exclude legacy copies whose marker cannot prove an explicit add."""
    skills = []
    for skill in await workspace.list_skills(agent_id=agent_id):
        marker = await _read_builtin_marker(workspace, skill)
        if marker is None or marker.get("added_to_workspace") is True:
            skills.append(skill)
    return skills


async def activate_workspace_builtin_skill(
    workspace: WorkspaceBase,
    agent_id: str,
    record: SkillRecord,
) -> bool:
    """Reuse a bundled copy when the user adds it, preserving local edits."""
    for skill in await workspace.list_skills(agent_id=agent_id):
        marker = await _read_builtin_marker(workspace, skill)
        if marker is None or (
            marker["hub_id"], marker["card_id"]
        ) != (record.hub_id, record.card_id):
            continue
        if marker.get("added_to_workspace") is not True:
            backend = workspace.get_backend()
            marker["added_to_workspace"] = True
            await backend.write_file(
                backend.join_path(skill.dir, BUILTIN_MARKER),
                json.dumps(marker).encode(),
            )
        return True
    return False
