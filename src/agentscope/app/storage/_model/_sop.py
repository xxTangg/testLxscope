# -*- coding: utf-8 -*-
"""The SOP storage classes: a procedure's description, and its runs.
A live :class:`~agentscope.sop.SOP` holds agents, so only this is stored."""
from enum import StrEnum
import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator, field_validator

from ._base import _RecordBase
from ._channel import SessionSettings
from ....sop import SOPRunState


class SOPWorkspaceGrain(StrEnum):
    """How many workspaces a run gets. Always minted for the run, never
    shared with another run."""

    RUN = "run"
    """One for the whole run, so steps can hand files to each other."""

    PER_SESSION_KEY = "per_session_key"
    """One per session, so no step sees another's files."""

    PER_NODE = "per_node"
    """An isolated workspace per node attempt, shared with its reviewer."""


class SOPAgentRef(BaseModel):
    """Which agent does something, and in which conversation."""

    agent_id: str = Field(description="The agent that does the work.")

    session_key: str = Field(
        description=(
            "Which conversation it does it in; references sharing a key "
            "share one session."
        ),
    )


class AgentVerifier(BaseModel):
    """A verifier that is itself an agent."""

    type: Literal["agent"] = "agent"

    agent: SOPAgentRef = Field(description="Who judges the work.")

    criteria: str = Field(
        default="",
        description=(
            "What to hold the work to, beyond the step's own description."
        ),
        json_schema_extra={"format": "textarea"},
    )


class HumanVerifier(BaseModel):
    """A verifier that asks a person and waits for the answer."""

    type: Literal["human"] = "human"

    question: str = Field(
        default="Does this meet what the step had to prove?",
        description="What the person is asked.",
        json_schema_extra={"format": "textarea"},
    )


# Who judges a step: an agent or a person.
SOPVerifier = Annotated[
    Union[AgentVerifier, HumanVerifier],
    Field(discriminator="type"),
]


class SOPStepDataV1(BaseModel):
    """One milestone, as :class:`~agentscope.sop.SOPStep` runs it.
    An incompatible change becomes a new model discriminated on
    :attr:`version`."""

    version: Literal["v1"] = "v1"

    id: str = ""
    """Stable node identifier; legacy steps receive deterministic ids."""

    depends_on: list[str] = Field(default_factory=list)
    input_bindings: dict[str, str] = Field(default_factory=dict)
    """Input name to ``node_id.output_key``; sources must be ancestors."""

    output_schema: dict | None = None
    timeout_seconds: int = Field(default=600, ge=1, le=86400)
    retry_delay_seconds: float = Field(default=2, ge=0, le=3600)

    subject: str = Field(description="A brief, actionable name.")

    description: str = Field(
        description="What this step must achieve — the destination.",
    )

    executor: SOPAgentRef = Field(description="Who does the work.")

    verifier: SOPVerifier | None = Field(
        default=None,
        description="Who judges it. ``None`` accepts whatever comes back.",
    )

    max_attempts: int = Field(
        default=3,
        gt=0,
        description="How many refusals before the run gives up on it.",
    )

    @field_validator("output_schema")
    @classmethod
    def validate_output_schema(cls, schema: dict | None) -> dict | None:
        """Schemas are checked offline; output validation never fetches URLs."""
        if schema is not None:
            from jsonschema import Draft202012Validator, SchemaError

            def check_refs(value: object) -> None:
                if isinstance(value, dict):
                    for key, child in value.items():
                        if (
                            key in ("$ref", "$dynamicRef")
                            and isinstance(child, str)
                            and not child.startswith("#")
                        ):
                            raise ValueError(
                                "Output schemas may use local references only."
                            )
                        check_refs(child)
                elif isinstance(value, list):
                    for child in value:
                        check_refs(child)

            check_refs(schema)
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                raise ValueError(
                    f"Invalid output schema: {exc.message}"
                ) from exc
        return schema


def _session_agents(steps: list[SOPStepDataV1]) -> dict[str, str]:
    """Map each session key the steps name to its agent.

    Raises:
        `ValueError`:
            If one key is used by two different agents.
    """
    agents: dict[str, str] = {}
    for step in steps:
        refs = [step.executor]
        if isinstance(step.verifier, AgentVerifier):
            refs.append(step.verifier.agent)
        for ref in refs:
            if (
                agents.setdefault(ref.session_key, ref.agent_id)
                != ref.agent_id
            ):
                raise ValueError(
                    f"Conversation {ref.session_key!r} is used by more "
                    f"than one agent.",
                )
    return agents


