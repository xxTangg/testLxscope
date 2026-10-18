# -*- coding: utf-8 -*-
"""DAG execution over real SQLite storage, without model or network calls."""
import asyncio
import tempfile
from typing import Any
from pathlib import Path
from types import SimpleNamespace
from collections import Counter
from contextlib import AsyncExitStack
from unittest import IsolatedAsyncioTestCase

from pydantic import ValidationError

from agentscope.app._service import SOPService, SessionService
from agentscope.app._tool import SubmitHandover, SubmitVerdict
from agentscope.app.message_bus import InMemoryMessageBus
from agentscope.app.storage import (
    AsyncSQLAlchemyStorage,
    SOPData,
    SOPRecord,
    SOPRunRecord,
)
from agentscope.message import (
    ToolResultState,
    UserMsg,
    AssistantMsg,
    ToolCallBlock,
    ToolCallState,
)
from agentscope.sop import SOPPhase
from agentscope.tool._builtin._backend import LocalBackend

MODEL = {
    "type": "dashscope",
    "credential_id": "c",
    "model": "qwen-max",
    "parameters": {},
}


def definition(human: bool = False) -> SOPData:
    return SOPData.model_validate(
        {
            "name": "diamond",
            "execution_mode": "dag",
            "max_concurrency": 2,
            "workspace_grain": "per_node",
            "steps": [
                {
                    "id": key,
                    "subject": key,
                    "description": f"do {key}",
                    "depends_on": parents,
                    "executor": {"agent_id": "agent", "session_key": "worker"},
                    "verifier": {"type": "human"}
                    if human and key == "c"
                    else None,
                    "max_attempts": 1,
                    "retry_delay_seconds": 0,
                }
                for key, parents in (
                    ("a", []),
                    ("b", ["a"]),
                    ("c", ["a"]),
                    ("d", ["b", "c"]),
                )
            ],
            "session_settings": {"worker": {"chat_model_config": MODEL}},
        }
    )


class Chat:
    def __init__(
        self,
        storage: Any,
        bus: Any,
        failures: Any = (),
        parallel: bool = False,
    ) -> None:
        self.storage, self.bus = storage, bus
        self.calls = Counter()
        self.failures = set(failures)
        self.parallel = parallel
        self.started = {"b": asyncio.Event(), "c": asyncio.Event()}
        self.block = None
        self.openings = {}

    async def run(
        self,
        user_id: Any,
        session_id: Any,
        agent_id: Any,
        opening: Any,
        sop_dispatch: Any,
    ) -> None:
        from agentscope.app.storage._model._sop import _parse_sop_dispatch

        run_id, index, _ = _parse_sop_dispatch(sop_dispatch)
        run = await self.storage.get_sop_run(user_id, run_id)
        key = run.definition.steps[index].id
        state = run.state.steps[index]
        self.calls[key] += 1
        self.openings[key] = opening
        if key in self.started:
            self.started[key].set()
            if self.parallel:
                await asyncio.wait_for(self.started["b"].wait(), 2)
                await asyncio.wait_for(self.started["c"].wait(), 2)
        if key == "b" and self.block:
            await self.block.wait()
        if key in self.failures:
            self.failures.remove(key)
            return
        result = await SubmitHandover(
            self.storage,
            user_id,
            run_id,
            index,
            message_bus=self.bus,
            expected_attempt_id=state.attempt_id,
            expected_generation=state.generation,
        )(handover=f"result {key}", outputs={"value": key})
        assert result.state is ToolResultState.SUCCESS, result


class SOPDAGTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.stack = AsyncExitStack()
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.storage = await self.stack.enter_async_context(
            AsyncSQLAlchemyStorage(
                f"sqlite+aiosqlite:///{directory}/test.db", create_tables=True
            )
        )
        self.bus = await self.stack.enter_async_context(InMemoryMessageBus())
        self.chat = Chat(self.storage, self.bus)
        self.service = SOPService(
            self.storage,
            None,
            self.bus,
            self.chat,
            SessionService(self.storage, self.bus),
        )

    async def asyncTearDown(self) -> None:
        await self.service.__aexit__()
        await self.stack.aclose()

    async def create(self, data: SOPData | None = None) -> SOPRunRecord:
        sop = SOPRecord(user_id="user", data=data or definition())
        await self.storage.upsert_sop("user", sop)
        return await self.service.create_run("user", sop.id)

    async def settle(self) -> None:
        await asyncio.gather(
            *(
                task
                for tasks in list(self.service._advancing.values())
                for task in list(tasks)
            )
        )

    async def test_parallel_failure_and_retry_preserve_successful_nodes(
        self,
    ) -> None:
        self.chat.parallel = True
        self.chat.failures.add("c")
        run = await self.create()
        state = await self.service.run("user", run.id)
        self.assertEqual(
            [node.phase for node in state.steps],
            [
                SOPPhase.COMPLETED,
                SOPPhase.COMPLETED,
                SOPPhase.FAILED,
                SOPPhase.BLOCKED,
            ],
        )
        self.assertEqual(self.chat.calls, {"a": 1, "b": 1, "c": 1})
        await self.service.retry_node(
            "user", run.id, "c", expected_generation=0
        )
        await self.settle()
        stored = await self.storage.get_sop_run("user", run.id)
        self.assertEqual(stored.state.phase, SOPPhase.COMPLETED)
        self.assertEqual(self.chat.calls, {"a": 1, "b": 1, "c": 2, "d": 1})
        self.assertEqual(len(stored.state.steps[2].attempts), 2)
        self.assertIn("result b", str(self.chat.openings["d"]))
        self.assertIn("result c", str(self.chat.openings["d"]))

    async def test_rerun_invalidates_only_descendants_and_retains_history(
        self,
    ) -> None:
        run = await self.create()
        await self.service.run("user", run.id)
        with self.assertRaises(ValueError):
            await self.service.retry_node("user", run.id, "b")
        await self.service.retry_node(
            "user", run.id, "b", include_descendants=True
        )
        await self.settle()
        self.assertEqual(self.chat.calls, {"a": 1, "b": 2, "c": 1, "d": 2})
        stored = await self.storage.get_sop_run("user", run.id)
        self.assertEqual(
            stored.state.steps[1].attempts[0].outputs, {"value": "b"}
        )

    async def test_restart_recovers_work_and_keeps_completed_outputs(
        self,
    ) -> None:
        self.chat.block = asyncio.Event()
        run = await self.create()
        self.service.advance_later("user", run.id)
        await asyncio.wait_for(self.chat.started["b"].wait(), 3)
        await self.service.__aexit__()
        replacement = Chat(self.storage, self.bus)
        self.service = SOPService(
            self.storage,
            None,
            self.bus,
            replacement,
            SessionService(self.storage, self.bus),
        )
        await self.service.recover()
        await self.settle()
        stored = await self.storage.get_sop_run("user", run.id)
        self.assertEqual(stored.state.phase, SOPPhase.COMPLETED)
        self.assertEqual(replacement.calls["a"], 0)
        self.assertGreaterEqual(len(stored.state.steps[1].attempts), 2)

    async def test_human_rejection_obeys_budget_and_cannot_approve_a_tool_wait(
        self,
    ) -> None:
        run = await self.create(definition(human=True))
        await self.service.run("user", run.id)
        stored = await self.storage.get_sop_run("user", run.id)
        token = stored.state.steps[2].attempt_id
        with self.assertRaises(ValueError):
            await self.service.record_verdict(
                "user", run.id, 2, True, expected_attempt_id="old-attempt"
            )
        await self.service.record_verdict(
            "user", run.id, 2, False, "fix c", token
        )
        await self.service.run("user", run.id)
        self.assertEqual(self.chat.calls["c"], 1)
        stored = await self.storage.get_sop_run("user", run.id)
        self.assertEqual(stored.state.steps[2].phase, SOPPhase.FAILED)
        node = stored.state.steps[2]
        node.phase, node.wait_reason, node.submission = (
            SOPPhase.AWAITING,
            "tool",
            None,
        )
        await self.storage.upsert_sop_run("user", stored)
        with self.assertRaises(ValueError):
            await self.service.record_verdict(
                "user", run.id, 2, True, expected_attempt_id=token
            )

    async def test_late_attempt_and_conflicting_duplicate_verdicts_are_rejected(
        self,
    ) -> None:
        run = await self.create(definition(human=True))
        await self.service.run("user", run.id)
        stored = await self.storage.get_sop_run("user", run.id)
        node = stored.state.steps[2]
        tool = SubmitVerdict(
            self.storage,
            "user",
            run.id,
            2,
            message_bus=self.bus,
            expected_attempt_id=node.attempt_id,
            expected_generation=node.generation,
            verifier="reviewer",
        )
        self.assertEqual((await tool(True)).state, ToolResultState.SUCCESS)
        self.assertEqual((await tool(True)).state, ToolResultState.SUCCESS)
        self.assertEqual(
            (await tool(False, "late change")).state, ToolResultState.ERROR
        )
        stored = await self.storage.get_sop_run("user", run.id)
        self.assertEqual(len(stored.state.steps[2].verifications), 1)
        await self.service.retry_node(
            "user", run.id, "c", include_descendants=True
        )
        self.assertEqual((await tool(True)).state, ToolResultState.ERROR)
        await self.settle()

    async def test_tool_resume_waits_for_session_checkpoint_before_human_review(
        self,
    ) -> None:
        from agentscope.app.message_bus import MessageBusKeys
        from agentscope.app.storage._model._sop import _parse_sop_dispatch

        run = await self.create(definition(human=True))
        original_run = self.chat.run

        async def park_c(
            user: Any,
            session_id: Any,
            agent: Any,
            opening: Any,
            sop_dispatch: Any,
        ) -> None:
            run_id, index, _ = _parse_sop_dispatch(sop_dispatch)
            if index != 2:
                return await original_run(
                    user, session_id, agent, opening, sop_dispatch
                )
            self.chat.calls["c"] += 1
            session = await self.storage.get_session(user, agent, session_id)
            session.state.context = [
                AssistantMsg(
                    name="agent",
                    content=[
                        ToolCallBlock(
                            type="tool_call",
                            id="call",
                            name="shell",
                            input="{}",
                            state=ToolCallState.SUBMITTED,
                        )
                    ],
                )
            ]
            await self.storage.upsert_session(
                user_id=user,
                agent_id=agent,
                config=session.config,
                state=session.state,
                session_id=session.id,
                origin=session.origin,
            )

        self.chat.run = park_c
        await self.service.run("user", run.id)
        stored = await self.storage.get_sop_run("user", run.id)
        node = stored.state.steps[2]
        self.assertEqual(node.waiting_on, "executor")
        session_id = stored.sessions["c/worker"]
        async with self.bus.acquire_lock(
            MessageBusKeys.session_lock(session_id)
        ):
            await SubmitHandover(
                self.storage,
                "user",
                run.id,
                2,
                message_bus=self.bus,
                expected_attempt_id=node.attempt_id,
            )("resumed result")
            await self.service.run("user", run.id)
            with self.assertRaises(ValueError):
                await self.service.record_verdict(
                    "user",
                    run.id,
                    2,
                    True,
                    expected_attempt_id=node.attempt_id,
                )
            session = await self.storage.get_session(
                "user", "agent", session_id
            )
            session.state.context = []
            await self.storage.upsert_session(
                user_id="user",
                agent_id="agent",
                config=session.config,
                state=session.state,
                session_id=session.id,
                origin=session.origin,
            )
        await self.service.run("user", run.id)
        stored = await self.storage.get_sop_run("user", run.id)
        self.assertEqual(stored.state.steps[2].wait_reason, "human")
        self.assertEqual(self.chat.calls["c"], 1)
        await self.service.record_verdict(
            "user", run.id, 2, True, expected_attempt_id=node.attempt_id
        )
        await self.service.run("user", run.id)
        self.assertEqual(
            (await self.storage.get_sop_run("user", run.id)).state.phase,
            SOPPhase.COMPLETED,
        )

    async def test_bindings_include_global_inputs_and_schema_checks_outputs(
        self,
    ) -> None:
        data = definition()
        data.steps[3].input_bindings = {
            "source": "b.value",
            "metric": "c.value",
        }
        run = await self.create(data)
        stored = await self.storage.get_sop_run("user", run.id)
        stored.state.inputs = [UserMsg(name="user", content="budget: 100")]
        await self.storage.upsert_sop_run("user", stored)
        await self.service.run("user", run.id)
        self.assertIn("budget: 100", str(self.chat.openings["d"]))
        self.assertIn('"metric": "c"', str(self.chat.openings["d"]))

    async def test_cycle_unknown_dependency_and_invalid_binding_are_rejected(
        self,
    ) -> None:
        for change in ("cycle", "unknown", "binding"):
            payload = definition().model_dump()
            if change == "cycle":
                payload["steps"][0]["depends_on"] = ["d"]
            elif change == "unknown":
                payload["steps"][1]["depends_on"] = ["missing"]
            else:
                payload["steps"][1]["input_bindings"] = {"bad": "c.value"}
            with self.subTest(change=change), self.assertRaises(
                ValidationError
            ):
                SOPData.model_validate(payload)

    async def test_output_schema_and_artifact_transfer_are_verified(
        self,
    ) -> None:
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        backend = LocalBackend()

        class Workspaces:
            async def get_workspace(
                self, user: Any, agent: Any, session: Any, workspace_id: Any
            ) -> SimpleNamespace:
                return SimpleNamespace(
                    workdir=str(Path(directory) / workspace_id),
                    get_backend=lambda: backend,
                )

        self.service._workspace_manager = Workspaces()
        data = definition()
        data.steps = data.steps[:2]
        data.steps[0].output_schema = {"type": "object", "required": ["value"]}
        run = await self.create(data)
        original_run = self.chat.run
        received = []

        async def with_files(
            user: Any,
            session_id: Any,
            agent: Any,
            opening: Any,
            sop_dispatch: Any,
        ) -> None:
            from agentscope.app.storage._model._sop import _parse_sop_dispatch

            run_id, index, _ = _parse_sop_dispatch(sop_dispatch)
            record = await self.storage.get_sop_run(user, run_id)
            node = record.state.steps[index]
            session = await self.storage.get_session(user, agent, session_id)
            workspace = await self.service._workspace_manager.get_workspace(
                user, agent, session_id, session.config.workspace_id
            )
            if index == 0:
                await backend.write_file(
                    backend.join_path(workspace.workdir, "result.txt"),
                    b"published evidence",
                )
                tool = SubmitHandover(
                    self.storage,
                    user,
                    run_id,
                    index,
                    message_bus=self.bus,
                    workspace=workspace,
                    session_record=session,
                    expected_attempt_id=node.attempt_id,
                )
                invalid = await tool("draft", outputs={})
                self.assertEqual(invalid.state, ToolResultState.ERROR)
                valid = await tool(
                    "draft",
                    outputs={"value": "a"},
                    artifact_paths=["result.txt"],
                )
                self.assertEqual(valid.state, ToolResultState.SUCCESS)
            else:
                paths = list(Path(workspace.workdir).glob("inputs/a/*"))
                received.extend(path.read_bytes() for path in paths)
                await original_run(
                    user, session_id, agent, opening, sop_dispatch
                )

        self.chat.run = with_files
        await self.service.run("user", run.id)
        self.assertEqual(received, [b"published evidence"])
        stored = await self.storage.get_sop_run("user", run.id)
        artifact = stored.state.steps[0].artifacts[0]
        await backend.write_file(artifact["snapshot_path"], b"tampered")
        await self.service.retry_node(
            "user", run.id, "b", include_descendants=True
        )
        await self.settle()
        stored = await self.storage.get_sop_run("user", run.id)
        self.assertEqual(stored.state.steps[1].phase, SOPPhase.FAILED)
        self.assertIn("changed after submission", stored.state.steps[1].error)

    async def test_cancel_fences_late_results_and_retains_successful_nodes(
        self,
    ) -> None:
        self.chat.block = asyncio.Event()
        run = await self.create()
        self.service.advance_later("user", run.id)
        await asyncio.wait_for(self.chat.started["b"].wait(), 3)
        await self.service.cancel_run("user", run.id)
        stored = await self.storage.get_sop_run("user", run.id)
        self.assertEqual(stored.state.phase, SOPPhase.CANCELLED)
        self.assertEqual(stored.state.steps[0].phase, SOPPhase.COMPLETED)
        with self.assertRaises(ValueError):
            await self.service.retry_node("user", run.id, "b")


