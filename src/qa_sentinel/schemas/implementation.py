from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.enums import ImplementationStatus
from qa_sentinel.domain.types import NonBlank


class Deviation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    description: NonBlank
    requires_replan: bool

class ImplementationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    implementation_status: ImplementationStatus
    plan_steps: tuple[NonBlank, ...]
    changed_files: tuple[NonBlank, ...]
    tests_added_or_modified: tuple[NonBlank, ...]
    commands_executed: tuple[NonBlank, ...]
    deviations: tuple[Deviation, ...]
    assumptions: tuple[NonBlank, ...]
    known_issues: tuple[NonBlank, ...]