def _parse_sop_dispatch(dispatch: str) -> tuple[str, int, int | None]:
    """Read legacy claims and generation-fenced DAG claims."""
    parts = dispatch.split(":")
    if len(parts) not in (2, 3):
        raise ValueError("Invalid SOP dispatch.")
    return parts[0], int(parts[-1]), int(parts[1]) if len(parts) == 3 else None


class SOPData(BaseModel):
    """A procedure: its milestones, in order."""

    name: str = Field(description="The name of the procedure.")

    execution_mode: Literal["sequential", "dag"] = "sequential"
    max_concurrency: int = Field(default=3, ge=1, le=32)

    description: str = Field(
        default="",
        description="What the procedure is for.",
    )

    steps: list[SOPStepDataV1] = Field(
        min_length=1,
        description="Its milestones, in the order they must happen.",
    )

    workspace_grain: SOPWorkspaceGrain = Field(
        default=SOPWorkspaceGrain.RUN,
        description="How many workspaces a run of this gets.",
    )

    session_settings: dict[str, SessionSettings] = Field(
        default_factory=dict,
        description=(
            "What each conversation is opened with, keyed by session key."
        ),
    )

    @model_validator(mode="after")
    def validate_graph(self) -> "SOPData":
        """Normalize legacy ids and reject ambiguous or cyclic graphs."""
        for index, step in enumerate(self.steps):
            if not step.id:
                step.id = f"step-{index + 1}"
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", step.id):
                raise ValueError(
                    "Node ids must contain 1–128 letters, numbers, underscores or hyphens."
                )
        by_id = {step.id: step for step in self.steps}
        if len(by_id) != len(self.steps):
            raise ValueError("Node ids must be unique.")
        if self.execution_mode == "sequential":
            return self
        visiting, visited = set(), set()

        def visit(node_id: str) -> set[str]:
            if node_id in visiting:
                raise ValueError("The SOP graph contains a cycle.")
            if node_id not in by_id:
                raise ValueError(f"Unknown dependency {node_id!r}.")
            visiting.add(node_id)
            ancestors = set()
            for parent in by_id[node_id].depends_on:
                ancestors.add(parent)
                if parent not in visited:
                    ancestors.update(visit(parent))
                else:
                    ancestors.update(ancestor_map[parent])
            visiting.remove(node_id)
            visited.add(node_id)
            ancestor_map[node_id] = ancestors
            return ancestors

        ancestor_map: dict[str, set[str]] = {}
        for node_id in by_id:
            if node_id not in visited:
                visit(node_id)
        for step in self.steps:
            if (
                isinstance(step.verifier, AgentVerifier)
                and step.executor.session_key
                == step.verifier.agent.session_key
            ):
                raise ValueError(
                    "DAG executor and reviewer must use separate conversation keys."
                )
            if len(set(step.depends_on)) != len(step.depends_on):
                raise ValueError(f"Duplicate dependencies on {step.id!r}.")
            for source in step.input_bindings.values():
                parent, separator, key = source.partition(".")
                if (
                    not separator
                    or not key
                    or parent not in ancestor_map[step.id]
                ):
                    raise ValueError(
                        f"Input source {source!r} must reference an ancestor output."
                    )
        return self

    def dependencies(self, index: int) -> list[str]:
        """Resolved edges, including the implicit legacy chain."""
        if self.execution_mode == "dag":
            return self.steps[index].depends_on
        return [self.steps[index - 1].id] if index else []

    def session_key(self, step: SOPStepDataV1, key: str) -> str:
        """DAG nodes never accidentally share an agent conversation."""
        return f"{step.id}/{key}" if self.execution_mode == "dag" else key


class SOPRecord(_RecordBase):
    """A stored procedure."""

    user_id: str
    """The user id."""

    data: SOPData
    """The procedure."""


class SOPRunRecord(_RecordBase):
    """One run of a procedure."""

    user_id: str
    """The user id."""

    sop_id: str = Field(frozen=True)
    """The :class:`SOPRecord` this run came from. Frozen, since backends
    index runs under it."""

    definition: SOPData
    """A copy of the procedure at start, so editing it cannot strand
    the run."""

    sessions: dict[str, str] = Field(default_factory=dict)
    """The session id for each :attr:`SOPAgentRef.session_key`."""

    state: SOPRunState = Field(default_factory=SOPRunState)
    """How the run is going."""
