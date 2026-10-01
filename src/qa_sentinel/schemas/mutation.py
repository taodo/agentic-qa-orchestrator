"""Proposed text replacements, never evidence that mutation already happened."""
from enum import StrEnum
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator
from qa_sentinel.domain.enums import ImplementationStatus
from qa_sentinel.domain.types import NonBlank, Count
from .implementation import ImplementationStepResult, Deviation

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class MutationOperation(StrEnum):
    MODIFY = "MODIFY"
    CREATE = "CREATE"


class SourceFileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: NonBlank
    sha256: Sha256
    content: str
    size_bytes: Count


class FileMutation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str = Field(min_length=1, max_length=1024)
    operation: MutationOperation
    expected_sha256: Sha256 | None
    content: str
    reason: NonBlank = Field(max_length=2048)

    @model_validator(mode="after")
    def precondition(self):
        if (self.operation == MutationOperation.MODIFY) != (self.expected_sha256 is not None):
            raise ValueError("MODIFY requires a hash; CREATE requires no hash")
        return self


class ImplementationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    implementation_status: ImplementationStatus
    implementation_summary: NonBlank = Field(max_length=4096)
    plan_steps: tuple[ImplementationStepResult, ...]
    mutations: tuple[FileMutation, ...]
    tests_added_or_modified: tuple[NonBlank, ...]
    assumptions: tuple[NonBlank, ...]
    known_issues: tuple[NonBlank, ...]
    deviations: tuple[Deviation, ...]

    @model_validator(mode="after")
    def no_blocked_writes(self):
        if self.implementation_status != ImplementationStatus.COMPLETED and self.mutations:
            raise ValueError("BLOCKED/FAILED proposals must not contain writes")
        return self
