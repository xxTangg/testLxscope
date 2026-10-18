# -*- coding: utf-8 -*-
"""The tools a SOP step's agent files its handover or verdict with,
straight into the run state."""
from typing import Any, TYPE_CHECKING, AsyncGenerator
from contextlib import asynccontextmanager
import hashlib
import os

from pydantic import Field

from ...message import TextBlock, ToolResultState
from ...permission import (
    PermissionBehavior,
    PermissionContext,
    PermissionDecision,
)
from ...sop import SOPPhase, VerificationResult
from ...tool import ToolBase, ToolChunk, ParamsBase
from ..message_bus import MessageBus, MessageBusKeys

if TYPE_CHECKING:
    from ..storage import StorageBase


class _SubmitHandoverParams(ParamsBase):
    """Parameters for :class:`SubmitHandover`."""

    handover: str = Field(
        description=(
            "What you are handing to the following steps. They cannot "
            "see this conversation or your tools' output, so anything "
            "they need from it has to be in here. Files are the "
            "exception when the procedure shares one workspace: name "
            "those by path rather than describing them."
        ),
    )
    outputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured outputs named by the node's output schema.",
    )
    artifact_paths: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Files to publish, relative to this workspace. Downstream nodes receive verified copies.",
    )


class _SubmitVerdictParams(ParamsBase):
    """Parameters for :class:`SubmitVerdict`."""

    passed: bool = Field(
        description="Whether the work meets what the step had to prove.",
    )
    message: str = Field(
        default="",
        description=(
            "If it does not pass, exactly what is wrong and what to do "
            "about it. This is handed to the author verbatim on their "
            "next attempt, so name the specific claims, files or values "
            "at fault."
        ),
    )


class _SOPSubmitBase(ToolBase):
    """Shared plumbing for the two submission tools, bound to one step
    of one run and writing its state directly."""

    name: str
    description: str
    input_schema: dict[str, Any]
    is_concurrency_safe: bool = False
    is_read_only: bool = False
    is_state_injected: bool = False
    is_external_tool: bool = False
    is_mcp: bool = False
    mcp_name: str | None = None

    def __init__(
        self,
        storage: "StorageBase",
        user_id: str,
        sop_run_id: str,
        step_index: int,
        message_bus: MessageBus | None = None,
        expected_attempt_id: str | None = None,
        expected_generation: int | None = None,
        workspace: Any = None,
        session_record: Any = None,
    ) -> None:
        """Bind the run this tool writes to.

        Args:
            storage (`StorageBase`):
                Application storage.
            user_id (`str`):
                The owner user id.
            sop_run_id (`str`):
                The run the calling session belongs to.
            step_index (`int`):
                Which of the run's steps it is working on.
        """
        self._storage = storage
        self._user_id = user_id
        self._sop_run_id = sop_run_id
        self._step_index = step_index
        self._message_bus = message_bus
        self._expected_attempt_id = expected_attempt_id
        self._expected_generation = expected_generation
        self._workspace = workspace
        self._session_record = session_record

    async def check_permissions(
        self,
        tool_input: dict[str, Any],
        context: PermissionContext,
    ) -> PermissionDecision:
        """Always allow — a step only ever carries the tool it needs.

        Args:
            tool_input (`dict[str, Any]`):
                Ignored.
            context (`PermissionContext`):
                Ignored.

        Returns:
            `PermissionDecision`:
                An ``ALLOW`` decision.
        """
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message=f"{self.name} is how a step reports, so it never asks.",
        )

    async def _write(self, apply: Any) -> ToolChunk | None:
        """Apply *apply* to the step and write the run back; returns an
        error chunk if the run is gone, else ``None``."""

        @asynccontextmanager
        async def unlocked() -> AsyncGenerator[None, None]:
            yield

        lock = (
            self._message_bus.acquire_lock(
                MessageBusKeys.sop_run_lock(self._sop_run_id),
            )
            if self._message_bus
            else unlocked()
        )
        async with lock:
            return await self._write_locked(apply)

    async def _write_locked(self, apply: Any) -> ToolChunk | None:
        """Validate the attempt under the same lock as the state update."""
        record = await self._storage.get_sop_run(
            self._user_id,
            self._sop_run_id,
        )
        if record is None or not 0 <= self._step_index < len(
            record.state.steps
        ):
            return ToolChunk(
                content=[
                    TextBlock(
                        text=(
                            f"{self.name}: run {self._sop_run_id!r} is no "
                            f"longer there to submit to."
                        ),
                    ),
                ],
                state=ToolResultState.ERROR,
            )
        step = record.state.steps[self._step_index]
        if (
            record.state.cancelled
            or (
                self._expected_attempt_id is not None
                and step.attempt_id != self._expected_attempt_id
            )
            or (
                self._expected_generation is not None
                and step.generation != self._expected_generation
            )
        ):
            return ToolChunk(
                content=[
                    TextBlock(text="This node attempt is no longer active.")
                ],
                state=ToolResultState.ERROR,
            )
        try:
            apply(step)
        except ValueError as exc:
            return ToolChunk(
                content=[TextBlock(text=str(exc))], state=ToolResultState.ERROR
            )
        await self._storage.update_sop_run(
            self._user_id,
            self._sop_run_id,
            record.state,
        )
        return None


