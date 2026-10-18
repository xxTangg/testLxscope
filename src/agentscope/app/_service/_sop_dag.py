# -*- coding: utf-8 -*-
"""Dependency scheduling with durable node checkpoints and bounded concurrency.

The persisted graph is the work queue. A renewable coordinator lease prevents
two processes driving one run; short state locks merge independent node writes.
"""
import asyncio
import hashlib
import json
import time
from typing import Any, Callable

from ..message_bus import MessageBusKeys
from ..storage import (
    AgentVerifier,
    ChatModelConfig,
    SessionConfig,
    SOPOrigin,
    SOPWorkspaceGrain,
    SOPRunRecord,
)
from ..._utils._common import _generate_id
from ...message import Msg, TextBlock, UserMsg
from ...permission import PermissionContext, PermissionMode
from ...sop import SOPAttempt, SOPPhase, SOPRunState, VerificationResult
from ...state import AgentState
from ._session import SessionService


class SOPDAGRunner:
    """One leased coordinator; every node retains its own attempts and output."""

    def __init__(self, service: Any, user_id: str, run_id: str) -> None:
        self.service = service
        self.storage = service._storage
        self.bus = service._message_bus
        self.user_id = user_id
        self.run_id = run_id
        self.token = _generate_id()
        self.claimed = False

    async def snapshot(self) -> SOPRunRecord:
        """Read current state and check this coordinator still owns it."""
        record = await self.storage.get_sop_run(self.user_id, self.run_id)
        if record is None:
            raise KeyError(f"SOP run {self.run_id!r} not found.")
        if self.claimed and record.state.coordinator_token != self.token:
            raise ValueError("Another coordinator took over this run.")
        return record

    async def mutate(
        self, apply: Callable[[SOPRunRecord], Any]
    ) -> SOPRunRecord:
        """Fence stale coordinators inside the state-write lock."""

        def guarded(record: SOPRunRecord) -> Any:
            if self.claimed and record.state.coordinator_token != self.token:
                raise ValueError("Another coordinator took over this run.")
            return apply(record)

        return await self.service.mutate_run(
            self.user_id, self.run_id, guarded
        )

    async def run(self) -> SOPRunState:
        """Drive every ready branch until settled, parked or delayed."""
        from ._sop import _PARKED

        tasks: dict[asyncio.Task, int] = {}
        async with self.bus.acquire_lock(
            MessageBusKeys.sop_coordinator(self.run_id), ttl_secs=60
        ):
            # Any RUNNING record here belongs to a departed coordinator.
            def recover(record: SOPRunRecord) -> None:
                record.state.coordinator_token = self.token
                for node in record.state.steps:
                    if node.phase is SOPPhase.RUNNING:
                        node.generation += (
                            1  # fence late results from the old worker
                        )
                        node.phase = SOPPhase.PENDING
                        if node.submission is None:
                            node.finish_attempt(
                                "interrupted",
                                "Worker stopped before completing the node.",
                            )
                        node.error = "Recovered after worker interruption."

            await self.mutate(recover)
            self.claimed = True
            try:
                while True:
                    record = await self.snapshot()
                    if record.state.cancelled:
                        break
                    by_id = {
                        step.id: index
                        for index, step in enumerate(record.definition.steps)
                    }

                    def block(latest: SOPRunRecord) -> None:
                        # Iterate to a fixed point even when the editor order
                        # differs from the topological order.
                        changed = True
                        while changed:
                            changed = False
                            for index, step in enumerate(
                                latest.definition.steps
                            ):
                                node = latest.state.steps[index]
                                if node.phase is SOPPhase.PENDING and any(
                                    latest.state.steps[by_id[parent]].phase
                                    in (
                                        SOPPhase.FAILED,
                                        SOPPhase.BLOCKED,
                                        SOPPhase.CANCELLED,
                                    )
                                    for parent in step.depends_on
                                ):
                                    node.phase = SOPPhase.BLOCKED
                                    node.error = (
                                        "An upstream node needs attention."
                                    )
                                    changed = True

                    record = await self.mutate(block)
                    active = set(tasks.values())
                    busy = set()
                    for current_index, current_step in enumerate(
                        record.definition.steps
                    ):
                        keys = [current_step.executor.session_key]
                        if isinstance(current_step.verifier, AgentVerifier):
                            keys.append(
                                current_step.verifier.agent.session_key
                            )
                        for key in keys:
                            sid = record.sessions.get(
                                record.definition.session_key(
                                    current_step, key
                                )
                            )
                            if sid and await self.bus.is_locked(
                                MessageBusKeys.session_lock(sid)
                            ):
                                busy.add(current_index)
                                break
                    limit = record.definition.max_concurrency
                    if (
                        record.definition.workspace_grain
                        is SOPWorkspaceGrain.RUN
                    ):
                        limit = 1  # shared mutable files have one writer
                    for index, step in enumerate(record.definition.steps):
                        if len(tasks) >= limit:
                            break
                        node = record.state.steps[index]
                        if (
                            index in active
                            or index in busy
                            or node.phase
                            in (
                                SOPPhase.COMPLETED,
                                SOPPhase.FAILED,
                                SOPPhase.BLOCKED,
                                SOPPhase.CANCELLED,
                            )
                        ):
                            continue
                        if not all(
                            record.state.steps[by_id[parent]].phase
                            is SOPPhase.COMPLETED
                            and by_id[parent] not in active
                            and by_id[parent] not in busy
                            for parent in step.depends_on
                        ):
                            continue
                        if (
                            node.phase is SOPPhase.RETRY_WAIT
                            and (node.retry_at or 0) > time.time()
                        ):
                            continue
                        if node.phase is SOPPhase.AWAITING:
                            if node.wait_reason == "human":
                                continue
                            ref = (
                                step.executor
                                if node.waiting_on == "executor"
                                or (
                                    node.waiting_on is None
                                    and node.submission is None
                                )
                                else getattr(step.verifier, "agent", None)
                            )
                            if ref is None:
                                continue
                            sid = record.sessions.get(
                                record.definition.session_key(
                                    step, ref.session_key
                                )
                            )
                            session = (
                                await self.storage.get_session(
                                    self.user_id, ref.agent_id, sid
                                )
                                if sid
                                else None
                            )
                            if (
                                session
                                and SessionService.derive_parked_status(
                                    session.state.context
                                )
                                in _PARKED
                            ):
                                # Reconstruct a missing dispatch registry after a
                                # bus migration or restart. The session is durable.
                                await self.bus.registry_set(
                                    MessageBusKeys.sop_dispatch(sid),
                                    MessageBusKeys.SOP_DISPATCH_FIELD,
                                    f"{self.run_id}:{node.generation}:{index}",
                                )
                                continue
                        task = asyncio.create_task(
                            self.drive(index),
                            name=f"sop-node:{self.run_id}:{step.id}",
                        )
                        tasks[task] = index
                    if not tasks:
                        return (await self.snapshot()).state
                    done, _ = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in done:
                        tasks.pop(task)
                        await task
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
        return (await self.snapshot()).state

    def inputs(self, record: SOPRunRecord, index: int) -> list[Msg]:
        """Keep global instructions and explicitly bind all upstream outputs."""
        step = record.definition.steps[index]
        by_id = {
            definition.id: node
            for definition, node in zip(
                record.definition.steps, record.state.steps
            )
        }
        given = list(record.state.inputs)
        if record.definition.description:
            given.append(
                UserMsg(
                    name="sop",
                    content=f"Workflow objective: {record.definition.description}",
                )
            )
        for parent in step.depends_on:
            node = by_id[parent]
            given.append(
                UserMsg(
                    name="sop",
                    content=[
                        TextBlock(text=f'<handover node="{parent}">'),
                        *(node.submission or []),
                        TextBlock(
                            text=json.dumps(
                                {"outputs": node.outputs}, ensure_ascii=False
                            )
                        ),
                        TextBlock(text="</handover>"),
                    ],
                )
            )
        bindings = {}
        for name, source in step.input_bindings.items():
            parent, _, path = source.partition(".")
            value = by_id[parent].outputs
            try:
                for part in path.split("."):
                    value = value[part]
            except (KeyError, TypeError) as exc:
                raise ValueError(
                    f"Required input {name!r} is missing from {source!r}."
                ) from exc
            bindings[name] = value
        if bindings:
            given.append(
                UserMsg(
                    name="sop",
                    content="Bound node inputs:\n"
                    + json.dumps(bindings, ensure_ascii=False),
                )
            )
        return given

    async def prepare(self, index: int) -> SOPRunRecord:
        """Create an isolated conversation/workspace for each new attempt."""

        async def apply(record: SOPRunRecord) -> None:
            if record.state.cancelled:
                raise ValueError("This run is cancelled.")
            step, node = (
                record.definition.steps[index],
                record.state.steps[index],
            )
            node.phase = SOPPhase.RUNNING
            node.wait_reason = None
            node.retry_at = None
            if node.submission is None and (
                not node.attempts or node.attempts[-1].ended_at is not None
            ):
                given = self.inputs(record, index)
                attempt = SOPAttempt(
                    number=len(node.attempts) + 1, inputs=given
                )
                node.attempt_id = attempt.id
                node.attempts.append(attempt)
                node.given = given
                workspace_id = _generate_id()
                if record.definition.workspace_grain is SOPWorkspaceGrain.RUN:
                    record.state.workspace_id = (
                        record.state.workspace_id or workspace_id
                    )
                    workspace_id = record.state.workspace_id
                refs = [step.executor]
                if isinstance(step.verifier, AgentVerifier):
                    refs.append(step.verifier.agent)
                created = []
                try:
                    for ref in refs:
                        key = record.definition.session_key(
                            step, ref.session_key
                        )
                        if key in attempt.sessions:
                            continue
                        settings = record.definition.session_settings[
                            ref.session_key
                        ]
                        session = await self.storage.upsert_session(
                            user_id=self.user_id,
                            agent_id=ref.agent_id,
                            config=SessionConfig(
                                workspace_id=_generate_id()
                                if record.definition.workspace_grain
                                is SOPWorkspaceGrain.PER_SESSION_KEY
                                else workspace_id,
                                name=f"{record.definition.name} / {step.subject} / {attempt.number}",
                                chat_model_config=ChatModelConfig(
                                    **settings.chat_model_config
                                ),
                                fallback_chat_model_config=ChatModelConfig(
                                    **settings.fallback_chat_model_config
                                )
                                if settings.fallback_chat_model_config
                                else None,
                            ),
                            state=AgentState(
                                permission_context=PermissionContext(
                                    mode=PermissionMode(
                                        settings.permission_mode
                                    )
                                )
                            ),
                            origin=SOPOrigin(
                                sop_run_id=self.run_id,
                                session_key=key,
                                node_id=step.id,
                                attempt_id=attempt.id,
                            ),
                        )
                        created.append((ref.agent_id, session.id))
                        record.sessions[key] = session.id
                        attempt.sessions[key] = session.id
                except BaseException:
                    for agent, sid in created:
                        await self.storage.delete_session(
                            self.user_id, agent, sid
                        )
                    raise

        return await self.mutate(apply)

    async def stage_artifacts(self, record: SOPRunRecord, index: int) -> None:
        """Copy content-addressed snapshots and verify hashes before use."""
        step, node = record.definition.steps[index], record.state.steps[index]
        reviewing = node.submission is not None
        ref = (
            getattr(step.verifier, "agent", None)
            if reviewing
            else step.executor
        )
        if ref is None:
            return
        by_id = {
            definition.id: state
            for definition, state in zip(
                record.definition.steps, record.state.steps
            )
        }
        artifacts = [
            (parent, artifact)
            for parent in step.depends_on
            for artifact in by_id[parent].artifacts
        ]
        if reviewing:
            artifacts += [(step.id, artifact) for artifact in node.artifacts]
        if not artifacts:
            return
        sid = record.sessions[
            record.definition.session_key(step, ref.session_key)
        ]
        target_session = await self.storage.get_session(
            self.user_id, ref.agent_id, sid
        )
        target = await self.service._workspace_manager.get_workspace(
            self.user_id, ref.agent_id, sid, target_session.config.workspace_id
        )
        target_backend = target.get_backend()
        paths = []
        for parent, artifact in artifacts:
            source = await self.service._workspace_manager.get_workspace(
                self.user_id,
                artifact["agent_id"],
                artifact["session_id"],
                artifact["workspace_id"],
            )
            data = await source.get_backend().read_file(
                artifact["snapshot_path"]
            )
            if hashlib.sha256(data).hexdigest() != artifact["sha256"]:
                raise ValueError(
                    f"Published artifact {artifact['name']!r} changed after submission."
                )
            relative = (
                f"inputs/{parent}/{artifact['sha256'][:12]}-{artifact['name']}"
            )
            await target_backend.write_file(
                target_backend.join_path(target.workdir, relative), data
            )
            paths.append(relative)
        node.given.append(
            UserMsg(
                name="sop",
                content="Published input files in this workspace:\n"
                + "\n".join(paths),
            )
        )

    async def drive(self, index: int) -> None:
        """Drive one attempt, persisting execution and review separately."""
        from ._sop import SessionSOPStep

        record = await self.snapshot()
        definition = record.definition.steps[index]
        node = record.state.steps[index]
        generation = node.generation

        async def persist() -> None:
            def apply(latest: SOPRunRecord) -> None:
                current = latest.state.steps[index]
                if latest.state.cancelled or current.generation != generation:
                    raise ValueError(
                        "This attempt was superseded or cancelled."
                    )
                latest.state.steps[index] = node.model_copy(deep=True)

            await self.mutate(apply)

        try:
            if (
                node.submission is None
                and len(node.verifications) - node.retry_offset
                >= definition.max_attempts
            ):
                node.phase = SOPPhase.FAILED
                await persist()
                return
            record = await self.prepare(index)
            node = record.state.steps[index]
            sessions = {
                ref.session_key: record.sessions[
                    record.definition.session_key(definition, ref.session_key)
                ]
                for ref in [
                    definition.executor,
                    *(
                        [definition.verifier.agent]
                        if isinstance(definition.verifier, AgentVerifier)
                        else []
                    ),
                ]
            }
            step = SessionSOPStep(
                definition,
                index,
                self.user_id,
                self.run_id,
                sessions,
                self.service._chat,
                self.storage,
                self.bus,
                persist,
                generation=generation,
            )
            while True:
                await self.stage_artifacts(record, index)
                before = len(node.verifications)
                async for _ in step.reply_stream(None, node):
                    pass
                if len(node.verifications) > before:
                    if node.verifications[-1].passed:
                        node.phase = SOPPhase.COMPLETED
                        node.error = None
                    else:
                        node.error = node.verifications[-1].message
                        node.outputs, node.artifacts = {}, []
                        if (
                            len(node.verifications) - node.retry_offset
                            >= definition.max_attempts
                        ):
                            node.phase = SOPPhase.FAILED
                        else:
                            node.phase = SOPPhase.RETRY_WAIT
                            node.retry_at = time.time() + min(
                                3600,
                                definition.retry_delay_seconds
                                * 2
                                ** min(
                                    12,
                                    len(node.verifications)
                                    - node.retry_offset
                                    - 1,
                                ),
                            )
                    await persist()
                    return
                await persist()
                if node.phase in (SOPPhase.AWAITING, SOPPhase.FAILED):
                    return
                # The executor handed over. Review in the same attempt.
                record.state.steps[index] = node
        except asyncio.CancelledError:
            # ChatService shields its own checkpoint before propagating this.
            # Read the latest submission so a completed handover is not lost.
            def interrupted(latest: SOPRunRecord) -> None:
                current = latest.state.steps[index]
                if (
                    not latest.state.cancelled
                    and current.generation == generation
                    and current.phase is SOPPhase.RUNNING
                ):
                    current.generation += 1
                    current.phase = SOPPhase.PENDING
                    if current.submission is None:
                        current.finish_attempt(
                            "interrupted",
                            "Worker stopped before completing the node.",
                        )

            await asyncio.shield(self.mutate(interrupted))
            raise
        except Exception as exc:

            def fail(latest: SOPRunRecord) -> None:
                current = latest.state.steps[index]
                if latest.state.cancelled or current.generation != generation:
                    return
                message = str(exc) or type(exc).__name__
                if (
                    not current.attempts
                    or current.attempts[-1].ended_at is not None
                ):
                    attempt = SOPAttempt(
                        number=len(current.attempts) + 1, inputs=current.given
                    )
                    current.attempt_id = attempt.id
                    current.attempts.append(attempt)
                current.verifications.append(
                    VerificationResult(
                        passed=False, message=message, verifier="sop"
                    )
                )
                current.finish_attempt("failed", message)
                current.submission, current.outputs, current.artifacts = (
                    None,
                    {},
                    [],
                )
                current.error = message
                current.wait_reason = None
                exhausted = (
                    len(current.verifications) - current.retry_offset
                    >= definition.max_attempts
                )
                current.phase = (
                    SOPPhase.FAILED if exhausted else SOPPhase.RETRY_WAIT
                )
                current.retry_at = time.time() + definition.retry_delay_seconds

            await self.mutate(fail)
