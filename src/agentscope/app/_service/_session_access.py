# -*- coding: utf-8 -*-
"""Ownership checks shared by session entry points and background runs."""

from fastapi import HTTPException

from ..storage import SessionRecord, StorageBase


async def require_session(
    storage: StorageBase,
    user_id: str,
    agent_id: str,
    session_id: str,
) -> SessionRecord:
    """Resolve the full owner/Agent/session identity before any side effect."""
    record = await storage.get_session(user_id, agent_id, session_id)
    if (
        record is None
        or record.user_id != user_id
        or record.agent_id != agent_id
    ):
        raise HTTPException(404, "Session not found.")
    return record