class SubmitHandover(_SOPSubmitBase):
    """Hand this step's result to the steps that follow it."""

    name: str = "SubmitHandover"
    description: str = """Hand over the result of this step.

## When to Use This Tool
- You have finished what this step had to achieve. Call this as the \
last thing you do — your turn is not over until you have.

## Important
- The steps after this one cannot see your tool output or this \
conversation, so whatever they need from it has to be in the handover \
text itself. Files are the exception when the procedure shares one \
workspace: leave them there and name them by path.
- Calling this does not mean the work is accepted; it is judged after \
you hand it over, and you may be asked again with a reason.
"""

    input_schema: dict = _SubmitHandoverParams.model_json_schema()

    async def __call__(
        self,
        handover: str,
        outputs: dict[str, Any] | None = None,
        artifact_paths: list[str] | None = None,
    ) -> ToolChunk:
        """Record the handover on this step's run state.

        Args:
            handover (`str`):
                What the following steps are told.

        Returns:
            `ToolChunk`:
                A confirmation, or an error if the run has gone.
        """

        outputs = outputs or {}
        record = await self._storage.get_sop_run(
            self._user_id, self._sop_run_id
        )
        if record is not None and 0 <= self._step_index < len(
            record.definition.steps
        ):
            schema = record.definition.steps[self._step_index].output_schema
            if schema is not None:
                from jsonschema import Draft202012Validator

                errors = list(
                    Draft202012Validator(schema).iter_errors(outputs)
                )
                if errors:
                    return ToolChunk(
                        content=[
                            TextBlock(
                                text=f"Output schema validation failed: {errors[0].message}"
                            )
                        ],
                        state=ToolResultState.ERROR,
                    )
        artifacts = []
        total_size = 0
        try:
            for relative in artifact_paths or []:
                if self._workspace is None or self._session_record is None:
                    raise ValueError(
                        "A workspace is required to publish files."
                    )
                relative = relative.replace("\\", "/")
                backend = self._workspace.get_backend()
                if backend.isabs(relative) or ".." in relative.split("/"):
                    raise ValueError(
                        "Artifact paths must stay inside the workspace."
                    )
                path = backend.join_path(self._workspace.workdir, relative)
                if type(backend).__name__ == "LocalBackend":
                    if os.path.commonpath(
                        [
                            os.path.realpath(path),
                            os.path.realpath(self._workspace.workdir),
                        ]
                    ) != os.path.realpath(self._workspace.workdir):
                        raise ValueError(
                            "Artifact symlinks must stay inside the workspace."
                        )
                info = await backend.stat(path)
                if (
                    info is None
                    or info.is_dir
                    or info.size_bytes is None
                    or info.size_bytes + total_size > 32 * 1024 * 1024
                ):
                    raise ValueError(
                        "Publish regular files totaling at most 32 MiB."
                    )
                data = await backend.read_file(path)
                total_size += len(data)
                if total_size > 32 * 1024 * 1024:
                    raise ValueError(
                        "Published files must total at most 32 MiB."
                    )
                digest = hashlib.sha256(data).hexdigest()
                snapshot = backend.join_path(
                    self._workspace.workdir,
                    ".sop-artifacts",
                    digest,
                    os.path.basename(relative),
                )
                await backend.write_file(snapshot, data)
                artifacts.append(
                    {
                        "name": os.path.basename(relative),
                        "sha256": digest,
                        "size": len(data),
                        "snapshot_path": snapshot,
                        "workspace_id": self._session_record.config.workspace_id,
                        "session_id": self._session_record.id,
                        "agent_id": self._session_record.agent_id,
                    }
                )
        except (ValueError, OSError) as exc:
            return ToolChunk(
                content=[TextBlock(text=str(exc))], state=ToolResultState.ERROR
            )

        def _apply(step: Any) -> None:
            if step.submission is not None:
                if (
                    len(step.submission) == 1
                    and getattr(step.submission[0], "text", None) == handover
                    and step.outputs == outputs
                ):
                    return
                raise ValueError("This attempt already has a handover.")
            if step.phase not in (SOPPhase.RUNNING, SOPPhase.AWAITING):
                raise ValueError(
                    "This node is not executing an active attempt."
                )
            step.submission = [TextBlock(type="text", text=handover)]
            step.outputs = outputs
            step.artifacts = artifacts

        failure = await self._write(_apply)
        return failure or ToolChunk(
            content=[TextBlock(type="text", text="Handed over.")],
            state=ToolResultState.SUCCESS,
        )


