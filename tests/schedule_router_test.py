# -*- coding: utf-8 -*-
"""Tests for schedule validation before persistence and registration."""
from datetime import datetime, timedelta
from unittest import IsolatedAsyncioTestCase, TestCase
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from agentscope.app._manager import SchedulerManager
from agentscope.app._manager._scheduler._tools._schedule_create import (
    ScheduleCreate,
)
from agentscope.app._router._schedule import create_schedule, update_schedule
from agentscope.app._router._schema._schedule import (
    CreateScheduleRequest,
    UpdateScheduleRequest,
)
from agentscope.app.storage import (
    ChatModelConfig,
    ScheduleData,
    ScheduleRecord,
)
from agentscope.permission import PermissionMode


class _Access:
    """Allow all resources used by the route under test."""

    async def resolve_agent(self, user_id: str, agent_id: str) -> None:
        """Accept the requested agent."""

    async def get_resource(
        self,
        user_id: str,
        kind: object,
        resource_id: str,
    ) -> None:
        """Accept the requested credential."""


class _Storage:
    """Record schedule writes without requiring Redis or SQL."""

    def __init__(self, existing: ScheduleRecord | None = None) -> None:
        self.existing = existing
        self.upserted: list[ScheduleRecord] = []

    async def get_schedule(
        self,
        user_id: str,
        schedule_id: str,
    ) -> ScheduleRecord | None:
        """Return the one fixture record."""
        _ = user_id, schedule_id
        return self.existing

    async def upsert_schedule(
        self,
        user_id: str,
        record: ScheduleRecord,
    ) -> str:
        """Record the write."""
        _ = user_id
        self.upserted.append(record)
        return record.id


class _Scheduler(SchedulerManager):
    """Track what the owner would be told, keeping real validation."""

    def __init__(self) -> None:
        super().__init__(
            storage=None,
            message_bus=None,
            workspace_manager=None,
        )
        self.notified: list[str] = []

    async def notify_changed(self, schedule_id: str) -> None:
        """Record the nudge without touching the message bus."""
        self.notified.append(schedule_id)


def _request(
    cron_expression: str,
    timezone: str = "UTC",
    ended_at: datetime | None = None,
) -> CreateScheduleRequest:
    """Build a minimal schedule request."""
    return CreateScheduleRequest(
        name="test schedule",
        cron_expression=cron_expression,
        timezone=timezone,
        ended_at=ended_at,
        agent_id="agent-1",
        chat_model_config=ChatModelConfig(
            type="test",
            credential_id="credential-1",
            model="model-1",
            parameters={},
        ),
    )


def _record() -> ScheduleRecord:
    """Build a valid existing schedule record."""
    return ScheduleRecord(
        id="schedule-1",
        user_id="user-1",
        agent_id="agent-1",
        data=ScheduleData(
            name="existing",
            cron_expression="0 9 * * *",
            timezone="UTC",
            started_at=datetime(2026, 1, 1),
            chat_model_config=ChatModelConfig(
                type="test",
                credential_id="credential-1",
                model="model-1",
                parameters={},
            ),
            permission_mode=PermissionMode.DONT_ASK,
        ),
    )


class ScheduleWeekdayTest(TestCase):
    """Standard cron weekdays are translated for APScheduler."""

    def test_standard_weekdays(self) -> None:
        """Numeric weekdays and names select complete two-week sequences."""
        record = _record()
        tz = ZoneInfo("UTC")
        record.data.ended_at = datetime(2026, 1, 14, 23, 59, tzinfo=tz)
        expected_days = {
            "1": [5, 12],
            "0": [4, 11],
            "7": [4, 11],
            "1-5": [1, 2, 5, 6, 7, 8, 9, 12, 13, 14],
            "0-7/3": [3, 4, 7, 10, 11, 14],
            "mon-fri": [1, 2, 5, 6, 7, 8, 9, 12, 13, 14],
        }
        for expression, days in expected_days.items():
            with self.subTest(expression=expression):
                record.data.cron_expression = f"0 9 * * {expression}"
                trigger = SchedulerManager.validate_schedule(record)
                start = datetime(2026, 1, 1, tzinfo=tz)
                previous = None
                dates = []
                for _ in range(15):
                    fire = trigger.get_next_fire_time(previous, start)
                    if fire is None:
                        break
                    dates.append(fire)
                    previous = fire
                    start = fire + timedelta(microseconds=1)
                self.assertEqual(
                    dates,
                    [datetime(2026, 1, day, 9, tzinfo=tz) for day in days],
                )

        record.data.cron_expression = "0 9 * * 8"
        with self.assertRaises(ValueError):
            SchedulerManager.validate_schedule(record)


