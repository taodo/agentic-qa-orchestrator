from pydantic import BaseModel, ConfigDict, StrictInt
from qa_sentinel.domain.enums import ImplementationStatus, ImplementationStepStatus, ChangeType
from qa_sentinel.domain.types import NonBlank


class ImplementationStepResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    step_id: NonBlank
    status: ImplementationStepStatus


class ChangedFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: NonBlank
    change_type: ChangeType
    reason: NonBlank


class ExecutedCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    command: NonBlank
    exit_code: StrictInt


class Deviation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    description: NonBlank
    requires_replan: bool

class ImplementationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    implementation_status: ImplementationStatus
    plan_steps: tuple[ImplementationStepResult, ...]
    changed_files: tuple[ChangedFile, ...]
    tests_added_or_modified: tuple[NonBlank, ...]
    commands_executed: tuple[ExecutedCommand, ...]
    deviations: tuple[Deviation, ...]
    assumptions: tuple[NonBlank, ...]
    known_issues: tuple[NonBlank, ...]
