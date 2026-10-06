"""Derived crash safety. No execution, evidence repair, or persisted recovery state."""
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID
from pydantic import Field, ValidationError
from qa_sentinel.agents.base import ARTIFACT_TYPES, OUTPUT_TYPES, STATE_AGENTS
from qa_sentinel.domain.enums import TaskState, AgentName, ArtifactType
from qa_sentinel.domain.execution_job import ExecutionJobError
from qa_sentinel.domain.execution_job import ExecutionJob
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.invocation import AgentInvocation
from qa_sentinel.domain.artifact import Artifact
from qa_sentinel.domain.event import Event
from qa_sentinel.domain.test_run import TestRun
from qa_sentinel.domain.error import ErrorRecord
from qa_sentinel.mutation.contracts import ApplicationResult, MutationFailure
from qa_sentinel.projects import ProjectWorkspaceGuard, ProjectBindingError
from qa_sentinel.orchestration.state_machine import TERMINAL_STATES, can_transition
from .models import View


class ReconciliationStatus(StrEnum):
    CLEAR = "CLEAR"
    RECOVERABLE = "RECOVERABLE"
    MANUAL_ACTION_REQUIRED = "MANUAL_ACTION_REQUIRED"
    INCONSISTENT = "INCONSISTENT"


class ReconciliationIssueKind(StrEnum):
    EXECUTION_JOB_INTERRUPTED = "EXECUTION_JOB_INTERRUPTED"
    AGENT_INVOCATION_PENDING = "AGENT_INVOCATION_PENDING"
    PROVIDER_CALL_UNCERTAIN = "PROVIDER_CALL_UNCERTAIN"
    IMPLEMENTATION_MUTATION_UNCERTAIN = "IMPLEMENTATION_MUTATION_UNCERTAIN"
    TEST_EXECUTION_PENDING = "TEST_EXECUTION_PENDING"
    WORKSPACE_DRIFT = "WORKSPACE_DRIFT"
    EVIDENCE_INCONSISTENT = "EVIDENCE_INCONSISTENT"


class ReconciliationSeverity(StrEnum):
    INFO = "INFO"
    BLOCKING = "BLOCKING"


GUIDANCE = {
    ReconciliationIssueKind.EXECUTION_JOB_INTERRUPTED: (
        "An execution request was interrupted; core evidence is assessed separately.",
        "Inspect Task state and this assessment before explicitly continuing."),
    ReconciliationIssueKind.AGENT_INVOCATION_PENDING: (
        "An agent invocation has no durable final outcome.",
        "Inspect the invocation and its evidence with the trusted operator. Do not clear STARTED or retry blindly."),
    ReconciliationIssueKind.PROVIDER_CALL_UNCERTAIN: (
        "A model request lacks a provable durable outcome.",
        "Inspect provider-side outcome privately. Do not replay a possibly completed request."),
    ReconciliationIssueKind.IMPLEMENTATION_MUTATION_UNCERTAIN: (
        "Mutation evidence does not prove a safe final workspace outcome.",
        "Inspect the authorized workspace and durable mutation evidence. Do not reapply or roll back automatically."),
    ReconciliationIssueKind.TEST_EXECUTION_PENDING: (
        "A test execution started but has no durable TestRun.",
        "Inspect the trusted workspace and process outcome before continuing. Do not rerun uncertain pytest."),
    ReconciliationIssueKind.WORKSPACE_DRIFT: (
        "Workspace identity or recorded applied hashes do not verify.",
        "Inspect the trusted binding and explicit applied files privately. Do not repair source automatically."),
    ReconciliationIssueKind.EVIDENCE_INCONSISTENT: (
        "Durable evidence linkage or lifecycle is inconsistent.",
        "Have the trusted operator inspect the referenced records. Do not fabricate completion or bypass gates."),
}


class ReconciliationIssueView(View):
    kind: ReconciliationIssueKind
    severity: ReconciliationSeverity
    summary: str = Field(max_length=160)
    evidence_refs: tuple[str, ...] = Field(max_length=8)
    operator_action: str = Field(max_length=240)


class ReconciliationAssessmentView(View):
    task_id: UUID
    status: ReconciliationStatus
    safe_to_run: bool
    safe_to_resume: bool
    issues: tuple[ReconciliationIssueView, ...] = Field(max_length=100)