class ScheduleCalendarTest(TestCase):
    """Standard cron combines restricted day fields with OR, not AND."""

    @staticmethod
    def _fires(record: ScheduleRecord, start: datetime, count: int) -> list:
        """Enumerate actual trigger dates, including overlap and end bounds."""
        trigger = SchedulerManager.validate_schedule(record)
        previous = None
        dates = []
        for _ in range(count):
            fire = trigger.get_next_fire_time(previous, start)
            if fire is None:
                break
            dates.append(fire)
            previous = fire
            start = fire + timedelta(microseconds=1)
        return dates

    def test_month_day_and_weekday_are_alternatives(self) -> None:
        """A monthly-plus-weekly task must not skip months of executions."""
        record = _record()
        record.data.cron_expression = "0 9 1 * 1"
        tz = ZoneInfo("UTC")
        dates = self._fires(record, datetime(2026, 10, 1, tzinfo=tz), 7)
        self.assertEqual(
            dates,
            [
                datetime(2026, month, day, 9, tzinfo=tz)
                for month, day in (
                    (10, 1),
                    (10, 5),
                    (10, 12),
                    (10, 19),
                    (10, 26),
                    (11, 1),
                    (11, 2),
                )
            ],
        )

    def test_overlapping_days_fire_once_within_activation_window(self) -> None:
        """Honor timezone and bounds without duplicate runs."""
        record = _record()
        record.data.cron_expression = "0 9 1 * mon"
        record.data.timezone = "Asia/Shanghai"
        tz = ZoneInfo(record.data.timezone)
        record.data.started_at = datetime(2026, 6, 1, 9, tzinfo=tz)
        record.data.ended_at = datetime(2026, 6, 8, 9, tzinfo=tz)
        self.assertEqual(
            self._fires(record, datetime(2026, 5, 1, tzinfo=tz), 4),
            [
                datetime(2026, 6, 1, 9, tzinfo=tz),
                datetime(2026, 6, 8, 9, tzinfo=tz),
            ],
        )

    def test_wildcard_day_fields_keep_intersection_semantics(self) -> None:
        """A wildcard, including a stepped one, does not add an OR branch."""
        tz = ZoneInfo("UTC")
        for expression, days in (
            ("0 9 * * 1", [5, 12, 19, 26]),
            ("0 9 1 * *", [1]),
            ("0 9 */2 * 1", [5, 19]),
            ("0 9 1-3 * */2", [1, 3]),
        ):
            with self.subTest(expression=expression):
                record = _record()
                record.data.cron_expression = expression
                record.data.ended_at = datetime(2026, 10, 31, 23, tzinfo=tz)
                self.assertEqual(
                    self._fires(record, datetime(2026, 10, 1, tzinfo=tz), 6),
                    [datetime(2026, 10, day, 9, tzinfo=tz) for day in days],
                )

    def test_weekday_branch_survives_an_impossible_month_day(self) -> None:
        """February has no 31st, but the Mondays must still run."""
        record = _record()
        record.data.cron_expression = "0 9 31 2 1"
        tz = ZoneInfo("UTC")
        record.data.ended_at = datetime(2026, 2, 28, 23, tzinfo=tz)
        self.assertEqual(
            self._fires(record, datetime(2026, 2, 1, tzinfo=tz), 5),
            [datetime(2026, 2, day, 9, tzinfo=tz) for day in (2, 9, 16, 23)],
        )

    def test_invalid_weekday_is_not_hidden_by_month_day_branch(self) -> None:
        """A valid first branch must not admit an invalid schedule."""
        record = _record()
        record.data.cron_expression = "0 9 1 * notaday"
        with self.assertRaises(ValueError):
            SchedulerManager.validate_schedule(record)


# UTC-12 sits west of every real server timezone, so a start time taken
# from the server's naive wall clock lands hours in this zone's future.
_FAR_WEST_TZ = "Etc/GMT+12"