class SubmitVerdict(_SOPSubmitBase):
    """Accept or refuse the work of the step under review."""

    name: str = "SubmitVerdict"
    description: str = """Decide whether this step's work is accepted.

## When to Use This Tool
- You have read the submission and judged it against what the step had \
to prove. Call this as the last thing you do — your turn is not over \
until you have.

## Important
- A refusal is handed to the author verbatim and is the only thing they \
get to work from, so say what is missing rather than that something is.
- Refusing sends the step back to be attempted again. Do not refuse over \
something the step was never asked to do.
"""

    input_schema: dict = _SubmitVerdictParams.model_json_schema()

    def __init__(self, *args: Any, verifier: str = "", **kwargs: Any) -> None:
        """Bind who the verdict is recorded under.

        Args:
            verifier (`str`, defaults to `""`):
                The reviewing agent's name, recorded on the verdict.
            *args:
                Forwarded to :class:`_SOPSubmitBase`.
            **kwargs:
                Forwarded to :class:`_SOPSubmitBase`.
        """
        super().__init__(*args, **kwargs)
        self._verifier = verifier

    async def __call__(self, passed: bool, message: str = "") -> ToolChunk:
        """File the verdict on this step's current attempt.

        Args:
            passed (`bool`):
                Whether the attempt is accepted.
            message (`str`, defaults to `""`):
                Why it was refused.

        Returns:
            `ToolChunk`:
                A confirmation, or an error if the run has gone.
        """

        def _apply(step: Any) -> None:
            if step.submission is None or step.phase not in (
                SOPPhase.RUNNING,
                SOPPhase.AWAITING,
            ):
                if (
                    step.verifications
                    and step.verifications[-1].passed == passed
                    and step.verifications[-1].message == message
                    and step.verifications[-1].verifier == self._verifier
                ):
                    return
                raise ValueError(
                    "This attempt has no active submission to review."
                )
            step.verifications.append(
                VerificationResult(
                    passed=passed,
                    message=message,
                    verifier=self._verifier,
                ),
            )
            step.finish_attempt(
                "completed" if passed else "rejected", message or None
            )
            if passed:
                step.phase = SOPPhase.COMPLETED
            else:
                # Same rule as ``SOPStepBase.record``.
                step.submission = None
                step.phase = SOPPhase.PENDING
                step.outputs = {}
                step.artifacts = []
            step.wait_reason = None

        failure = await self._write(_apply)
        return failure or ToolChunk(
            content=[
                TextBlock(
                    type="text",
                    text="Accepted." if passed else "Sent back.",
                ),
            ],
            state=ToolResultState.SUCCESS,
        )
