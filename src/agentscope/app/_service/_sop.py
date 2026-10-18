# -*- coding: utf-8 -*-
"""Running a stored procedure, one ``ChatService`` turn per step half.

A step's result is read back from the run state, where its agent's
submit tool wrote it.
"""
import asyncio
import json
import inspect
from typing import Any, AsyncGenerator, Awaitable, Callable, Self

from ..storage import (
    AgentVerifier,
    ChatModelConfig,
    HumanVerifier,
    SessionConfig,
    SOPOrigin,
    SOPRunRecord,
    SOPStepDataV1,
    SOPWorkspaceGrain,
    StorageBase,
)
from ..storage._model._sop import _session_agents
from .._tool import SubmitVerdict
from ..message_bus import MessageBus, MessageBusKeys
from ..workspace_manager import WorkspaceManagerBase
from ..._logging import logger
from ._session import SessionService, SessionStatus
from ...event import (
    ExternalExecutionResultEvent,
    UserConfirmResultEvent,
    UserInterruptEvent,
)
from ...message import Msg, TextBlock, UserMsg
from ..._utils._common import _generate_id
from ...sop import (
    SOP,
    SOPAttempt,
    SOPEngine,
    SOPPhase,
    SOPRunState,
    SOPStepBase,
    SOPStepRunState,
)
from ...permission import PermissionContext, PermissionMode
from ...state import AgentState

_PARKED = (
    SessionStatus.AWAITING_PERMISSION,
    SessionStatus.AWAITING_EXTERNAL_RESULT,
)