class ScheduleDefaultStartTest(IsolatedAsyncioTestCase):
    """A schedule created without a start time is active right away."""

    def _assert_fires_within_the_hour(self, record: ScheduleRecord) -> None:
        trigger = SchedulerManager.validate_schedule(record)
        now = datetime.now().astimezone()
        next_fire = trigger.get_next_fire_time(None, now)
        self.assertIsNotNone(next_fire)
        self.assertLessEqual(next_fire - now, timedelta(hours=1))

    async def test_router_default_start_is_an_absolute_instant(self) -> None:
        """An hourly schedule must not skip runs in a far-off timezone."""
        storage = _Storage()

        await create_schedule(
            _request("0 * * * *", timezone=_FAR_WEST_TZ),
            user_id="user-1",
            storage=storage,
            access=_Access(),
            scheduler=_Scheduler(),
        )

        self._assert_fires_within_the_hour(storage.upserted[0])

    async def test_tool_default_start_is_an_absolute_instant(self) -> None:
        """The agent-facing tool's default start must not drift either."""
        storage = _Storage()
        tool = ScheduleCreate(
            user_id="user-1",
            agent_id="agent-1",
            chat_model_config=_request("0 * * * *").chat_model_config,
            storage=storage,
            scheduler_manager=_Scheduler(),
        )

        await tool(
            name="hourly",
            cron_expression="0 * * * *",
            timezone=_FAR_WEST_TZ,
        )

        self._assert_fires_within_the_hour(storage.upserted[0])

    def test_model_default_start_is_an_absolute_instant(self) -> None:
        """Records built without ``started_at`` get the same guarantee."""
        record = _record()
        record.data = ScheduleData(
            name="hourly",
            cron_expression="0 * * * *",
            timezone=_FAR_WEST_TZ,
            chat_model_config=record.data.chat_model_config,
        )

        self._assert_fires_within_the_hour(record)


