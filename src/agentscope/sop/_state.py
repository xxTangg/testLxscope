# -*- coding: utf-8 -*-
"""The runtime state of a SOP run — the half worth persisting.

A definition is code and can be run any number of times; a run is plain
data and belongs to exactly one of those times. The engine owns the run
and hands each step the slice that is its own, so nothing about a run
ever lives on a step object.
"""
from enum import StrEnum
from typing import Any
from copy import deepcopy

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializeAsAny,
    computed_field,
)

from ..message import DataBlock, Msg, TextBlock
from .._utils._common import _generate_id, _generate_timestamp


class SOPPhase(StrEnum):
    """Where a step, or a whole run, stands.

    One enum for both: a run is only ever as far along as its steps let
    it be.
    """

    PENDING = "pending"
    """Not started, or sent back to try again."""

    RUNNING = "running"
    """In flight."""

    AWAITING = "awaiting"
    """Parked — someone outside has to answer before it can go on."""

    COMPLETED = "completed"
    """Accepted."""

    FAILED = "failed"
    """Refused until :attr:`~._schema.SOPStepBase.max_attempts` ran out."""

    BLOCKED = "blocked"
    RETRY_WAIT = "retry_wait"
    CANCELLED = "cancelled"


class SOPAttempt(BaseModel):
    """Immutable evidence of each node attempt, retained on local reruns."""

    id: str = Field(default_factory=_generate_id)
    number: int
    started_at: str = Field(default_factory=_generate_timestamp)
    ended_at: str | None = None
    status: str = "running"
    inputs: list[Msg] = Field(default_factory=list)
    submission: list[TextBlock | DataBlock] | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    sessions: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    verdict: dict[str, Any] | None = None


class VerificationResult(BaseModel):
    """One settled verdict on one attempt.

    Only settled verdicts exist — a step with nothing to say yet records
    nothing, because a verdict that has not happened is not a verdict.
    """

    passed: bool
    """Whether the attempt was accepted."""

    message: str = ""
    """Why it was refused. This goes back to the executor verbatim on the
    next attempt, so it has to say what is missing rather than that
    something is."""

    verifier: str = ""
    """Who decided — a model, a person, an external system."""

    created_at: str = Field(default_factory=_generate_timestamp)
    """When the verdict was reached."""


class SOPStepRunState(BaseModel):
    """What one step did in one run.

    The engine writes :attr:`given`; the step keeps the other three
    honest. To remember more, subclass this and name the subclass in
    :attr:`~._schema.SOPStepBase.state_type` — extra fields survive a
    round trip through storage.
    """

    model_config = ConfigDict(extra="allow")

    phase: SOPPhase = SOPPhase.PENDING
    """Where the step stands."""

    node_id: str = ""
    generation: int = 0
    attempt_id: str | None = None
    attempts: list[SOPAttempt] = Field(default_factory=list)
    retry_offset: int = 0
    wait_reason: str | None = None
    waiting_on: str | None = None
    error: str | None = None
    retry_at: float | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)

    def finish_attempt(self, status: str, error: str | None = None) -> None:
        """Keep the draft before a rejection clears the live submission."""
        if (
            self.attempts
            and self.attempts[-1].id == self.attempt_id
            and self.attempts[-1].ended_at is None
        ):
            attempt = self.attempts[-1]
            attempt.status = status
            attempt.ended_at = _generate_timestamp()
            attempt.inputs = deepcopy(self.given)
            attempt.submission = deepcopy(self.submission)
            attempt.outputs = deepcopy(self.outputs)
            attempt.artifacts = deepcopy(self.artifacts)
            attempt.error = error
            if (
                status in ("completed", "rejected", "failed")
                and self.verifications
            ):
                attempt.verdict = self.verifications[-1].model_dump(
                    mode="json"
                )

    given: list[Msg] = Field(default_factory=list)
    """What the engine dispatched this attempt with — the run's inputs
    for the first step, the one before's handover for the rest. Written
    by the engine, read by the step: a verifier judging a draft has to
    see what was asked for, and after a park the answer that resumes the
    attempt is all the step is handed."""

    submission: list[TextBlock | DataBlock] | None = None
    """What the current attempt handed over, once it has.

    Blocks rather than text: a step that produces a chart, a file or an
    image hands it on as readily as a sentence, and the next step reads
    it the same way. ``None`` — as opposed to empty — means the attempt
    has not produced anything yet, which is also how a step tells, on
    resume, that it parked while working rather than while being
    judged."""

    verifications: list[VerificationResult] = Field(default_factory=list)
    """Every settled verdict, oldest first. Its length is the attempt
    count, and its last entry is why the executor is being asked again."""


class SOPRunState(BaseModel):
    """One execution of a SOP, and the whole of what is worth saving.

    It covers the SOP's own state and nothing below it: an executor that
    keeps state of its own (an :class:`~..agent.Agent` does) is persisted
    by whoever built it, the same way it is built.
    """

    id: str = Field(default_factory=_generate_id)
    """The run identifier."""

    inputs: list[Msg] = Field(default_factory=list)
    """What the run was started with, and what its first step reads."""

    steps: list[SerializeAsAny[SOPStepRunState]] = Field(
        default_factory=list,
    )
    """How each step is going, in the order the SOP declares them.

    Serialized as whatever each step actually kept, so the extra a
    :attr:`~._schema.SOPStepBase.state_type` subclass adds is written
    out rather than trimmed back to this base."""

    created_at: str = Field(default_factory=_generate_timestamp)
    """When the run was created."""

    cancelled: bool = False
    workspace_id: str | None = None
    coordinator_token: str | None = None

    @computed_field  # type: ignore[misc]
    @property
    def phase(self) -> SOPPhase:
        """Where the run stands, worked out from its steps.

        Dumped alongside the stored fields so a reader can sort runs
        by it without replaying every step.

        Returns:
            `SOPPhase`:
                How far along the run as a whole is.
        """
        phases = [_.phase for _ in self.steps]
        if self.cancelled:
            return SOPPhase.CANCELLED
        if not phases or all(_ is SOPPhase.PENDING for _ in phases):
            return SOPPhase.PENDING
        if all(_ is SOPPhase.COMPLETED for _ in phases):
            return SOPPhase.COMPLETED
        if any(_ in (SOPPhase.RUNNING, SOPPhase.RETRY_WAIT) for _ in phases):
            return SOPPhase.RUNNING
        if any(_ is SOPPhase.AWAITING for _ in phases):
            return SOPPhase.AWAITING
        if any(_ is SOPPhase.FAILED for _ in phases):
            return SOPPhase.FAILED
        return SOPPhase.RUNNING