class SessionSOPStep(SOPStepBase):
    """One milestone, worked on in ordinary chat sessions.

    One call hands one turn to the executor's or the reviewer's session,
    chosen by whether anything has been handed over yet.
    """

    def __init__(
        self,
        data: SOPStepDataV1,
        index: int,
        user_id: str,
        sop_run_id: str,
        sessions: dict[str, str],
        chat: Any,
        storage: StorageBase,
        message_bus: MessageBus,
        persist: Callable[[], Awaitable[None]],
        generation: int | None = None,
    ) -> None:
        """Bind the step to the run it belongs to.

        Args:
            data (`SOPStepDataV1`):
                The milestone as the procedure describes it.
            index (`int`):
                Its position in the run.
            user_id (`str`):
                The owner user id.
            sop_run_id (`str`):
                The run this step is part of.
            sessions (`dict[str, str]`):
                The run's session ids, by session key.
            chat (`ChatService`):
                Where a turn is actually taken.
            storage (`StorageBase`):
                Application storage.
            message_bus (`MessageBus`):
                Holds the dispatch claim of a parked turn.
            persist (`Callable[[], Awaitable[None]]`):
                Writes the whole run state.
        """
        super().__init__(data.subject, data.description, data.max_attempts)
        self._data = data
        self._index = index
        self._user_id = user_id
        self._sop_run_id = sop_run_id
        self._sessions = sessions
        self._chat = chat
        self._storage = storage
        self._message_bus = message_bus
        self._persist = persist
        self._generation = generation

    async def reply_stream(  # pylint: disable=invalid-overridden-method
        self,
        inputs: Msg
        | list[Msg]
        | UserConfirmResultEvent
        | UserInterruptEvent
        | ExternalExecutionResultEvent
        | None,
        state: SOPStepRunState,
    ) -> AsyncGenerator[Any, None]:
        """Hand one turn to one session and read back what it filed.

        Yields nothing: the agent publishes into its own session.
        """
        for event in ():
            yield event

        verifier = self._data.verifier
        reviewing = state.submission is not None
        if not reviewing:
            ref, opening = self._data.executor, self._brief(state)
        elif verifier is None:
            # A step that only had to happen.
            self.record(state, True)
            return
        elif isinstance(verifier, HumanVerifier):
            # The person's verdict is filed via ``record_verdict``.
            state.phase = SOPPhase.AWAITING
            state.wait_reason = "human"
            state.waiting_on = None
            return
        else:
            ref, opening = verifier.agent, self._question(state, verifier)

        session_id = self._sessions[ref.session_key]
        if state.phase is SOPPhase.AWAITING:
            # Still parked on a tool call, which a new brief can't answer.
            session = await self._storage.get_session(
                self._user_id,
                ref.agent_id,
                session_id,
            )
            if session is not None and (
                SessionService.derive_parked_status(session.state.context)
                in _PARKED
            ):
                return

        state.phase = SOPPhase.RUNNING
        state.wait_reason = None
        state.waiting_on = None
        if not reviewing and (
            not state.attempts or state.attempts[-1].ended_at is not None
        ):
            attempt = SOPAttempt(
                number=len(state.attempts) + 1,
                inputs=state.given,
                sessions=dict(self._sessions),
            )
            state.attempt_id = attempt.id
            state.attempts.append(attempt)
        # Before the turn, since its submit tool reads the stored state.
        await self._persist()

        dispatch = f"{self._sop_run_id}:{self._index}"
        if self._generation is not None:
            dispatch = f"{self._sop_run_id}:{self._generation}:{self._index}"
        try:
            async with asyncio.timeout(self._data.timeout_seconds):
                await self._chat.run(
                    self._user_id,
                    session_id,
                    ref.agent_id,
                    opening,
                    sop_dispatch=dispatch,
                )

            stored = await self._storage.get_sop_run(
                self._user_id,
                self._sop_run_id,
            )
            if stored is None:
                # Deleted mid-turn; nothing left to record against.
                state.phase = SOPPhase.FAILED
                return
            filed = stored.state.steps[self._index]
            state.submission = filed.submission
            state.outputs = filed.outputs
            state.artifacts = filed.artifacts
            state.attempts = filed.attempts
            verdicts = list(filed.verifications)

            if len(verdicts) > len(state.verifications):
                state.verifications = verdicts
                if verdicts[-1].passed:
                    state.phase = SOPPhase.COMPLETED
                else:
                    state.submission = None
                    state.phase = SOPPhase.PENDING
                return

            if not reviewing and state.submission is not None:
                # Handed over; the same step is judged on the next pass.
                state.phase = SOPPhase.RUNNING
                return

            session = await self._storage.get_session(
                self._user_id,
                ref.agent_id,
                session_id,
            )
            if session is not None and (
                SessionService.derive_parked_status(session.state.context)
                in _PARKED
            ):
                state.phase = SOPPhase.AWAITING
                state.wait_reason = "tool"
                state.waiting_on = "verifier" if reviewing else "executor"
                return

            self.record(
                state,
                False,
                "The reviewer ended its turn without a verdict."
                if reviewing
                else "Your turn ended without submitting anything, so the "
                "step has nothing to show for it.",
                "sop",
            )
        except TimeoutError:
            self.record(
                state,
                False,
                f"Node exceeded its {self._data.timeout_seconds}s timeout.",
                "sop",
            )
            state.error = "Node execution timed out."
        finally:
            # A parked turn keeps its claim for the chat turn that
            # resumes it; any other ending releases the session.
            if state.phase is SOPPhase.AWAITING:
                await self._message_bus.registry_set(
                    MessageBusKeys.sop_dispatch(session_id),
                    MessageBusKeys.SOP_DISPATCH_FIELD,
                    dispatch,
                )
            else:
                await self._message_bus.registry_drop(
                    MessageBusKeys.sop_dispatch(session_id),
                )

    def _brief(self, state: SOPStepRunState) -> list[Msg]:
        """What the author is asked at the start of an attempt."""
        text = (
            f"<system-reminder>You are running one step of the SOP.\n\n"
            f"## {self.subject}\n\n{self.description}\n"
        )
        if state.verifications:
            text += (
                f"\nYour last attempt was not accepted:\n"
                f"{state.verifications[-1].message}\n"
            )
        text += "</system-reminder>"
        if self._data.output_schema:
            text += (
                "\nSubmitHandover.outputs must match this JSON Schema:\n"
                + json.dumps(self._data.output_schema, ensure_ascii=False)
            )
        text += "\nPublish any files needed downstream with SubmitHandover.artifact_paths."
        return [UserMsg(name="sop", content=text), *state.given]

    def _question(
        self,
        state: SOPStepRunState,
        verifier: AgentVerifier,
    ) -> list[Msg]:
        """What the reviewer is asked, once there is something to judge."""
        text = (
            f"<system-reminder>Judge the work below against what this "
            f"step had to prove.\n\n## {self.subject}\n\n{self.description}"
        )
        if verifier.criteria:
            text += f"\n\n{verifier.criteria}"
        return [
            UserMsg(name="sop", content=text + "</system-reminder>"),
            *state.given,
            UserMsg(
                name="sop",
                content=[
                    TextBlock(type="text", text="<submission>"),
                    *(state.submission or []),
                    TextBlock(
                        type="text",
                        text=json.dumps(
                            {
                                "outputs": state.outputs,
                                "artifacts": state.artifacts,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                    TextBlock(type="text", text="</submission>"),
                ],
            ),
        ]


class SOPService:
    """Start runs of a stored procedure, and carry them forward.

    Enter it as a context manager so detached advances are cancelled
    before storage closes.
    """

    def __init__(
        self,
        storage: StorageBase,
        workspace_manager: WorkspaceManagerBase,
        message_bus: MessageBus,
        chat: Any,
        session_service: SessionService,
    ) -> None:
        """Initialize the service.

        Args:
            storage (`StorageBase`):
                Application storage.
            workspace_manager (`WorkspaceManagerBase`):
                Closes the workspaces a deleted run minted.
            message_bus (`MessageBus`):
                Serialises advances of one run against each other.
            chat (`ChatService`):
                Where each step's turn is taken.
            session_service (`SessionService`):
                Deletes a run's sessions.
        """
        self._storage = storage
        self._workspace_manager = workspace_manager
        self._message_bus = message_bus
        self._chat = chat
        self._session_service = session_service
        # Strong refs to detached advances, by run, so a delete can
        # cancel them.
        self._advancing: dict[str, set[asyncio.Task]] = {}
        self._recovery_task: asyncio.Task | None = None

    async def create_run(
        self,
        user_id: str,
        sop_id: str,
        inputs: list[Msg] | None = None,
    ) -> SOPRunRecord:
        """Open a run with all of its sessions created up front.

        Args:
            user_id (`str`):
                The owner user id.
            sop_id (`str`):
                The procedure to run, copied into the run.
            inputs (`list[Msg] | None`, optional):
                What the first step is given.

        Returns:
            `SOPRunRecord`:
                The opened run, already persisted.

        Raises:
            `KeyError`:
                If the user has no such procedure.
        """
        async with self._message_bus.acquire_lock(
            MessageBusKeys.sop_lock(sop_id),
            ttl_secs=MessageBusKeys.SOP_RUN_TTL_SECS,
        ):
            return await self._open_run(user_id, sop_id, inputs)

    async def _open_run(
        self,
        user_id: str,
        sop_id: str,
        inputs: list[Msg] | None,
    ) -> SOPRunRecord:
        """Open the run, with the procedure's lock already held."""
        sop_record = await self._storage.get_sop(user_id, sop_id)
        if sop_record is None:
            raise KeyError(f"SOP {sop_id!r} not found.")
        data = sop_record.data
        run = SOPRunRecord(
            user_id=user_id,
            sop_id=sop_record.id,
            definition=data,
            state=SOPRunState(
                inputs=inputs or [],
                steps=[
                    SOPStepRunState(node_id=step.id) for step in data.steps
                ],
            ),
        )

        if data.execution_mode == "dag":
            return await self._storage.upsert_sop_run(user_id, run)

        agents = _session_agents(data.steps)

        # Minted rather than assigned: ``assign_workspace_id`` may reuse
        # the agent's workspace across runs, breaking the grain.
        shared = _generate_id()
        run.state.workspace_id = shared
        try:
            for key, agent_id in agents.items():
                settings = data.session_settings[key]
                fallback = settings.fallback_chat_model_config
                workspace_id = (
                    shared
                    if data.workspace_grain is SOPWorkspaceGrain.RUN
                    else _generate_id()
                )
                session = await self._storage.upsert_session(
                    user_id=user_id,
                    agent_id=agent_id,
                    config=SessionConfig(
                        workspace_id=workspace_id,
                        name=f"{data.name} / {key}",
                        chat_model_config=ChatModelConfig(
                            **settings.chat_model_config,
                        ),
                        fallback_chat_model_config=(
                            ChatModelConfig(**fallback) if fallback else None
                        ),
                    ),
                    state=AgentState(
                        permission_context=PermissionContext(
                            mode=PermissionMode(settings.permission_mode),
                        ),
                    ),
                    origin=SOPOrigin(sop_run_id=run.id, session_key=key),
                )
                run.sessions[key] = session.id

            return await self._storage.upsert_sop_run(user_id, run)
        except Exception:
            # Unreachable without the run record, so roll them back.
            for key, session_id in run.sessions.items():
                await self._storage.delete_session(
                    user_id,
                    agents[key],
                    session_id,
                )
            raise

    async def __aenter__(self) -> Self:
        """Enter the service's lifetime."""
        self._recovery_task = asyncio.create_task(
            self._recover_loop(), name="sop-recovery"
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        """Stop every advance still going, before its storage closes."""
        if self._recovery_task:
            self._recovery_task.cancel()
            await asyncio.gather(self._recovery_task, return_exceptions=True)
        going = [task for tasks in self._advancing.values() for task in tasks]
        for task in going:
            task.cancel()
        await asyncio.gather(*going, return_exceptions=True)
        self._advancing.clear()

    def advance_later(self, user_id: str, sop_run_id: str) -> None:
        """Advance a run in a detached task; failures are logged.

        Args:
            user_id (`str`):
                The owner user id.
            sop_run_id (`str`):
                The run to carry on.
        """

        if self._advancing.get(sop_run_id):
            return

        async def _run() -> None:
            try:
                await self.run(user_id, sop_run_id)
            except Exception:  # pylint: disable=broad-except
                logger.exception(
                    "Advancing SOP run %r failed.",
                    sop_run_id,
                )

        task = asyncio.create_task(_run(), name=f"sop-run:{sop_run_id}")
        going = self._advancing.setdefault(sop_run_id, set())
        going.add(task)
        task.add_done_callback(going.discard)

    async def _recover_loop(self) -> None:
        """Persisted node states are the queue; rebuilding it loses no ack."""
        while True:
            await asyncio.sleep(5)
            try:
                await self.recover()
            except Exception:
                logger.exception(
                    "SOP recovery scan failed; retrying on the next tick."
                )

    async def recover(self) -> None:
        """Schedule unfinished runs after a process restart or missed wakeup."""
        for record in await self._storage.list_recoverable_sop_runs():
            if record.state.cancelled:
                continue
            if not any(
                step.phase
                in (SOPPhase.PENDING, SOPPhase.RUNNING, SOPPhase.RETRY_WAIT)
                or (
                    step.phase is SOPPhase.AWAITING
                    and step.wait_reason != "human"
                    and (step.wait_reason == "tool" or step.submission is None)
                )
                for step in record.state.steps
            ):
                continue
            key = (
                MessageBusKeys.sop_coordinator(record.id)
                if record.definition.execution_mode == "dag"
                else MessageBusKeys.sop_run_lock(record.id)
            )
            if record.definition.execution_mode == "sequential" and any(
                [
                    await self._message_bus.is_locked(
                        MessageBusKeys.session_lock(sid)
                    )
                    for sid in record.sessions.values()
                ]
            ):
                continue
            if not await self._message_bus.is_locked(key):
                self.advance_later(record.user_id, record.id)

    async def mutate_run(
        self, user_id: str, run_id: str, apply: Any
    ) -> SOPRunRecord:
        """Serialize short, latest-record mutations across DAG node workers."""
        async with self._message_bus.acquire_lock(
            MessageBusKeys.sop_run_lock(run_id)
        ):
            record = await self._storage.get_sop_run(user_id, run_id)
            if record is None:
                raise KeyError(f"SOP run {run_id!r} not found.")
            result = apply(record)
            if inspect.isawaitable(result):
                await result
            return await self._storage.upsert_sop_run(user_id, record)

    async def delete_sop(self, user_id: str, sop_id: str) -> bool:
        """Delete a procedure and every run of it.

        Under the procedure's lock, so no run is opened mid-cascade.

        Args:
            user_id (`str`):
                The owner user id.
            sop_id (`str`):
                The procedure to delete.

        Returns:
            `bool`:
                Whether there was one to delete.
        """
        async with self._message_bus.acquire_lock(
            MessageBusKeys.sop_lock(sop_id),
            ttl_secs=MessageBusKeys.SOP_RUN_TTL_SECS,
        ):
            for run in await self._storage.list_sop_runs(
                user_id,
                sop_id=sop_id,
            ):
                await self.delete_run(user_id, run.id)
            return await self._storage.delete_sop(user_id, sop_id)

    async def delete_run(self, user_id: str, sop_run_id: str) -> bool:
        """Delete a run, its sessions, claims and workspaces.

        Local advances are cancelled first, then the rest runs under the
        run's lock so no advance writes the record back afterwards.

        Args:
            user_id (`str`):
                The owner user id.
            sop_run_id (`str`):
                The run to delete.

        Returns:
            `bool`:
                Whether there was one to delete.
        """
        if await self._storage.get_sop_run(user_id, sop_run_id) is None:
            return False
        going = list(self._advancing.get(sop_run_id, ()))
        for task in going:
            task.cancel()
        await asyncio.gather(*going, return_exceptions=True)
        async with self._message_bus.acquire_lock(
            MessageBusKeys.sop_run_lock(sop_run_id),
            ttl_secs=MessageBusKeys.SOP_RUN_TTL_SECS,
        ):
            record = await self._storage.get_sop_run(user_id, sop_run_id)
            if record is None:
                return False
            agents = _session_agents(record.definition.steps)
            if record.definition.execution_mode == "dag":
                agents = {
                    record.definition.session_key(step, key): agent
                    for step in record.definition.steps
                    for key, agent in _session_agents([step]).items()
                }
            workspace_ids = set()
            session_pairs = {
                (agents[key], session_id)
                for key, session_id in record.sessions.items()
            }
            for node in record.state.steps:
                for attempt in node.attempts:
                    for key, session_id in attempt.sessions.items():
                        if key in agents:
                            session_pairs.add((agents[key], session_id))
            for agent_id, session_id in session_pairs:
                session = await self._storage.get_session(
                    user_id,
                    agent_id,
                    session_id,
                )
                if session is not None:
                    workspace_ids.add(session.config.workspace_id)
                # Via the session service, to also cancel and purge.
                await self._session_service.delete_session(
                    user_id,
                    agent_id,
                    session_id,
                )
                await self._message_bus.registry_drop(
                    MessageBusKeys.sop_dispatch(session_id),
                )
            deleted = await self._storage.delete_sop_run(user_id, sop_run_id)
        # Minted for this run alone, so nobody else closes them.
        for workspace_id in workspace_ids:
            await self._workspace_manager.close(workspace_id)
        return deleted

    async def record_verdict(
        self,
        user_id: str,
        sop_run_id: str,
        step_index: int,
        passed: bool,
        message: str = "",
        expected_attempt_id: str | None = None,
    ) -> SOPRunRecord:
        """File a person's verdict on a step waiting for one.

        Under the run's lock, so an advance cannot overwrite it.

        Args:
            user_id (`str`):
                The owner user id.
            sop_run_id (`str`):
                The run being judged.
            step_index (`int`):
                Which step, by its position.
            passed (`bool`):
                Whether the attempt is accepted.
            message (`str`, defaults to `""`):
                Why it was refused.

        Returns:
            `SOPRunRecord`:
                The run with the verdict recorded on it.

        Raises:
            `KeyError`:
                If the user has no such run, or it has no such step.
            `ValueError`:
                If that step is not judged by a person, or not waiting.
        """
        async with self._message_bus.acquire_lock(
            MessageBusKeys.sop_run_lock(sop_run_id),
            ttl_secs=MessageBusKeys.SOP_RUN_TTL_SECS,
        ):
            record = await self._storage.get_sop_run(user_id, sop_run_id)
            if record is None:
                raise KeyError(f"SOP run {sop_run_id!r} not found.")
            if not 0 <= step_index < len(record.definition.steps):
                raise KeyError(
                    f"Step {step_index} is not part of this run.",
                )
            step = record.definition.steps[step_index]
            if not isinstance(step.verifier, HumanVerifier):
                raise ValueError(
                    f"Step {step_index} is not judged by a person.",
                )
            if record.state.steps[step_index].phase is not SOPPhase.AWAITING:
                raise ValueError(
                    f"Step {step_index} is not waiting to be judged.",
                )
            node = record.state.steps[step_index]
            if node.submission is None or node.wait_reason not in (
                None,
                "human",
            ):
                raise ValueError(
                    "This node is waiting for a tool, not a human verdict."
                )
            if (
                record.definition.execution_mode == "dag"
                and expected_attempt_id != node.attempt_id
            ):
                raise ValueError(
                    "The submission changed; refresh before reviewing it."
                )

            # The same tool an agent reviewer calls.
            result = await SubmitVerdict(
                storage=self._storage,
                user_id=user_id,
                sop_run_id=sop_run_id,
                step_index=step_index,
                verifier=user_id,
            )(passed=passed, message=message)
            from ...message import ToolResultState

            if result.state == ToolResultState.ERROR:
                raise ValueError(str(result.content))

            updated = await self._storage.get_sop_run(user_id, sop_run_id)

        if updated is None:
            raise KeyError(f"SOP run {sop_run_id!r} not found.")
        return updated

    async def retry_node(
        self,
        user_id: str,
        run_id: str,
        node_id: str,
        *,
        include_descendants: bool = False,
        expected_generation: int | None = None,
    ) -> SOPRunRecord:
        """Retry within the same run; invalidate only dependent results."""

        def apply(record: SOPRunRecord) -> None:
            if record.state.cancelled:
                raise ValueError("Cancelled runs cannot be retried.")
            by_id = {
                step.id: index
                for index, step in enumerate(record.definition.steps)
            }
            if node_id not in by_id:
                raise KeyError(f"Node {node_id!r} not found.")
            target = record.state.steps[by_id[node_id]]
            if (
                expected_generation is not None
                and target.generation != expected_generation
            ):
                raise ValueError("The node changed; refresh before retrying.")
            if target.phase not in (
                SOPPhase.FAILED,
                SOPPhase.COMPLETED,
                SOPPhase.AWAITING,
            ):
                raise ValueError(
                    "Only failed, completed or parked nodes can be retried."
                )
            descendants = set()
            changed = True
            while changed:
                changed = False
                for index, step in enumerate(record.definition.steps):
                    if (
                        step.id not in descendants
                        and step.id != node_id
                        and any(
                            parent in descendants or parent == node_id
                            for parent in record.definition.dependencies(index)
                        )
                    ):
                        descendants.add(step.id)
                        changed = True
            if not include_descendants and any(
                record.state.steps[by_id[key]].phase
                in (SOPPhase.COMPLETED, SOPPhase.AWAITING)
                for key in descendants
            ):
                raise ValueError(
                    "Downstream results exist; choose rerun node and descendants."
                )
            affected = {node_id} | descendants
            if any(
                record.state.steps[by_id[key]].phase is SOPPhase.RUNNING
                for key in affected
            ):
                raise ValueError(
                    "Wait for affected running nodes to stop before rerunning them."
                )
            for key in affected:
                node = record.state.steps[by_id[key]]
                if (
                    key != node_id
                    and not include_descendants
                    and node.phase not in (SOPPhase.BLOCKED, SOPPhase.PENDING)
                ):
                    continue
                node.finish_attempt(
                    "superseded", "A node or upstream result was rerun."
                )
                node.generation += 1
                node.phase = SOPPhase.PENDING
                node.retry_offset = len(node.verifications)
                node.attempt_id = None
                node.submission, node.outputs, node.artifacts = None, {}, []
                node.given = []
                node.error, node.wait_reason, node.retry_at = None, None, None
                node.waiting_on = None

        record = await self.mutate_run(user_id, run_id, apply)
        self.advance_later(user_id, run_id)
        return record

    async def resume_run(self, user_id: str, run_id: str) -> SOPRunRecord:
        """Rebuild the ready queue, preserving successful node outputs."""
        record = await self._storage.get_sop_run(user_id, run_id)
        if record is None:
            raise KeyError(f"SOP run {run_id!r} not found.")
        if record.state.cancelled:
            raise ValueError("This run was cancelled.")
        if record.definition.execution_mode == "sequential" and any(
            [
                await self._message_bus.is_locked(
                    MessageBusKeys.session_lock(sid)
                )
                for sid in record.sessions.values()
            ]
        ):
            raise ValueError("A node conversation is still running.")
        self.advance_later(user_id, run_id)
        return record

    async def cancel_run(self, user_id: str, run_id: str) -> SOPRunRecord:
        """Fence future writes before stopping the coordinator and its workers."""

        owned = await self._storage.get_sop_run(user_id, run_id)
        if owned is None:
            raise KeyError(f"SOP run {run_id!r} not found.")
        if owned.definition.execution_mode == "sequential":
            going = list(self._advancing.get(run_id, ()))
            for task in going:
                task.cancel()
            await asyncio.gather(*going, return_exceptions=True)

        def apply(record: SOPRunRecord) -> None:
            record.state.cancelled = True
            for node in record.state.steps:
                if node.phase not in (SOPPhase.COMPLETED, SOPPhase.FAILED):
                    node.finish_attempt("cancelled", "Cancelled by the owner.")
                    node.phase = SOPPhase.CANCELLED
                    node.generation += 1

        record = await self.mutate_run(user_id, run_id, apply)
        going = list(self._advancing.get(run_id, ()))
        for task in going:
            task.cancel()
        await asyncio.gather(*going, return_exceptions=True)
        return record

    async def run(self, user_id: str, sop_run_id: str) -> SOPRunState:
        """Carry a run on until it finishes, fails, or waits on someone.

        Args:
            user_id (`str`):
                The owner user id.
            sop_run_id (`str`):
                The run to drive.

        Returns:
            `SOPRunState`:
                How the run stands now.

        Raises:
            `KeyError`:
                If the user has no such run.
        """
        record = await self._storage.get_sop_run(user_id, sop_run_id)
        if record is not None and record.definition.execution_mode == "dag":
            from ._sop_dag import SOPDAGRunner

            return await SOPDAGRunner(self, user_id, sop_run_id).run()
        async with self._message_bus.acquire_lock(
            MessageBusKeys.sop_run_lock(sop_run_id),
            ttl_secs=MessageBusKeys.SOP_RUN_TTL_SECS,
        ):
            return await self._advance(user_id, sop_run_id)

    async def _advance(self, user_id: str, sop_run_id: str) -> SOPRunState:
        """Drive the run, with its lock already held."""
        record = await self._storage.get_sop_run(user_id, sop_run_id)
        if record is None:
            raise KeyError(f"SOP run {sop_run_id!r} not found.")

        state = record.state
        if state.cancelled:
            return state

        async def _persist() -> None:
            await self._storage.update_sop_run(user_id, sop_run_id, state)

        engine = SOPEngine(
            SOP(
                name=record.definition.name,
                description=record.definition.description,
                steps=[
                    SessionSOPStep(
                        data=step,
                        index=index,
                        user_id=user_id,
                        sop_run_id=sop_run_id,
                        sessions=record.sessions,
                        chat=self._chat,
                        storage=self._storage,
                        message_bus=self._message_bus,
                        persist=_persist,
                    )
                    for index, step in enumerate(record.definition.steps)
                ],
            ),
            state,
        )
        async for _ in engine.reply_stream():
            pass
        await _persist()
        return engine.state