class SOPDAGRedisTest(SOPDAGTest):
    """Run the same concurrency/recovery contracts against the deployed backend."""

    async def asyncSetUp(self) -> None:
        import fakeredis.aioredis
        from agentscope.app.storage import RedisStorage
        from agentscope.app.message_bus import RedisMessageBus

        self.stack = AsyncExitStack()
        self.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        self.stack.push_async_callback(self.redis.aclose)

        class Storage(RedisStorage):
            async def __aenter__(inner) -> Any:
                inner._client = self.redis
                return inner

            async def aclose(inner) -> None:
                inner._client = None

        class Bus(RedisMessageBus):
            async def __aenter__(inner) -> Any:
                inner._client = self.redis
                return inner

            async def aclose(inner) -> None:
                inner._client = None

        self.storage = await self.stack.enter_async_context(Storage())
        self.bus = await self.stack.enter_async_context(Bus())
        self.chat = Chat(self.storage, self.bus)
        self.service = SOPService(
            self.storage,
            None,
            self.bus,
            self.chat,
            SessionService(self.storage, self.bus),
        )

    async def test_two_coordinators_do_not_duplicate_successful_nodes(
        self,
    ) -> None:
        run = await self.create()
        other = SOPService(
            self.storage,
            None,
            self.bus,
            self.chat,
            SessionService(self.storage, self.bus),
        )
        await asyncio.gather(
            self.service.run("user", run.id), other.run("user", run.id)
        )
        self.assertEqual(self.chat.calls, {"a": 1, "b": 1, "c": 1, "d": 1})