class ScheduleValidationTest(IsolatedAsyncioTestCase):
    """Invalid schedules must fail before any state mutation."""

    async def test_create_valid_schedule_persists_and_notifies(self) -> None:
        """The rejections below only mean something if this passes."""
        storage = _Storage()
        scheduler = _Scheduler()

        response = await create_schedule(
            _request("0 9 * * *"),
            user_id="user-1",
            storage=storage,
            access=_Access(),
            scheduler=scheduler,
        )

        self.assertEqual(len(storage.upserted), 1)
        self.assertEqual(storage.upserted[0].id, response.schedule_id)
        self.assertListEqual(scheduler.notified, [response.schedule_id])

    async def test_create_persists_requested_start_time(self) -> None:
        """The first fire is constrained by the selected start instant."""
        storage = _Storage()
        start = datetime(2026, 12, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
        body = _request("0 9 * * *", timezone="Asia/Shanghai")
        body.started_at = start

        await create_schedule(
            body,
            user_id="user-1",
            storage=storage,
            access=_Access(),
            scheduler=_Scheduler(),
        )

        record = storage.upserted[0]
        self.assertEqual(record.data.started_at, start)
        trigger = SchedulerManager.validate_schedule(record)
        self.assertEqual(
            trigger.get_next_fire_time(None, start - timedelta(days=1)),
            start,
        )

    async def test_create_persists_end_time(self) -> None:
        """The HTTP create path must preserve the activation end time."""
        storage = _Storage()
        scheduler = _Scheduler()
        ended_at = datetime(2026, 12, 31, 23, 59, 59)

        await create_schedule(
            _request("0 9 * * *", ended_at=ended_at),
            user_id="user-1",
            storage=storage,
            access=_Access(),
            scheduler=scheduler,
        )

        self.assertEqual(storage.upserted[0].data.ended_at, ended_at)

    async def test_create_empty_timezone_does_not_persist(self) -> None:
        """An empty timezone must not silently mean server-local."""
        storage = _Storage()
        scheduler = _Scheduler()

        with self.assertRaises(HTTPException) as ctx:
            await create_schedule(
                _request("0 9 * * *", timezone=""),
                user_id="user-1",
                storage=storage,
                access=_Access(),
                scheduler=scheduler,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(storage.upserted, [])
        self.assertEqual(scheduler.notified, [])

    async def test_create_invalid_cron_does_not_persist(self) -> None:
        """Create rejects invalid cron before writing the schedule."""
        storage = _Storage()
        scheduler = _Scheduler()

        with self.assertRaises(HTTPException) as ctx:
            await create_schedule(
                _request("not a cron"),
                user_id="user-1",
                storage=storage,
                access=_Access(),
                scheduler=scheduler,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(storage.upserted, [])
        self.assertEqual(scheduler.notified, [])

    async def test_create_out_of_range_cron_does_not_persist(self) -> None:
        """Cron field ranges are checked without constructing a trigger."""
        storage = _Storage()
        scheduler = _Scheduler()

        with self.assertRaises(HTTPException) as ctx:
            await create_schedule(
                _request("61 9 * * *"),
                user_id="user-1",
                storage=storage,
                access=_Access(),
                scheduler=scheduler,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(storage.upserted, [])
        self.assertEqual(scheduler.notified, [])

    async def test_create_invalid_timezone_does_not_persist(self) -> None:
        """Create rejects an unknown timezone before writing the schedule."""
        storage = _Storage()
        scheduler = _Scheduler()

        with self.assertRaises(HTTPException) as ctx:
            await create_schedule(
                _request("0 9 * * *", timezone="Mars/Olympus_Mons"),
                user_id="user-1",
                storage=storage,
                access=_Access(),
                scheduler=scheduler,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(storage.upserted, [])
        self.assertEqual(scheduler.notified, [])

    async def test_update_invalid_cron_keeps_existing_state(self) -> None:
        """Update rejects invalid cron before persisting or notifying."""
        existing = _record()
        storage = _Storage(existing)
        scheduler = _Scheduler()

        with self.assertRaises(HTTPException) as ctx:
            await update_schedule(
                "schedule-1",
                UpdateScheduleRequest(cron_expression="not a cron"),
                user_id="user-1",
                storage=storage,
                scheduler=scheduler,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(storage.upserted, [])
        self.assertEqual(scheduler.notified, [])

    async def test_update_invalid_timezone_keeps_existing_state(self) -> None:
        """Update rejects an unknown timezone before changing state."""
        existing = _record()
        storage = _Storage(existing)
        scheduler = _Scheduler()

        with self.assertRaises(HTTPException) as ctx:
            await update_schedule(
                "schedule-1",
                UpdateScheduleRequest(timezone="Mars/Olympus_Mons"),
                user_id="user-1",
                storage=storage,
                scheduler=scheduler,
            )

        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(storage.upserted, [])
        self.assertEqual(scheduler.notified, [])

    async def test_tool_invalid_cron_does_not_persist(self) -> None:
        """The agent-facing create tool validates before writing too."""
        storage = _Storage()
        scheduler = _Scheduler()
        tool = ScheduleCreate(
            user_id="user-1",
            agent_id="agent-1",
            chat_model_config=_request("0 9 * * *").chat_model_config,
            storage=storage,
            scheduler_manager=scheduler,
        )

        with self.assertRaises(ValueError):
            await tool(name="bad", cron_expression="not a cron")

        self.assertEqual(storage.upserted, [])

    async def test_tool_invalid_timezone_does_not_persist(self) -> None:
        """The agent-facing tool rejects an unknown timezone before writing."""
        storage = _Storage()
        scheduler = _Scheduler()
        tool = ScheduleCreate(
            user_id="user-1",
            agent_id="agent-1",
            chat_model_config=_request("0 9 * * *").chat_model_config,
            storage=storage,
            scheduler_manager=scheduler,
        )

        with self.assertRaises(ValueError):
            await tool(
                name="bad timezone",
                cron_expression="0 9 * * *",
                timezone="Mars/Olympus_Mons",
            )

        self.assertEqual(storage.upserted, [])

    async def test_tool_invalid_time_window_does_not_persist(self) -> None:
        """The agent-facing tool rejects a reversed activation window."""
        storage = _Storage()
        scheduler = _Scheduler()
        tool = ScheduleCreate(
            user_id="user-1",
            agent_id="agent-1",
            chat_model_config=_request("0 9 * * *").chat_model_config,
            storage=storage,
            scheduler_manager=scheduler,
        )

        with self.assertRaises(ValueError):
            await tool(
                name="bad window",
                cron_expression="0 9 * * *",
                started_at=datetime(2026, 1, 2),
                ended_at=datetime(2026, 1, 1),
            )

        self.assertEqual(storage.upserted, [])
