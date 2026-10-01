from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict
from qa_sentinel.domain.types import NonBlank, Count
from qa_sentinel.domain.enums import ErrorType
from qa_sentinel.schemas.mutation import Sha256, MutationOperation
from qa_sentinel.orchestration.reliability_policy import FailureDisposition


@dataclass(frozen=True)
class MutationConfig:
    workspace_root: Path
    max_source_file_bytes: int = 128 * 1024
    max_source_total_bytes: int = 512 * 1024
    max_source_files: int = 20
    max_result_file_bytes: int = 256 * 1024
    max_total_change_bytes: int = 1024 * 1024
    max_mutations: int = 20
    allow_host_workspace: bool = False

    def __post_init__(self):
        root = Path(self.workspace_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Workspace must be an existing directory")
        host = Path(__file__).resolve().parents[3]
        if not self.allow_host_workspace and (root == host or root.is_relative_to(host) or host.is_relative_to(root)):
            raise ValueError("Host repository mutation requires explicit trusted configuration")
        for name in ("max_source_file_bytes", "max_source_total_bytes", "max_source_files",
                     "max_result_file_bytes", "max_total_change_bytes", "max_mutations"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError("Mutation limits must be positive integers")
        if type(self.allow_host_workspace) is not bool:
            raise ValueError("Host workspace permission must be a boolean")
        object.__setattr__(self, "workspace_root", root)


class PolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    allowed: bool
    reason_code: NonBlank
    reason: NonBlank


class AppliedFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: NonBlank
    operation: MutationOperation
    before_sha256: Sha256 | None
    after_sha256: Sha256
    size_bytes: Count


class ApplicationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    success: bool
    decision: PolicyDecision
    applied: tuple[AppliedFile, ...] = ()
    rollback: Literal["NOT_NEEDED", "SUCCEEDED", "FAILED"] = "NOT_NEEDED"


class MutationFailure(Exception):
    def __init__(self, code, *, application=False):
        super().__init__(code)
        self.code = code
        conflicts = {"STALE_SOURCE", "CREATE_TARGET_EXISTS", "MODIFY_TARGET_MISSING", "SOURCE_LIMIT",
                     "INVALID_ENCODING", "INVALID_FILE_TYPE", "SOURCE_READ_FAILED", "IMPLEMENTATION_GATE_REJECTED",
                     "MUTATION_SERVICE_REQUIRED", "APPLIED_EVIDENCE_MISMATCH"}
        self.error_type = ErrorType.TOOL_ERROR if application else (
            ErrorType.WORKFLOW_ERROR if code in conflicts else ErrorType.POLICY_VIOLATION)
        self.disposition = FailureDisposition.STRUCTURAL if application or code in conflicts else FailureDisposition.TERMINAL


class MutationReconciliationRequired(RuntimeError):
    """Files may have changed; durable invocation must be reconciled before more work."""
