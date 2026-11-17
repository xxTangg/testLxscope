# -*- coding: utf-8 -*-
# pylint: disable=protected-access
"""Session instants stay unambiguous across storage and host timezones."""
import json
from datetime import datetime, timedelta, timezone
from unittest import IsolatedAsyncioTestCase, TestCase

import fakeredis.aioredis

from agentscope.app.storage import (
    AsyncSQLAlchemyStorage,
    RedisStorage,
    SessionConfig,
    SessionRecord,
)
from agentscope.app.storage._sql._tables import SessionRow
from agentscope.state import AgentState


class SessionTimestampTest(TestCase):
    """UTC offsets survive legacy reads and API serialization."""

    def test_new_session_has_utc_timestamps(self) -> None:
        """Defaults must not depend on the server's local clock zone."""
        before = datetime.now(timezone.utc)
        record = SessionRecord(
            user_id="user-1",
            agent_id="agent-1",
            config=SessionConfig(workspace_id="ws-1"),
        )
        after = datetime.now(timezone.utc)
        for stamp in (record.created_at, record.updated_at):
            self.assertEqual(stamp.utcoffset(), timedelta(0))
            self.assertLessEqual(before, stamp)
            self.assertLessEqual(stamp, after)
        self.assertIn(
            record.config.name,
            {
                before.strftime("%Y-%m-%d %H:%M:%S"),
                after.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )

    def test_legacy_and_offset_records_normalize_to_utc(self) -> None:
        """Legacy Docker and SQL timestamps represent UTC, not host time."""
        expected = datetime(2026, 11, 13, 6, 51, 38, tzinfo=timezone.utc)
        for value in (
            "2026-11-13T06:51:38",
            "2026-11-13T06:51:38Z",
            "2026-11-13T14:51:38+08:00",
        ):
            with self.subTest(value=value):
                record = SessionRecord.model_validate(
                    {
                        "user_id": "user-1",
                        "agent_id": "agent-1",
                        "config": {"workspace_id": "ws-1"},
                        "created_at": value,
                        "updated_at": value,
                    },
                )
                self.assertEqual(record.created_at, expected)
                self.assertEqual(record.updated_at, expected)
                dump = record.model_dump(mode="json")
                self.assertEqual(
                    dump["created_at"],
                    "2026-11-13T06:51:38+00:00",
                )
                self.assertEqual(dump["updated_at"], dump["created_at"])

    def test_naive_sql_write_stamps_serialize_with_offset(self) -> None:
        """SQL stamps returned records in place without model validation."""
        record = SessionRecord(
            user_id="user-1",
            agent_id="agent-1",
            config=SessionConfig(workspace_id="ws-1"),
        )
        record.created_at = datetime(2026, 11, 13, 6, 51, 38)
        record.updated_at = datetime(2026, 11, 13, 6, 52)
        self.assertEqual(
            record.model_dump(mode="json")["created_at"],
            "2026-11-13T06:51:38+00:00",
        )
        loaded = SessionRecord.model_validate_json(record.model_dump_json())
        self.assertEqual(loaded.updated_at.utcoffset(), timedelta(0))


class RedisSessionTimestampTest(IsolatedAsyncioTestCase):
    """New and historical Redis sessions can coexist and be updated."""

    async def test_mixed_records_sort_and_keep_utc_on_update(self) -> None:
        """Adding offsets must not break sorting or reset creation time."""
        storage = RedisStorage()
        client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        storage._client = client
        try:
            legacy = SessionRecord(
                id="legacy-session",
                user_id="user-1",
                agent_id="agent-1",
                config=SessionConfig(workspace_id="ws-1"),
            ).model_dump(mode="json")
            legacy["created_at"] = "2026-11-13T06:51:38"
            legacy["updated_at"] = "2026-11-13T06:51:38"
            await client.set(
                storage._key(
                    storage.key_config.session,
                    user_id="user-1",
                    session_id="legacy-session",
                ),
                json.dumps(legacy),
            )
            await client.sadd(
                storage._key(
                    storage.key_config.session_index,
                    user_id="user-1",
                    agent_id="agent-1",
                ),
                "legacy-session",
            )
            fresh = await storage.upsert_session(
                "user-1",
                "agent-1",
                SessionConfig(workspace_id="ws-2"),
            )
            records = await storage.list_sessions("user-1", "agent-1")
            self.assertEqual(len(records), 2)
            self.assertTrue(
                all(r.created_at.utcoffset() == timedelta(0) for r in records),
            )
            updated = await storage.upsert_session(
                "user-1",
                "agent-1",
                SessionConfig(workspace_id="ws-2", name="renamed"),
                session_id=fresh.id,
            )
            self.assertEqual(updated.created_at, fresh.created_at)
            self.assertEqual(updated.updated_at.utcoffset(), timedelta(0))
            await storage.update_session_state(
                "user-1",
                "agent-1",
                "legacy-session",
                AgentState(),
            )
            loaded = await storage.get_session(
                "user-1",
                "agent-1",
                "legacy-session",
            )
            self.assertEqual(
                loaded.created_at.isoformat(),
                "2026-11-13T06:51:38+00:00",
            )
            self.assertEqual(loaded.updated_at.utcoffset(), timedelta(0))
        finally:
            await client.aclose()


class SQLSessionTimestampTest(IsolatedAsyncioTestCase):
    """SQL keeps naive UTC columns and emits aware UTC session records."""

    async def test_legacy_sql_session_is_not_shifted_on_update(self) -> None:
        """A non-UTC host must not convert already-UTC columns twice."""
        from sqlalchemy import update

        async with AsyncSQLAlchemyStorage("sqlite+aiosqlite://") as storage:
            created = await storage.upsert_session(
                "user-1",
                "agent-1",
                SessionConfig(workspace_id="ws-1"),
            )
            self.assertTrue(
                created.model_dump(mode="json")["created_at"].endswith(
                    "+00:00",
                ),
            )
            legacy_time = datetime(2026, 11, 13, 6, 51, 38)
            async with storage._session() as session:
                await session.execute(
                    update(SessionRow)
                    .where(SessionRow.id == created.id)
                    .values(created_at=legacy_time, updated_at=legacy_time),
                )
                await session.commit()
            loaded = await storage.get_session(
                "user-1",
                "agent-1",
                created.id,
            )
            self.assertEqual(
                loaded.created_at,
                legacy_time.replace(tzinfo=timezone.utc),
            )
            updated = await storage.upsert_session(
                "user-1",
                "agent-1",
                SessionConfig(workspace_id="ws-1", name="renamed"),
                session_id=created.id,
            )
            self.assertEqual(
                updated.model_dump(mode="json")["created_at"],
                "2026-11-13T06:51:38+00:00",
            )