@dataclass(frozen=True)
class ReconciliationEvidence:
    task: Task
    invocations: tuple[AgentInvocation, ...]
    artifacts: tuple[Artifact, ...]
    events: tuple[Event, ...]
    test_runs: tuple[TestRun, ...]
    errors: tuple[ErrorRecord, ...]
    jobs: tuple[ExecutionJob, ...]


def assess(evidence: ReconciliationEvidence, bundle) -> ReconciliationAssessmentView:
    """Inspect detached records; only accepted bounded workspace verification may read files."""
    task = evidence.task
    invocations = {i.id: i for i in evidence.invocations}
    artifacts = {a.id: a for a in evidence.artifacts}
    runs = {r.id: r for r in evidence.test_runs}
    errors = {e.id: e for e in evidence.errors}
    issues = []
    inconsistent = False
    recoverable = False
    overflow = False

    def add(kind, *records, severity=ReconciliationSeverity.BLOCKING):
        nonlocal inconsistent, overflow
        if kind == ReconciliationIssueKind.EVIDENCE_INCONSISTENT:
            inconsistent = True
        summary, action = GUIDANCE[kind]
        refs = tuple(str(r.id) for r in records if r is not None)[:8]
        issue = ReconciliationIssueView(kind=kind, severity=severity, summary=summary,
            evidence_refs=refs, operator_action=action)
        if issue not in issues:
            if len(issues) < 99:
                issues.append(issue)
            else:
                overflow = True

    K = ReconciliationIssueKind
    current = invocations.get(task.current_invocation_id)
    if task.current_invocation_id is not None and current is None:
        add(K.EVIDENCE_INCONSISTENT)
    canonical = {}
    for artifact in evidence.artifacts:
        if artifact.invocation_id is not None and artifact.invocation_id not in invocations:
            add(K.EVIDENCE_INCONSISTENT, artifact)
        if artifact.artifact_type not in ARTIFACT_TYPES.values():
            continue
        invocation = invocations.get(artifact.invocation_id)
        if (invocation is None or ARTIFACT_TYPES[invocation.agent] != artifact.artifact_type or
            artifact.producer_agent != invocation.agent or artifact.producer_model != invocation.model):
            add(K.EVIDENCE_INCONSISTENT, artifact, invocation)
            continue
        canonical.setdefault(invocation.id, []).append(artifact)
        try:
            OUTPUT_TYPES[invocation.agent].model_validate(artifact.content)
        except (ValidationError, ValueError, TypeError):
            add(K.EVIDENCE_INCONSISTENT, artifact, invocation)
        if invocation.status.value != "COMPLETED":
            add(K.EVIDENCE_INCONSISTENT, artifact, invocation)

    seen_attempts = set()
    for invocation in evidence.invocations:
        key = (invocation.agent, invocation.attempt)
        if key in seen_attempts or invocation.task_id != task.id:
            add(K.EVIDENCE_INCONSISTENT, invocation)
        seen_attempts.add(key)
        outputs = canonical.get(invocation.id, [])
        related = [e for e in evidence.events if e.correlation.invocation_id == invocation.id]
        if invocation.status.value == "STARTED":
            add(K.AGENT_INVOCATION_PENDING, invocation)
            # Reasoning-only roles use STARTED as the only durable call reservation.
            # A reserved validated mutation proposal proves a response was retained,
            # while repository roles have explicit per-turn evidence below.
            if invocation.model != "fake" and not any(e.event_type in {
                "MODEL_TURN_STARTED", "MODEL_TURN_COMPLETED", "MODEL_TURN_FAILED", "MUTATION_RESERVED"
            } for e in related):
                add(K.PROVIDER_CALL_UNCERTAIN, invocation)
            if invocation.finished_at is not None or invocation.error_id is not None:
                add(K.EVIDENCE_INCONSISTENT, invocation)
        elif invocation.finished_at is None:
            add(K.EVIDENCE_INCONSISTENT, invocation)
        if invocation.status.value == "COMPLETED":
            if len(outputs) != 1 or invocation.error_id is not None:
                add(K.EVIDENCE_INCONSISTENT, invocation, *outputs)
            elif (current == invocation and STATE_AGENTS.get(task.state) == invocation.agent and
                  not any(e.event_type in {"STATE_TRANSITIONED", "MODEL_ESCALATED"} for e in related)):
                recoverable = True  # Existing _pending() reuse; never mark STARTED complete.
        if invocation.status.value in {"FAILED", "BLOCKED"}:
            error = errors.get(invocation.error_id)
            if error is None or error.source.invocation_id != invocation.id:
                add(K.EVIDENCE_INCONSISTENT, invocation)
            if current == invocation and STATE_AGENTS.get(task.state) == invocation.agent and not any(
                e.event_type in {"STATE_TRANSITIONED", "RETRY_SCHEDULED"} for e in related):
                add(K.AGENT_INVOCATION_PENDING, invocation)

    # Provider reservations use explicit invocation/turn identity, never timestamps.
    turns = {}
    for event in evidence.events:
        if event.event_type not in {"MODEL_TURN_STARTED", "MODEL_TURN_COMPLETED", "MODEL_TURN_FAILED"}:
            continue
        index = event.payload.get("turn_index")
        if event.correlation.invocation_id not in invocations or type(index) is not int or index < 1:
            add(K.EVIDENCE_INCONSISTENT, event)
            continue
        group = turns.setdefault((event.correlation.invocation_id, index), {})
        group.setdefault(event.event_type, []).append(event)
    for group in turns.values():
        starts = group.get("MODEL_TURN_STARTED", [])
        outcomes = group.get("MODEL_TURN_COMPLETED", []) + group.get("MODEL_TURN_FAILED", [])
        if len(starts) != 1 or len(outcomes) > 1:
            add(K.EVIDENCE_INCONSISTENT, *starts, *outcomes)
        if starts and not outcomes:
            add(K.PROVIDER_CALL_UNCERTAIN, *starts)

    # No physical IO on pure demo/fake bundles. Real checks reuse the workspace guard.
    guard = ProjectWorkspaceGuard(None, bundle.binding, reader=bundle.repository_service,
        mutation=bundle.mutation_service, test_provider=bundle.test_provider)
    workspace_valid = True
    try:
        guard.assess(task, evidence.events)
    except (ProjectBindingError, OSError, ValueError):
        workspace_valid = False
        add(K.WORKSPACE_DRIFT)

    applied = []
    for invocation_id in sorted({e.correlation.invocation_id for e in evidence.events if e.event_type.startswith("MUTATION_")}, key=str):
        invocation = invocations.get(invocation_id)
        related = [e for e in evidence.events if e.correlation.invocation_id == invocation_id]
        reserved = [e for e in related if e.event_type == "MUTATION_RESERVED"]
        results = [e for e in related if e.event_type in {"MUTATION_APPLIED", "MUTATION_FAILED"}]
        uncertain = [e for e in related if e.event_type == "MUTATION_RECONCILIATION_REQUIRED"]
        if uncertain or reserved and not results:
            add(K.IMPLEMENTATION_MUTATION_UNCERTAIN, *uncertain, *reserved)
        if (invocation is None or invocation.agent != AgentName.IMPLEMENTER or len(reserved) != 1 or
            len(results) > 1):
            add(K.EVIDENCE_INCONSISTENT, invocation, *reserved, *results)
        for event in results:
            try:
                result = ApplicationResult.model_validate(event.payload["result"])
                if result.rollback == "FAILED":
                    add(K.IMPLEMENTATION_MUTATION_UNCERTAIN, event)
                if event.event_type == "MUTATION_APPLIED":
                    outputs = canonical.get(invocation_id, [])
                    if (not result.success or not result.decision.allowed or result.rollback != "NOT_NEEDED" or invocation is None or
                        invocation.status.value != "COMPLETED" or len(outputs) != 1):
                        add(K.IMPLEMENTATION_MUTATION_UNCERTAIN, event, invocation)
                        continue
                    expected = {f["path"]: f["change_type"] for f in outputs[0].content["changed_files"]}
                    actual = {f.path: "CREATED" if f.operation.value == "CREATE" else "MODIFIED" for f in result.applied}
                    if expected != actual or len(actual) != len(result.applied):
                        add(K.EVIDENCE_INCONSISTENT, event, outputs[0])
                        continue
                    applied.append((invocation, event, result))
                elif result.success or invocation is None or invocation.status.value not in {"FAILED", "BLOCKED"}:
                    add(K.IMPLEMENTATION_MUTATION_UNCERTAIN, event, invocation)
                elif result.applied:
                    add(K.EVIDENCE_INCONSISTENT, event)
            except (KeyError, ValidationError, TypeError, ValueError):
                add(K.EVIDENCE_INCONSISTENT, event)

    # Later durable implementation attempts can replace earlier applied bytes.
    # Verify the newest recorded fact for each path, not obsolete hashes from a repair.
    latest = {}
    for invocation, event, result in sorted(applied, key=lambda item: item[0].attempt):
        service = bundle.mutation_service
        if service is None or len(result.applied) > service.config.max_mutations:
            add(K.IMPLEMENTATION_MUTATION_UNCERTAIN, event)
            continue
        for fact in result.applied:
            latest[fact.path] = (event, fact)
    if workspace_valid:
        grouped = {}
        for event, fact in latest.values():
            grouped.setdefault(event.id, (event, []))[1].append(fact.model_dump())
        for event, facts in grouped.values():
            try:
                bundle.mutation_service.verify_applied(facts, event.payload["workspace_identity"])
            except (MutationFailure, ValidationError, OSError, KeyError, ValueError, TypeError):
                add(K.WORKSPACE_DRIFT, event)

    starts = set()
    for event in evidence.events:
        if event.event_type in {"TEST_RESULT_RECORDED", "TEST_EXECUTION_COMPLETED", "TEST_EXECUTION_FAILED", "TEST_EXECUTION_TIMED_OUT"} and event.correlation.test_run_id not in runs:
            add(K.EVIDENCE_INCONSISTENT, event)
        if event.event_type != "TEST_EXECUTION_STARTED":
            continue
        run_id = event.correlation.test_run_id
        if run_id is None or run_id in starts:
            add(K.EVIDENCE_INCONSISTENT, event)
        starts.add(run_id)
        run = runs.get(run_id)
        if run is None:
            add(K.TEST_EXECUTION_PENDING, event)
        elif run.implementation_artifact_id != event.correlation.artifact_id:
            add(K.EVIDENCE_INCONSISTENT, event, run)
    for run in evidence.test_runs:
        implementation = artifacts.get(run.implementation_artifact_id)
        report = artifacts.get(run.report_artifact_id)
        if (implementation is None or implementation.artifact_type != ArtifactType.IMPLEMENTATION or
            run.task_id != task.id or run.report_artifact_id is not None and (
                report is None or report.artifact_type != ArtifactType.TEST_RESULT)):
            add(K.EVIDENCE_INCONSISTENT, run, implementation, report)

    for job in evidence.jobs:
        if job.project_id != task.project_id or job.task_id != task.id:
            add(K.EVIDENCE_INCONSISTENT, job)
        if job.status.value == "QUEUED":
            recoverable = True
        if job.safe_error_code == ExecutionJobError.EXECUTION_INTERRUPTED:
            recoverable = True
            add(K.EXECUTION_JOB_INTERRUPTED, job, severity=ReconciliationSeverity.INFO)
    if overflow:
        inconsistent = True
        summary, action = GUIDANCE[K.EVIDENCE_INCONSISTENT]
        issues.append(ReconciliationIssueView(kind=K.EVIDENCE_INCONSISTENT, severity="BLOCKING",
            summary=summary, operator_action=action, evidence_refs=()))
    blocked = any(i.severity == ReconciliationSeverity.BLOCKING for i in issues)
    status = (ReconciliationStatus.INCONSISTENT if inconsistent else
        ReconciliationStatus.MANUAL_ACTION_REQUIRED if blocked else
        ReconciliationStatus.RECOVERABLE if recoverable else ReconciliationStatus.CLEAR)
    can_resume = (task.state == TaskState.BLOCKED and task.resume_state is not None and
        task.resume_state not in TERMINAL_STATES | {TaskState.BLOCKED} and
        can_transition(task.state, task.resume_state, resume_state=task.resume_state))
    return ReconciliationAssessmentView(task_id=task.id, status=status,
        safe_to_run=not blocked, safe_to_resume=not blocked and can_resume, issues=tuple(issues))
