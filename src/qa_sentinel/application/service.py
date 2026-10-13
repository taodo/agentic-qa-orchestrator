"""Use-case boundary. Execution and transitions belong exclusively to core."""
from qa_sentinel.persistence.ai_action_results import action_outputs
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
from uuid import UUID, uuid5, NAMESPACE_URL
from pydantic import ValidationError
from qa_sentinel.domain.campaign_review import ApprovalCommand, ReviewError, assess_readiness
from qa_sentinel.execution.synthetic_run import SyntheticRunExecutor, execute_synthetic
from qa_sentinel.domain.qa_run_lifecycle import RunLifecycleError
from .campaign_review import CampaignTraceability, ReviewState, RequirementTrace, TraceLink, Readiness
from qa_sentinel.domain.qa_run import (CreateQARun, QARun, QARunRequirement, QARunTest,
    prepare_run, SnapshotSizeError)
from qa_sentinel.domain.project import Project
from qa_sentinel.domain.campaign import QACampaign, InvalidCampaignTransition
from qa_sentinel.domain.campaign_content import (RequirementExtraction, CampaignRequirement,
    RequirementReviewStatus, ExtractionStatus, Clarification, extraction_retryable)
from qa_sentinel.agents.requirement_extraction import ingest, validate_output, SourceTooLarge
from qa_sentinel.models.base import ModelError, ModelMetadata
from qa_sentinel.agents.test_import import parse_import
from qa_sentinel.agents.test_generation import generation_identity, validate_generation
from qa_sentinel.domain.test_specification import TestGeneration, TestMarker
from .test_specifications import (TestImportView, TestImportDetail, TestSpecificationView, TestGenerationView, generation_view, canonical_spec)
from .campaign_content import (CampaignSourceView, CampaignSourceDetail, CampaignRequirementView,
    ExtractionView, CampaignModelUsage, extraction_view, campaign_usage, ClarificationView, RequirementHistoryEntry)
from qa_sentinel.domain.task import Task
from qa_sentinel.domain.enums import TaskState
from qa_sentinel.domain.execution_job import ExecutionJob, ExecutionJobStatus as JobStatus, ExecutionJobError
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.orchestration.runner import WorkflowRunner
from qa_sentinel.orchestration.workflow_engine import WorkflowEngine
from qa_sentinel.orchestration.errors import WorkflowError
from qa_sentinel.orchestration.state_machine import TERMINAL_STATES
from .commands import CreateTask, UpdateProject, UpdateCampaign, TransitionCampaign
from .errors import ApplicationError, ApplicationErrorCode as Code
from .runtime import ProjectExecutionResolver
from .reconciliation import ReconciliationEvidence, ReconciliationStatus, assess
from .models import (
    CollectionPage, ProjectView, TaskSummary, TaskDetail, TimelineEntry,
    ArtifactView, InvocationView, TestRunView, ErrorView, DecisionView, GateEvaluationView,
    ExecutionJobView, QACampaignView,
)
from .model_usage import TaskModelUsage, assess_usage, MAX_USAGE_EVENTS
from .operations import (
    OperationalAttention, OperationalSummaryView, ProjectOperationalSummaryView,
    TaskOperationalSummaryView, OperationalActivityView,
)


def identifier(value):
    try:
        return value if isinstance(value, UUID) else UUID(value)
    except (TypeError, ValueError, AttributeError):
        raise ApplicationError(Code.INVALID_INPUT) from None


def list_limit(value, maximum=200):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ApplicationError(Code.INVALID_LIST_LIMIT)
    return value


def project_view(record):
    return ProjectView.model_validate(record.model_dump())


def task_view(record, detail=False):
    view = TaskDetail if detail else TaskSummary
    return view.model_validate(record.model_dump(include=set(view.model_fields)))


def record_view(record, view):
    return view.model_validate(record.model_dump(include=set(view.model_fields)))


def page(records, limit, view):
    items = tuple(record_view(record, view) for record in records[:limit])
    return CollectionPage[view](items=items, total_returned=len(items), truncated=len(records) > limit)


@contextmanager
def persistence_boundary():
    """Keep database/model implementation exceptions out of the public contract."""
    try:
        yield
    except ApplicationError:
        raise
    except Exception:
        raise ApplicationError(Code.PERSISTENCE_ERROR) from None


class QASentinelApplication:
    def __init__(self, session_factory, execution_resolver: ProjectExecutionResolver, *, execution_admission=None, execution_notify=None, requirement_extractor=None, test_generator=None, synthetic_run_executor=None, browser_executor=None, browser_plan_generator=None):
        self._factory = session_factory
        self._requirement_extractor = requirement_extractor
        self._test_generator = test_generator
        self._browser_executor = browser_executor
        self._browser_plan_generator = browser_plan_generator
        self._synthetic_run_executor = synthetic_run_executor if synthetic_run_executor is not None else SyntheticRunExecutor()
        self._resolver = execution_resolver
        # Optional trusted host coordination, never supplied by HTTP/model inputs.
        self._execution_admission = execution_admission
        self._execution_notify = execution_notify

    @staticmethod
    def _project(uow, project_id):
        project = uow.projects.get(project_id)
        if project is None:
            raise ApplicationError(Code.PROJECT_NOT_FOUND)
        return project

    def _task(self, uow, task_id, project_id=None):
        if project_id is not None:
            self._project(uow, project_id)
        task = uow.tasks.get(task_id)
        if task is None:
            raise ApplicationError(Code.TASK_NOT_FOUND)
        if project_id is not None and task.project_id != project_id:
            raise ApplicationError(Code.PROJECT_TASK_MISMATCH)
        self._project(uow, task.project_id)
        return task

    def create_project(self, *, key, name, description="") -> ProjectView:
        try:
            project = Project(key=key, name=name, description=description)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            if uow.projects.get_by_key(project.key) is not None:
                raise ApplicationError(Code.PROJECT_KEY_EXISTS)
            uow.projects.add(project)
            result = project_view(project)
            uow.commit()
            return result

    def update_project(self, project_id, **changes) -> ProjectView:
        project_id = identifier(project_id)
        try:
            command = UpdateProject.model_validate(changes)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            project = self._project(uow, project_id)
            for field in command.model_fields_set:
                setattr(project, field, getattr(command, field))
            project.updated_at = datetime.now(timezone.utc)
            uow.projects.save(project)
            result = project_view(project)
            uow.commit()
            return result

    def get_project(self, project_id) -> ProjectView:
        project_id = identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return project_view(self._project(uow, project_id))

    def list_projects(self, *, limit=50) -> CollectionPage[ProjectView]:
        limit = list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return page(uow.reads.projects(limit), limit, ProjectView)

    def _campaign(self, uow, project_id, campaign_id):
        self._project(uow, project_id)
        campaign = uow.campaigns.get(campaign_id)
        if campaign is None:
            raise ApplicationError(Code.CAMPAIGN_NOT_FOUND)
        if campaign.project_id != project_id:
            raise ApplicationError(Code.PROJECT_CAMPAIGN_MISMATCH)
        return campaign

    def _target(self, uow, project_id, target_id):
        self._project(uow, project_id)
        target = uow.targets.get(project_id, target_id)
        if target is None: raise ApplicationError(Code.TARGET_NOT_FOUND)
        return target

    def create_target(self, project_id, **values):
        from qa_sentinel.domain.target import TargetUnderTest
        project_id = identifier(project_id)
        try: target = TargetUnderTest(project_id=project_id, **values)
        except ValidationError: raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._project(uow, project_id)
            uow.targets.add(target); uow.commit()
            return target

    def list_targets(self, project_id, *, limit=50):
        from qa_sentinel.domain.target import TargetUnderTest
        project_id, limit = identifier(project_id), list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._project(uow, project_id)
            return page(uow.targets.list(project_id, limit), limit, TargetUnderTest)

    def get_target(self, project_id, target_id):
        project_id, target_id = map(identifier, (project_id, target_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return self._target(uow, project_id, target_id)

    def update_target(self, project_id, target_id, **changes):
        from qa_sentinel.domain.target import UpdateTarget
        project_id, target_id = map(identifier, (project_id, target_id))
        try: command = UpdateTarget.model_validate(changes)
        except ValidationError: raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write": True})
            target = self._target(uow, project_id, target_id).update(command)
            uow.targets.save(target); uow.commit()
            return target

    def get_campaign_target(self, project_id, campaign_id):
        project_id, campaign_id = map(identifier, (project_id, campaign_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            campaign = self._campaign(uow, project_id, campaign_id)
            return None if campaign.target_id is None else self._target(uow, project_id, campaign.target_id)

    def associate_campaign_target(self, project_id, campaign_id, *, target_id):
        project_id, campaign_id = map(identifier, (project_id, campaign_id))
        target_id = None if target_id is None else identifier(target_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write": True})
            campaign = self._campaign(uow, project_id, campaign_id)
            if target_id is not None: self._target(uow, project_id, target_id)
            campaign = campaign.associate_target(target_id)
            uow.targets.associate(campaign, target_id)
            uow.campaigns.save_metadata(campaign); uow.commit()
            return record_view(campaign, QACampaignView)

    def create_campaign(self, project_id, *, name, objective=None, target_id=None) -> QACampaignView:
        project_id = identifier(project_id)
        try:
            campaign = QACampaign(project_id=project_id, name=name, objective=objective, target_id=target_id)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._project(uow, project_id)
            if campaign.target_id is not None: self._target(uow, project_id, campaign.target_id)
            uow.campaigns.add(campaign)
            result = record_view(campaign, QACampaignView)
            uow.commit()
            return result

    def get_campaign(self, project_id, campaign_id) -> QACampaignView:
        project_id, campaign_id = identifier(project_id), identifier(campaign_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return record_view(self._campaign(uow, project_id, campaign_id), QACampaignView)

    def list_project_campaigns(self, project_id, *, limit=50) -> CollectionPage[QACampaignView]:
        project_id, limit = identifier(project_id), list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._project(uow, project_id)
            return page(uow.campaigns.list_for_project(project_id, limit=limit), limit, QACampaignView)

    def update_campaign(self, project_id, campaign_id, **changes) -> QACampaignView:
        project_id, campaign_id = identifier(project_id), identifier(campaign_id)
        try:
            command = UpdateCampaign.model_validate(changes)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            campaign = self._campaign(uow, project_id, campaign_id).update_metadata(
                **command.model_dump(exclude_unset=True))
            uow.campaigns.save_metadata(campaign)
            result = record_view(campaign, QACampaignView)
            uow.commit()
            return result

    def transition_campaign(self, project_id, campaign_id, *, status) -> QACampaignView:
        project_id, campaign_id = identifier(project_id), identifier(campaign_id)
        try:
            command = TransitionCampaign(status=status)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            campaign = self._campaign(uow, project_id, campaign_id)
            try:
                campaign = campaign.transition(command.status)
                uow.campaigns.save_transition(campaign)
            except InvalidCampaignTransition:
                raise ApplicationError(Code.CAMPAIGN_INVALID_TRANSITION) from None
            result = record_view(campaign, QACampaignView)
            uow.commit()
            return result

    def _source(self, uow, project_id, campaign_id, source_id):
        self._campaign(uow, project_id, campaign_id)
        source = uow.campaign_content.source(source_id)
        if source is None:
            raise ApplicationError(Code.CAMPAIGN_SOURCE_NOT_FOUND)
        if (source.project_id, source.campaign_id) != (project_id, campaign_id):
            raise ApplicationError(Code.CAMPAIGN_SOURCE_MISMATCH)
        return source

    def ingest_campaign_source(self, project_id, campaign_id, *, name, source_type, content) -> CampaignSourceView:
        project_id, campaign_id = identifier(project_id), identifier(campaign_id)
        try:
            source = ingest(project_id, campaign_id, name=name, source_type=source_type, content=content)
        except SourceTooLarge:
            raise ApplicationError(Code.SOURCE_SIZE_LIMIT) from None
        except (ValueError, TypeError):
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            # Reuse the accepted short SQLite writer reservation; no external work here.
            uow.session.connection(execution_options={"qa_job_write": True})
            self._campaign(uow, project_id, campaign_id)
            existing = uow.campaign_content.source_by_content(source)
            if existing is not None:
                return record_view(existing, CampaignSourceView)
            uow.campaign_content.add_source(source)
            result = record_view(source, CampaignSourceView)
            uow.commit()
            return result

    def upload_campaign_document(self, project_id, campaign_id, *, name, content):
        from qa_sentinel.agents.documents import parse_document
        project_id, campaign_id = map(identifier, (project_id, campaign_id))
        # Validate ownership before parsing untrusted data; no external work in a transaction.
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow, project_id, campaign_id)
        try:
            source = parse_document(project_id, campaign_id, name=name, content=content)
        except SourceTooLarge:
            raise ApplicationError(Code.SOURCE_SIZE_LIMIT) from None
        except ValueError:
            raise ApplicationError(Code.DOCUMENT_INVALID) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write": True})
            self._campaign(uow, project_id, campaign_id)
            existing = uow.campaign_content.source_by_content(source)
            if existing is not None: return record_view(existing, CampaignSourceView)
            uow.campaign_content.add_source(source)
            uow.commit()
            return record_view(source, CampaignSourceView)

    def get_campaign_source(self, project_id, campaign_id, source_id) -> CampaignSourceDetail:
        project_id, campaign_id, source_id = map(identifier, (project_id, campaign_id, source_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return record_view(self._source(uow, project_id, campaign_id, source_id), CampaignSourceDetail)

    def list_campaign_sources(self, project_id, campaign_id, *, limit=50, purpose=None) -> CollectionPage[CampaignSourceView]:
        project_id, campaign_id, limit = identifier(project_id), identifier(campaign_id), list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow, project_id, campaign_id)
            if purpose not in (None, "SPECIFICATION", "CLARIFICATION", "TEST_REVIEW"):
                raise ApplicationError(Code.INVALID_INPUT)
            rows = uow.campaign_content.sources(campaign_id, limit, purpose)
            latest = uow.campaign_content.latest_attempts([r["id"] for r in rows[:limit]])
            targets = uow.campaign_content.clarification_targets([r["id"] for r in rows[:limit]])
            outputs = action_outputs(uow.session, latest.values())
            return self._operational_page([{**r, "clarification_requirement_id":targets.get(r["id"]), "latest_extraction":None if r["id"] not in latest else extraction_view(latest[r["id"]], output=outputs[latest[r["id"]].id])} for r in rows], limit, CampaignSourceView)

    def get_campaign_requirement(self, project_id, campaign_id, requirement_id) -> CampaignRequirementView:
        project_id, campaign_id, requirement_id = map(identifier, (project_id, campaign_id, requirement_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow, project_id, campaign_id)
            requirement = uow.campaign_content.requirement(requirement_id)
            if requirement is None:
                raise ApplicationError(Code.CAMPAIGN_REQUIREMENT_NOT_FOUND)
            if (requirement.project_id, requirement.campaign_id) != (project_id, campaign_id):
                raise ApplicationError(Code.CAMPAIGN_REQUIREMENT_MISMATCH)
            return record_view(requirement, CampaignRequirementView)

    def list_campaign_requirements(self, project_id, campaign_id, *, limit=50) -> CollectionPage[CampaignRequirementView]:
        project_id, campaign_id, limit = identifier(project_id), identifier(campaign_id), list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow, project_id, campaign_id)
            return page(uow.campaign_content.requirements(campaign_id, limit), limit, CampaignRequirementView)

    def _review_object(self, uow, project_id, campaign_id, object_id, kind):
        self._campaign(uow, project_id, campaign_id)
        if kind == "TEST_SPECIFICATION":
            return self._test_child(uow, project_id, campaign_id, object_id, 'specification')
        record = uow.campaign_content.requirement(object_id)
        if record is None: raise ApplicationError(Code.CAMPAIGN_REQUIREMENT_NOT_FOUND)
        if (record.project_id, record.campaign_id) != (project_id, campaign_id):
            raise ApplicationError(Code.CAMPAIGN_REQUIREMENT_MISMATCH)
        return record

    def _review(self, project_id, campaign_id, object_id, kind, command=None):
        project_id, campaign_id, object_id = map(identifier, (project_id, campaign_id, object_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            if command is not None:
                uow.session.connection(execution_options={"qa_job_write": True})
            record = self._review_object(uow, project_id, campaign_id, object_id, kind)
            try:
                if command is None:
                    return uow.campaign_reviews.state(record, kind)
                if kind == "REQUIREMENT" and not uow.campaign_content.is_current(record.id):
                    raise ReviewError("REVIEW_NOT_REVIEWABLE")
                if kind == "TEST_SPECIFICATION":
                    from sqlalchemy import select
                    from qa_sentinel.persistence.models import TestSpecificationRow
                    from qa_sentinel.persistence.preparation_current import current_test
                    if uow.session.scalar(select(TestSpecificationRow.id).where(TestSpecificationRow.id==str(record.id),current_test())) is None:
                        raise ReviewError("REVIEW_NOT_REVIEWABLE")
                if kind == "TEST_SPECIFICATION" and any(not uow.campaign_content.is_current(id) for id in record.requirement_ids):
                    raise ReviewError("REVIEW_NOT_REVIEWABLE")
                result = uow.campaign_reviews.approve(record, kind, command)
            except ReviewError as error:
                raise ApplicationError(Code(str(error))) from None
            uow.commit()
            return result

    @staticmethod
    def _approval_command(reviewer_label, note, action):
        try:
            return ApprovalCommand(reviewer_label=reviewer_label, note=note, action=action)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None

    def review_campaign_requirement(self, project_id, campaign_id, requirement_id, *, reviewer_label, note=None, action="APPROVE") -> ReviewState:
        return self._review(project_id, campaign_id, requirement_id, "REQUIREMENT",
            self._approval_command(reviewer_label, note, action))

    def get_campaign_requirement_review(self, project_id, campaign_id, requirement_id) -> ReviewState:
        return self._review(project_id, campaign_id, requirement_id, "REQUIREMENT")

    def review_campaign_test_specification(self, project_id, campaign_id, test_spec_id, *, reviewer_label, note=None, action="APPROVE") -> ReviewState:
        return self._review(project_id, campaign_id, test_spec_id, "TEST_SPECIFICATION",
            self._approval_command(reviewer_label, note, action))

    def get_campaign_test_specification_review(self, project_id, campaign_id, test_spec_id) -> ReviewState:
        return self._review(project_id, campaign_id, test_spec_id, "TEST_SPECIFICATION")

    def get_campaign_traceability(self, project_id, campaign_id, *, limit=50) -> CampaignTraceability:
        project_id, campaign_id, limit = identifier(project_id), identifier(campaign_id), list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow, project_id, campaign_id)
            requirements, req_more, links, link_more = uow.campaign_reviews.traceability(project_id, campaign_id, limit)
            return CampaignTraceability(project_id=project_id, campaign_id=campaign_id,
                requirements=CollectionPage[RequirementTrace](items=requirements, total_returned=len(requirements), truncated=req_more),
                links=CollectionPage[TraceLink](items=links, total_returned=len(links), truncated=link_more))

    def get_campaign_readiness(self, project_id, campaign_id) -> Readiness:
        project_id, campaign_id = map(identifier, (project_id, campaign_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            campaign = self._campaign(uow, project_id, campaign_id)
            return assess_readiness(campaign, uow.campaign_reviews.readiness_counts(project_id, campaign_id))

    def get_test_edit_evidence(self, project_id, campaign_id, test_id):
        from sqlalchemy import select
        from qa_sentinel.persistence.models import TestEditRow
        from .product_v2 import TestEditEvidence
        project_id,campaign_id,test_id = map(identifier,(project_id,campaign_id,test_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._review_object(uow,project_id,campaign_id,test_id,"TEST_SPECIFICATION")
            row = uow.session.scalar(select(TestEditRow).where(TestEditRow.project_id==str(project_id),
                TestEditRow.campaign_id==str(campaign_id),TestEditRow.test_id==str(test_id)))
            return None if row is None else TestEditEvidence.model_validate({name:getattr(row,name) for name in TestEditEvidence.model_fields})

    def get_test_design_page(self, project_id, campaign_id, *, search="", status="ALL", page=1, page_size=10):
        from .test_design import DesignCriteria, design_page
        project_id, campaign_id = map(identifier, (project_id, campaign_id))
        try: criteria = DesignCriteria(search=search, status=status)
        except ValidationError: raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow, project_id, campaign_id)
            return design_page(uow, project_id, campaign_id, criteria, page, page_size)

    def test_design_selection(self, project_id, campaign_id, *, selection, fingerprint=None, reviewer_label=None, note=None):
        from .test_design import DesignSelection, summarize, records, approvable
        project_id, campaign_id = map(identifier, (project_id, campaign_id))
        try: selection = DesignSelection.model_validate(selection)
        except ValidationError: raise ApplicationError(Code.INVALID_INPUT) from None
        command = None if fingerprint is None else self._approval_command(reviewer_label, note, "APPROVE")
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            if command is not None:
                uow.session.connection(execution_options={"qa_job_write": True})
            self._campaign(uow, project_id, campaign_id)
            summary = summarize(uow, project_id, campaign_id, selection)
            if command is None:
                return summary
            if summary.fingerprint != fingerprint:
                raise ApplicationError(Code.REVIEW_CONFLICT)
            # No receipts are written until every selected identity/hash/status has
            # been revalidated under the writer reservation. Ineligible is explicit.
            approved = 0
            try:
                for test in records(uow, project_id, campaign_id, selection):
                    if approvable(test):
                        uow.campaign_reviews.approve(test, "TEST_SPECIFICATION", command)
                        approved += 1
            except ReviewError as error:
                raise ApplicationError(Code(str(error))) from None
            uow.commit()
            return dict(matched=summary.matched, approved=approved, skipped=summary.matched-approved)

    def export_qa_run(self, project_id, campaign_id, run_id, *, format):
        from sqlalchemy import select, func
        from qa_sentinel.persistence.models import QARunEvidenceRow
        from .test_export import export_rows
        project_id, campaign_id, run_id = map(identifier, (project_id, campaign_id, run_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            run = self._qa_run(uow, project_id, campaign_id, run_id)
            tests = uow.qa_runs.all_entries(run, "tests")  # existing 1,000 snapshot cap
            counts = dict(uow.session.execute(select(QARunEvidenceRow.run_test_id, func.count()).where(
                QARunEvidenceRow.project_id == str(project_id), QARunEvidenceRow.campaign_id == str(campaign_id),
                QARunEvidenceRow.run_id == str(run_id)).group_by(QARunEvidenceRow.run_test_id).limit(1001)).all())
            rows = [("Run ID", "Run number", "Test snapshot ID", "Test Case ID", "Test title", "Execution status", "QA result", "Priority",
                     "Requirement IDs", "Evidence count", "Run created", "Run started", "Run completed", "Run execution status", "Run QA outcome")]
            for t in tests:
                rows.append((run.id, run.run_number, t.id, t.original_test_specification_id, t.content.title,
                    t.execution_status, t.qa_result, t.content.priority, "; ".join(map(str, t.content.requirement_ids)),
                    counts.get(str(t.id), 0), run.created_at.isoformat(),
                    run.started_at.isoformat() if run.started_at else "", run.completed_at.isoformat() if run.completed_at else "",
                    run.execution_status, run.qa_outcome))
        try: return export_rows(rows, format, f"run-{run.run_number}-results", len(tests))
        except ValueError: raise ApplicationError(Code.INVALID_INPUT) from None

    def export_campaign_tests(self, project_id, campaign_id, *, test_specification_ids, format):
        from sqlalchemy import select
        from qa_sentinel.persistence.models import CampaignRequirementRow, TestSpecificationRow
        from qa_sentinel.persistence.campaign_content import requirement_from
        from qa_sentinel.persistence.preparation_current import current_test
        from .test_export import export_tests
        project_id,campaign_id = map(identifier,(project_id,campaign_id))
        ids = tuple(identifier(id) for id in test_specification_ids)
        if not 1 <= len(ids) <= 200 or len(set(ids)) != len(ids): raise ApplicationError(Code.INVALID_INPUT)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow,project_id,campaign_id)
            rows = list(uow.session.scalars(select(TestSpecificationRow).where(TestSpecificationRow.project_id == str(project_id),
                TestSpecificationRow.campaign_id == str(campaign_id),TestSpecificationRow.id.in_([str(id) for id in ids]),current_test()).order_by(TestSpecificationRow.id).limit(201)))
            if len(rows) != len(ids): raise ApplicationError(Code.INVALID_INPUT)
            tests = uow.test_specifications._specs(rows)
            needed = {id for t in tests for id in t.requirement_ids}
            requirements = [requirement_from(row) for row in uow.session.scalars(select(CampaignRequirementRow).where(
                CampaignRequirementRow.project_id == str(project_id),CampaignRequirementRow.campaign_id == str(campaign_id),
                CampaignRequirementRow.id.in_([str(id) for id in needed])).limit(4001))]
        try: return export_tests(tests,requirements,format)
        except ValueError: raise ApplicationError(Code.INVALID_INPUT) from None

    def edit_campaign_test(self, project_id, campaign_id, test_id, *, design, previous_hash, reviewer_label, note):
        return self._edit_campaign_test(project_id,campaign_id,test_id,design=design,previous_hash=previous_hash,
            reviewer_label=reviewer_label,note=note)

    def _edit_campaign_test(self, project_id, campaign_id, test_id, *, design, previous_hash, reviewer_label, note, reserved_facts=None):
        import json
        from uuid import uuid4
        from sqlalchemy import select
        from qa_sentinel.domain.test_specification import TestDesign, CampaignTestSpecification, TestProvenance
        from qa_sentinel.domain.campaign_review import content_hash
        from qa_sentinel.persistence.preparation_current import current_test
        from qa_sentinel.persistence.models import TestSpecificationRow, TestRequirementLinkRow, TestEditRow
        from qa_sentinel.persistence.campaign_content import row_values
        project_id,campaign_id,test_id = map(identifier,(project_id,campaign_id,test_id))
        try:
            design = TestDesign.model_validate(design)
            assertion = ApprovalCommand(reviewer_label=reviewer_label,note=note)
            if not assertion.note: raise ValueError()
        except (ValueError,TypeError): raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write":True})
            old = self._review_object(uow,project_id,campaign_id,test_id,"TEST_SPECIFICATION")
            current = uow.session.scalar(select(TestSpecificationRow.id).where(TestSpecificationRow.id==str(test_id),current_test()))
            if current is None or previous_hash != content_hash(old) or design.key != old.key or old.unresolved_requirement_refs:
                raise ApplicationError(Code.REVIEW_CONFLICT)
            from .browser_ux import is_reserved_facts, validate_facts
            existing = tuple(text for text in old.preconditions if is_reserved_facts(text))
            submitted = tuple(text for text in design.preconditions if is_reserved_facts(text))
            if reserved_facts is None:
                # Generic omission cannot delete facts; explicit raw submissions may only retain exact bytes.
                if submitted and submitted != existing: raise ApplicationError(Code.INVALID_INPUT)
                preconditions = tuple(text for text in design.preconditions if not is_reserved_facts(text)) + existing
            else:
                # Only the validated dedicated application path supplies this internal typed value.
                try: expected = (validate_facts(reserved_facts,old).model_dump_json(),)
                except ValueError: raise ApplicationError(Code.INVALID_INPUT) from None
                if submitted != expected: raise ApplicationError(Code.INVALID_INPUT)
                preconditions = design.preconditions
            try: design = TestDesign.model_validate({**design.model_dump(),"preconditions":preconditions})
            except ValueError: raise ApplicationError(Code.INVALID_INPUT) from None
            prior_edit = uow.session.scalar(select(TestEditRow).where(TestEditRow.test_id==str(test_id)))
            version = 2 if prior_edit is None else prior_edit.version+1
            if version > 10: raise ApplicationError(Code.REVIEW_CONFLICT)
            # Human evidence is separate from PRD evidence. No source citation is invented.
            try:
                facts = ingest(project_id,campaign_id,name="Human test review: "+old.key,source_type="TEXT",
                    content="Human-provided test design information\n"+assertion.note+"\n"+json.dumps(design.model_dump(mode="json"),ensure_ascii=False))
            except SourceTooLarge: raise ApplicationError(Code.SOURCE_SIZE_LIMIT) from None
            if facts.status != "INGESTED": raise ApplicationError(Code.INVALID_INPUT)
            facts = type(facts).model_validate({**facts.model_dump(),"purpose":"TEST_REVIEW"})
            existing = uow.campaign_content.source_by_content(facts)
            if existing is None: uow.campaign_content.add_source(facts)
            else: facts = existing
            edit_id,new_id = uuid4(),uuid4()
            try:
                new = CampaignTestSpecification(**design.model_dump(),id=new_id,project_id=project_id,campaign_id=campaign_id,
                    logical_key="HUMAN-"+str(new_id),requirement_ids=old.requirement_ids,unresolved_requirement_refs=old.unresolved_requirement_refs,
                    provenance=TestProvenance(origin="HUMAN_EDIT",record_id=edit_id,content_hash=facts.content_hash,contract_version="test-human-v1"),
                    review_status="NEEDS_CLARIFICATION" if design.information_markers else "READY_FOR_REVIEW")
            except ValidationError: raise ApplicationError(Code.INVALID_INPUT) from None
            values = row_values(new);ids=values.pop("requirement_ids")
            uow.session.add(TestSpecificationRow(**values,import_id=None,generation_id=None))
            for id in ids: uow.session.add(TestRequirementLinkRow(test_spec_id=str(new_id),requirement_id=id,project_id=str(project_id),campaign_id=str(campaign_id)))
            uow.session.add(TestEditRow(id=str(edit_id),project_id=str(project_id),campaign_id=str(campaign_id),test_id=str(new_id),previous_id=str(test_id),
                source_id=str(facts.id),version=version,reviewer_label=assertion.reviewer_label,note=assertion.note,previous_hash=previous_hash,created_at=new.created_at))
            uow.commit()
            return TestSpecificationView.model_validate(new.model_dump())

    def list_execution_candidates(self, project_id, campaign_id, *, limit=50, after_id=UUID(int=0)):
        from sqlalchemy import select
        from qa_sentinel.persistence.models import CampaignRequirementRow, RequirementReviewRow, TestSpecificationReviewRow
        from qa_sentinel.persistence.campaign_content import requirement_from
        from qa_sentinel.persistence.preparation_current import current_requirement
        from qa_sentinel.domain.qa_run import validate_approval
        from qa_sentinel.domain.campaign_review import ApprovalEvidence, content_hash
        from .product_v2 import ExecutionCandidate
        project_id,campaign_id,limit,after_id = identifier(project_id),identifier(campaign_id),list_limit(limit),identifier(after_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow,project_id,campaign_id)
            tests = uow.qa_runs.candidates(project_id,campaign_id,limit,after_id)
            selected = tests[:limit]
            ids = {id for test in selected for id in test.requirement_ids}
            requirements = {r.id:r for r in (requirement_from(row) for row in uow.session.scalars(select(CampaignRequirementRow).where(
                CampaignRequirementRow.project_id == str(project_id),CampaignRequirementRow.campaign_id == str(campaign_id),
                CampaignRequirementRow.id.in_([str(id) for id in ids]),current_requirement()).limit(limit*20+1)))}
            def receipts(table, ids, kind):
                return {row.object_id: ApprovalEvidence.model_validate({"object_kind":kind,
                    **{name:getattr(row,name) for name in ApprovalEvidence.model_fields if name != "object_kind"}})
                    for row in uow.session.scalars(select(table).where(table.project_id == str(project_id),table.campaign_id == str(campaign_id),table.object_id.in_([str(id) for id in ids])).limit(len(ids)+1))}
            req_receipts = receipts(RequirementReviewRow,ids,"REQUIREMENT")
            test_receipts = receipts(TestSpecificationReviewRow,[test.id for test in selected],"TEST_SPECIFICATION")
            items = []
            for test in selected:
                reason = None
                try:
                    validate_approval(test,test_receipts.get(str(test.id)),"TEST_SPECIFICATION")
                    if test.unresolved_requirement_refs or not test.requirement_ids or not test.required_evidence or test.overall_expected_result is None or any(s.expected is None for s in test.steps): raise ValueError()
                    for id in test.requirement_ids:
                        requirement = requirements[id]
                        validate_approval(requirement,req_receipts.get(str(id)),"REQUIREMENT")
                        if not requirement.acceptance_criteria: raise ValueError()
                except (ValueError,AttributeError,KeyError):
                    reason = "Approval, supported expected behavior and current approved source Requirements are required."
                items.append(ExecutionCandidate(test=test,content_hash=content_hash(test),eligible=reason is None,reason=reason))
            return CollectionPage[ExecutionCandidate](items=items,total_returned=len(items),truncated=len(tests)>limit)

    def edit_browser_facts(self, project_id, campaign_id, test_id, **command):
        from .browser_ux import edit_facts
        return edit_facts(self,project_id,campaign_id,test_id,**command)

    def browser_planning_readiness(self, project_id, campaign_id, test_id, *, provider_available):
        from .browser_ux import readiness
        return readiness(self,project_id,campaign_id,test_id,provider_available=provider_available)

    def generate_ready_browser_plan(self, project_id, campaign_id, test_id, *, provider_available):
        state=self.browser_planning_readiness(project_id,campaign_id,test_id,provider_available=provider_available)
        if state.status=='PROVIDER_UNAVAILABLE':raise ApplicationError(Code.GENERATION_NOT_CONFIGURED)
        if state.status!='AVAILABLE':raise ApplicationError(Code.BROWSER_PLAN_PROVENANCE_MISMATCH)
        return self.generate_browser_plan(project_id,campaign_id,test_id)

    def generate_browser_plan(self, project_id, campaign_id, test_id):
        from .browser_generation import generate
        return generate(self,project_id,campaign_id,test_id)

    def retry_browser_plan_generation(self, project_id, campaign_id, generation_id):
        from .browser_generation import generate
        return generate(self,project_id,campaign_id,None,previous_id=generation_id)

    def get_browser_plan_generation(self, project_id, campaign_id, generation_id):
        project_id,campaign_id,generation_id=map(identifier,(project_id,campaign_id,generation_id))
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            self._campaign(uow,project_id,campaign_id)
            record=uow.browser_plans.get(project_id,campaign_id,generation_id)
            if record is None:raise ApplicationError(Code.BROWSER_PLAN_NOT_FOUND)
            return record

    def list_browser_plan_generations(self, project_id, campaign_id, *, limit=20):
        project_id,campaign_id=map(identifier,(project_id,campaign_id));limit=list_limit(limit,50)
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            self._campaign(uow,project_id,campaign_id)
            rows=uow.browser_plans.list(project_id,campaign_id,limit)
            return CollectionPage(items=tuple(rows[:limit]),total_returned=min(len(rows),limit),truncated=len(rows)>limit)

    def get_browser_plan_acceptance(self, project_id, campaign_id, generation_id):
        project_id,campaign_id,generation_id=map(identifier,(project_id,campaign_id,generation_id))
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            self._campaign(uow,project_id,campaign_id)
            if uow.browser_plans.get(project_id,campaign_id,generation_id) is None:raise ApplicationError(Code.BROWSER_PLAN_NOT_FOUND)
            return uow.browser_plans.acceptance(project_id,campaign_id,generation_id)

    def accept_browser_plan_generation(self, project_id, campaign_id, generation_id, *, idempotency_key, note=None):
        if self._browser_executor is None:raise ApplicationError(Code.RUN_INVALID_STATE)
        record=self.get_browser_plan_generation(project_id,campaign_id,generation_id)
        if record.status!='SUCCEEDED':raise ApplicationError(Code.BROWSER_PLAN_PROVENANCE_MISMATCH)
        return self._create_qa_run(project_id,campaign_id,idempotency_key=idempotency_key,note=note,
            test_specification_ids=(record.test.id,),browser_generation_id=record.id)

    def create_qa_run(self, project_id, campaign_id, *, idempotency_key, note=None, test_specification_ids=None) -> QARun:
        return self._create_qa_run(project_id,campaign_id,idempotency_key=idempotency_key,note=note,test_specification_ids=test_specification_ids)

    def create_browser_qa_run(self, project_id, campaign_id, *, idempotency_key, plans, note=None) -> QARun:
        if self._browser_executor is None: raise ApplicationError(Code.RUN_INVALID_STATE)
        return self._create_qa_run(project_id,campaign_id,idempotency_key=idempotency_key,note=note,
            test_specification_ids=tuple(plans),browser_plans=plans)

    def _create_qa_run(self, project_id, campaign_id, *, idempotency_key, note=None, test_specification_ids=None, browser_plans=None, browser_generation_id=None) -> QARun:
        project_id, campaign_id = map(identifier, (project_id, campaign_id))
        try:
            command = CreateQARun(idempotency_key=idempotency_key, note=note, test_specification_ids=test_specification_ids)
        except ValidationError as error:
            code = Code.INVALID_IDEMPOTENCY_KEY if any(e["loc"] and e["loc"][0] == "idempotency_key" for e in error.errors()) else Code.INVALID_INPUT
            raise ApplicationError(code) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            # Reserve before any preparation read: one consistent, atomic SQLite
            # snapshot and protected numbering. No external execution in this UoW.
            uow.session.connection(execution_options={"qa_job_write": True})
            campaign = self._campaign(uow, project_id, campaign_id)
            generation=acceptance=None
            if browser_generation_id is not None:
                generation=uow.browser_plans.get(project_id,campaign_id,browser_generation_id)
                if generation is None or generation.status!='SUCCEEDED':raise ApplicationError(Code.BROWSER_PLAN_PROVENANCE_MISMATCH)
                browser_plans={generation.test.id:generation.output.plan}
                acceptance=uow.browser_plans.acceptance(project_id,campaign_id,generation.id)
            existing = uow.qa_runs.by_key(project_id, campaign_id, command.idempotency_key)
            if existing is not None:
                if generation is not None and (acceptance is None or acceptance.run_id!=existing.id):
                    raise ApplicationError(Code.RUN_IDEMPOTENCY_CONFLICT)
                if generation is None and any(t.browser_plan is not None and t.browser_plan.origin=='AI' for t in uow.qa_runs.all_entries(existing,'tests')):
                    raise ApplicationError(Code.RUN_IDEMPOTENCY_CONFLICT)
                if (existing.executor_kind == "WEB_BROWSER") != (browser_plans is not None):
                    raise ApplicationError(Code.RUN_IDEMPOTENCY_CONFLICT)
                if browser_plans is not None:
                    prior=uow.qa_runs.all_entries(existing,"tests")
                    if any(t.browser_plan.plan != browser_plans[t.content.id] for t in prior if t.content.id in browser_plans):
                        raise ApplicationError(Code.RUN_IDEMPOTENCY_CONFLICT)
                if existing.note != command.note:
                    raise ApplicationError(Code.RUN_IDEMPOTENCY_CONFLICT)
                if command.test_specification_ids is not None:
                    original = uow.qa_runs.all_entries(existing, "tests")
                    if existing.snapshot_version != "qa-run-selection-v2" or {t.content.id for t in original} != set(command.test_specification_ids):
                        raise ApplicationError(Code.RUN_IDEMPOTENCY_CONFLICT)
                elif existing.snapshot_version != "qa-run-snapshot-v1":
                    raise ApplicationError(Code.RUN_IDEMPOTENCY_CONFLICT)
                return existing  # Replay original intent, even if preparation changed.
            if acceptance is not None:raise ApplicationError(Code.BROWSER_PLAN_ALREADY_ACCEPTED)
            readiness = assess_readiness(campaign, uow.campaign_reviews.readiness_counts(project_id, campaign_id))
            if command.test_specification_ids is None and readiness.status != "READY":
                raise ApplicationError(Code.CAMPAIGN_NOT_READY_FOR_RUN)
            try:
                requirements, tests = (uow.qa_runs.approved_content(project_id, campaign_id) if command.test_specification_ids is None
                    else uow.qa_runs.selection_content(project_id, campaign_id, command.test_specification_ids))
                # Validate full approval versions, not only SQL readiness counts.
                reqs = uow.campaign_reviews.evidence_batch(requirements, "REQUIREMENT")
                specs = uow.campaign_reviews.evidence_batch(tests, "TEST_SPECIFICATION")
                from qa_sentinel.domain.target import TargetSnapshot
                target_snapshot = None if campaign.target_id is None else TargetSnapshot.capture(self._target(uow, project_id, campaign.target_id))
                prepared = prepare_run(campaign, readiness, command, uow.qa_runs.next_number(campaign_id), reqs, specs, target_snapshot)
                if browser_plans is not None:
                    from .browser_runs import seal
                    if generation is not None:
                        from qa_sentinel.domain.browser_generation import input_hash
                        from qa_sentinel.execution.browser_policy import digest
                        from qa_sentinel.agents.browser_plan_generation import validate_candidate
                        candidate_test=prepared.tests[0]
                        if target_snapshot is None or generation.target_hash!=digest(target_snapshot) or generation.test_hash!=input_hash(candidate_test.content,candidate_test.approval):
                            raise ApplicationError(Code.BROWSER_PLAN_PROVENANCE_MISMATCH)
                        validate_candidate(generation,generation.output,self._browser_executor.policy_for(target_snapshot))
                    prepared=seal(prepared,browser_plans,self._browser_executor.identity,
                        self._browser_executor.policy_for(target_snapshot),origin='AI' if generation is not None else 'MANUAL')
                uow.qa_runs.add(prepared)
                if generation is not None:
                    from qa_sentinel.domain.browser_generation import BrowserPlanAcceptance
                    uow.browser_plans.accept(BrowserPlanAcceptance(generation_id=generation.id,project_id=project_id,campaign_id=campaign_id,
                        run_id=prepared.run.id,run_test_id=prepared.tests[0].id,plan_hash=generation.plan_hash))
            except SnapshotSizeError:
                raise ApplicationError(Code.RUN_SNAPSHOT_SIZE_LIMIT) from None
            except ReviewError:
                raise ApplicationError(Code.REVIEW_EVIDENCE_INVALID) from None
            except ValueError:
                raise ApplicationError(Code.RUN_SELECTION_INVALID) from None
            uow.commit()
            return prepared.run

    def _qa_run(self, uow, project_id, campaign_id, run_id):
        self._campaign(uow, project_id, campaign_id)
        run = uow.qa_runs.get(project_id, campaign_id, run_id)
        if run is None:
            # Distinguish a Campaign mismatch only inside the already validated
            # Project scope; foreign Project identities remain indistinguishable.
            if uow.qa_runs.exists_in_project(project_id, run_id):
                raise ApplicationError(Code.RUN_CAMPAIGN_MISMATCH)
            raise ApplicationError(Code.RUN_NOT_FOUND)
        return run

    def start_qa_run(self, project_id, campaign_id, run_id) -> QARun:
        return self._start_qa_run(project_id,campaign_id,run_id)

    def start_browser_qa_run(self, project_id, campaign_id, run_id) -> QARun:
        return self._start_qa_run(project_id,campaign_id,run_id,allow_browser=True)

    def _start_qa_run(self, project_id, campaign_id, run_id, *, allow_browser=False) -> QARun:
        project_id, campaign_id, run_id = map(identifier, (project_id, campaign_id, run_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write": True})
            run = self._qa_run(uow, project_id, campaign_id, run_id)
            if (run.executor_kind == "WEB_BROWSER") != allow_browser:
                raise ApplicationError(Code.RUN_INVALID_STATE)
            if allow_browser and (self._browser_executor is None or run.runtime_identity != self._browser_executor.identity):
                raise ApplicationError(Code.RUN_INVALID_STATE)
            if run.execution_status != "CREATED":
                raise ApplicationError(Code.RUN_INVALID_STATE)
            prepared = uow.qa_runs.preparation(run)
            if any(t.execution_status != "NOT_STARTED" for t in prepared.tests):
                raise ApplicationError(Code.RUN_INVALID_STATE)
            uow.qa_runs.start(run)
            uow.commit()  # Claim is durable before any executor evaluation.
        try:
            for snapshot in prepared.tests:
                with persistence_boundary(), UnitOfWork(self._factory) as uow:
                    uow.session.connection(execution_options={"qa_job_write": True})
                    run = uow.qa_runs.get(project_id, campaign_id, run_id)
                    running = uow.qa_runs.start_test(run, uow.qa_runs.test(run, snapshot.id))
                    uow.commit()
                result = (self._browser_executor.execute(running.browser_plan,run,running) if allow_browser else
                    execute_synthetic(self._synthetic_run_executor, running))  # No open DB transaction.
                with persistence_boundary(), UnitOfWork(self._factory) as uow:
                    uow.session.connection(execution_options={"qa_job_write": True})
                    run = uow.qa_runs.get(project_id, campaign_id, run_id)
                    uow.qa_runs.complete_test(run, uow.qa_runs.test(run, snapshot.id), result)
                    uow.commit()  # Durable result AND evidence before processing the next test, including FAIL.
            return self._finish_qa_run(project_id, campaign_id, run_id)
        except Exception as error:
            # No raw exception text/evidence; earlier committed test results survive.
            from qa_sentinel.execution.playwright_browser import BrowserExecutionError
            from qa_sentinel.domain.browser_execution import BrowserErrorCode
            safe_code = (error.code if isinstance(error,BrowserExecutionError) else BrowserErrorCode.INTERNAL) if allow_browser else None
            return self._finish_qa_run(project_id, campaign_id, run_id, failed=True, browser_error_code=safe_code)

    def _finish_qa_run(self, project_id, campaign_id, run_id, *, failed=False, browser_error_code=None):
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write": True})
            run = uow.qa_runs.get(project_id, campaign_id, run_id)
            try:
                result = uow.qa_runs.finish(run, failed=failed, browser_error_code=browser_error_code)
            except RunLifecycleError:
                raise ApplicationError(Code.RUN_INVALID_STATE) from None
            uow.commit()
            return result

    def get_qa_run(self, project_id, campaign_id, run_id) -> QARun:
        project_id, campaign_id, run_id = map(identifier, (project_id, campaign_id, run_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return self._qa_run(uow, project_id, campaign_id, run_id)

    def list_qa_runs(self, project_id, campaign_id, *, limit=50) -> CollectionPage[QARun]:
        project_id, campaign_id = map(identifier, (project_id, campaign_id))
        limit = list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow, project_id, campaign_id)
            return page(uow.qa_runs.list(project_id, campaign_id, limit), limit, QARun)

    def _qa_run_entries(self, project_id, campaign_id, run_id, kind, limit, after_position):
        project_id, campaign_id, run_id = map(identifier, (project_id, campaign_id, run_id))
        limit = list_limit(limit)
        if type(after_position) is not int or not 0 <= after_position <= 1000:
            raise ApplicationError(Code.INVALID_INPUT)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            run = self._qa_run(uow, project_id, campaign_id, run_id)
            contract = QARunTest if kind == "tests" else QARunRequirement
            return page(uow.qa_runs.entries(run, kind, limit, after_position), limit, contract)

    def list_qa_run_tests(self, project_id, campaign_id, run_id, *, limit=50, after_position=0) -> CollectionPage[QARunTest]:
        return self._qa_run_entries(project_id, campaign_id, run_id, "tests", limit, after_position)

    def list_qa_run_requirements(self, project_id, campaign_id, run_id, *, limit=50, after_position=0) -> CollectionPage[QARunRequirement]:
        return self._qa_run_entries(project_id, campaign_id, run_id, "requirements", limit, after_position)

    def get_qa_run_results(self, project_id, campaign_id, run_id, *, limit=50, after_position=0):
        from .qa_run_results import QARunResults, QARunResultSummary, QARunTestResult, evidence_page
        from qa_sentinel.domain.qa_run_evidence import EVIDENCE_PREVIEW_LIMIT
        project_id, campaign_id, run_id = map(identifier, (project_id, campaign_id, run_id))
        limit = list_limit(limit)
        if type(after_position) is not int or not 0 <= after_position <= 1000:
            raise ApplicationError(Code.INVALID_INPUT)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            run = self._qa_run(uow, project_id, campaign_id, run_id)
            tests = page(uow.qa_runs.entries(run, "tests", limit, after_position), limit, QARunTest)
            evidence = uow.qa_runs.evidence_preview(run, [t.id for t in tests.items], EVIDENCE_PREVIEW_LIMIT)
            items = []
            for test in tests.items:
                count, records = evidence.get(str(test.id), (0, []))
                items.append(QARunTestResult(**test.model_dump(), evidence_count=count,
                    evidence=CollectionPage(items=evidence_page(records, EVIDENCE_PREVIEW_LIMIT).items, total_returned=len(records), truncated=count > len(records))))
            return QARunResults(run=run, summary=QARunResultSummary(**uow.qa_runs.result_counts(run)),
                tests=CollectionPage(items=tuple(items), total_returned=len(items), truncated=tests.truncated))

    def list_qa_run_test_evidence(self, project_id, campaign_id, run_id, test_id, *, limit=50, after_sequence=0):
        from qa_sentinel.domain.qa_run_evidence import MAX_TEST_EVIDENCE
        from .qa_run_results import evidence_page
        project_id, campaign_id, run_id, test_id = map(identifier, (project_id, campaign_id, run_id, test_id))
        limit = list_limit(limit)
        if type(after_sequence) is not int or not 0 <= after_sequence <= MAX_TEST_EVIDENCE:
            raise ApplicationError(Code.INVALID_INPUT)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            run = self._qa_run(uow, project_id, campaign_id, run_id)
            # Conceal foreign/missing Test identities with the established scoped Run error.
            try:
                uow.qa_runs.test(run, test_id)
            except RunLifecycleError:
                raise ApplicationError(Code.RUN_NOT_FOUND) from None
            return evidence_page(uow.qa_runs.evidence(run, test_id, limit, after_sequence), limit)

    def get_campaign_model_usage(self, project_id, campaign_id, *, limit=200) -> CampaignModelUsage:
        project_id, campaign_id, limit = identifier(project_id), identifier(campaign_id), list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow, project_id, campaign_id)
            records=uow.campaign_content.extractions(campaign_id,limit)+uow.test_specifications.generations(campaign_id,limit)
            latest = uow.campaign_content.latest_attempts([r.source_id for r in records if isinstance(r, RequirementExtraction)])
            return campaign_usage(project_id,campaign_id,sorted(records,key=lambda r:(r.started_at,str(r.id))),limit,
                latest_attempt_ids={r.id for r in latest.values()})

    def add_requirement_clarification(self, project_id, campaign_id, requirement_id, *, request_key, content):
        project_id, campaign_id, requirement_id = map(identifier, (project_id,campaign_id,requirement_id))
        try:
            if type(content) is not str or len(content.encode("utf-8")) > 4000: raise ValueError()
            facts = ingest(project_id,campaign_id,name="Clarification facts",source_type="TEXT",content=content)
            if facts.status != "INGESTED": raise ValueError()
            # Validate key independently, before DB work.
            Clarification(project_id=project_id,campaign_id=campaign_id,requirement_id=requirement_id,
                source_id=requirement_id,request_key=request_key,facts_hash=facts.content_hash,first_fact_line=1)
        except (ValueError,TypeError):
            raise ApplicationError(Code.CLARIFICATION_INVALID) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write":True})
            requirement = self._review_object(uow,project_id,campaign_id,requirement_id,"REQUIREMENT")
            existing = uow.campaign_content.clarification_by_key(campaign_id,request_key)
            if existing is not None:
                if existing.requirement_id != requirement_id or existing.facts_hash != facts.content_hash:
                    raise ApplicationError(Code.REQUIREMENT_REVISION_CONFLICT)
                return ClarificationView.model_validate(existing.model_dump())
            if requirement.review_status != "NEEDS_CLARIFICATION" or not uow.campaign_content.is_current(requirement_id) or uow.campaign_content.version(requirement_id) >= 10:
                raise ApplicationError(Code.REQUIREMENT_REVISION_CONFLICT)
            prior = uow.campaign_content.attempt(requirement.extraction_id)
            original = self._source(uow,project_id,campaign_id,prior.source_id)
            prefix = original.normalized_text + "\n\nClarification for Requirement " + str(requirement_id) + ":\n"
            try:
                combined = ingest(project_id,campaign_id,name="Clarification: " + requirement.key,source_type="TEXT",content=prefix+facts.normalized_text)
            except (ValueError,SourceTooLarge):
                raise ApplicationError(Code.CLARIFICATION_INVALID) from None
            if combined.status != "INGESTED": raise ApplicationError(Code.CLARIFICATION_INVALID)
            combined = type(combined).model_validate({**combined.model_dump(),"purpose":"CLARIFICATION"})
            source = uow.campaign_content.source_by_content(combined)
            if source is None:
                source = combined
                uow.campaign_content.add_source(source)
            # Same evidence under a distinct key cannot create duplicate sources/revision work.
            old = uow.campaign_content.clarification_for_source(source.id)
            if old is not None: raise ApplicationError(Code.REQUIREMENT_REVISION_CONFLICT)
            record = Clarification(project_id=project_id,campaign_id=campaign_id,requirement_id=requirement_id,
                source_id=source.id,request_key=request_key,facts_hash=facts.content_hash,first_fact_line=len(prefix.split("\n")))
            uow.campaign_content.add_clarification(record)
            uow.commit()
            return ClarificationView.model_validate(record.model_dump())

    def get_requirement_history(self,project_id,campaign_id,requirement_id):
        project_id,campaign_id,requirement_id=map(identifier,(project_id,campaign_id,requirement_id))
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            self._review_object(uow,project_id,campaign_id,requirement_id,"REQUIREMENT")
            items=tuple(RequirementHistoryEntry.model_validate(r) for r in uow.campaign_content.revision_history(requirement_id))
            return CollectionPage[RequirementHistoryEntry](items=items,total_returned=len(items),truncated=False)

    def extract_campaign_requirements(self, project_id, campaign_id, source_id) -> ExtractionView:
        return self._extract_attempt(project_id, campaign_id, source_id)

    def retry_campaign_extraction(self, project_id, campaign_id, attempt_id) -> ExtractionView:
        project_id, campaign_id, attempt_id = map(identifier, (project_id, campaign_id, attempt_id))
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._campaign(uow, project_id, campaign_id)
            parent = uow.campaign_content.attempt(attempt_id)
            if parent is None or (parent.project_id, parent.campaign_id) != (project_id, campaign_id):
                raise ApplicationError(Code.EXTRACTION_ATTEMPT_NOT_FOUND)
        return self._extract_attempt(project_id, campaign_id, parent.source_id, parent_attempt_id=attempt_id)

    def list_campaign_extraction_attempts(self, project_id, campaign_id, source_id, *, limit=50):
        project_id, campaign_id, source_id = map(identifier, (project_id, campaign_id, source_id))
        limit = list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._source(uow, project_id, campaign_id, source_id)
            records = uow.campaign_content.attempt_history(source_id, limit)
            outputs = action_outputs(uow.session, records[:limit])
            items = tuple(extraction_view(r, is_latest=i == 0, output=outputs[r.id]) for i,r in enumerate(records[:limit]))
            return CollectionPage[ExtractionView](items=items,total_returned=len(items),truncated=len(records)>limit)

    def _extract_attempt(self, project_id, campaign_id, source_id, *, parent_attempt_id=None):
        project_id, campaign_id, source_id = map(identifier, (project_id, campaign_id, source_id))
        def replay(repo):
            if parent_attempt_id is None:
                existing = repo.extraction_for_source(source_id)
            else:
                parent = repo.attempt(parent_attempt_id)
                if parent is None or parent.source_id != source_id or (parent.project_id,parent.campaign_id) != (project_id,campaign_id):
                    raise ApplicationError(Code.EXTRACTION_ATTEMPT_NOT_FOUND)
                existing = repo.retry_child(parent_attempt_id)
                if existing is None and not extraction_retryable(parent):
                    raise ApplicationError(Code.EXTRACTION_RETRY_NOT_ALLOWED)
            if existing is not None:
                if existing.status == "STARTED":
                    raise ApplicationError(Code.EXTRACTION_RECONCILIATION_REQUIRED if parent_attempt_id is None else Code.EXTRACTION_RETRY_CONFLICT)
                latest = repo.extraction_for_source(source_id, latest=True)
                return extraction_view(existing,is_latest=latest.id == existing.id, output=action_outputs(repo.session, [existing])[existing.id])
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            source = self._source(uow, project_id, campaign_id, source_id)
            existing = replay(uow.campaign_content)
            if existing is not None: return existing
            clarification = uow.campaign_content.clarification_for_source(source_id)
            target = None if clarification is None else uow.campaign_content.requirement(clarification.requirement_id)
            parent = None if parent_attempt_id is None else uow.campaign_content.attempt(parent_attempt_id)
        if source.status != "INGESTED": raise ApplicationError(Code.SOURCE_NOT_INGESTED)
        if self._requirement_extractor is None: raise ApplicationError(Code.EXTRACTION_NOT_CONFIGURED)
        try:
            request = self._requirement_extractor.prepare(source) if target is None else self._requirement_extractor.prepare_revision(source, target, clarification.first_fact_line)
        except ModelError:
            raise ApplicationError(Code.EXTRACTION_CONTEXT_LIMIT) from None
        extraction = RequirementExtraction(project_id=project_id, campaign_id=campaign_id, source_id=source.id,
            source_hash=source.content_hash, model=request.model, parent_attempt_id=parent_attempt_id,
            attempt_number=1 if parent is None else parent.attempt_number+1)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write": True})
            self._source(uow, project_id, campaign_id, source_id)
            existing = replay(uow.campaign_content)
            if existing is not None: return existing
            if clarification is not None and (not uow.campaign_content.is_current(target.id) or uow.campaign_content.version(target.id) >= 10 or uow.campaign_content.active_revision(target.id)):
                raise ApplicationError(Code.REQUIREMENT_REVISION_CONFLICT)
            uow.campaign_content.reserve(extraction)
            uow.commit()
        # No DB transaction is open during provider work. One explicit attempt, no retry loop.
        metadata, error, requirements = None, None, ()
        try:
            response = self._requirement_extractor.extract(request)
            metadata = ModelMetadata.model_validate(response.metadata.model_dump())
            output = validate_output(source, response.parsed_output)
            if clarification is not None:
                if len(output.requirements) != 1 or output.requirements[0].key != target.key:
                    raise ValueError("EXTRACTION_INVALID_OUTPUT")
                if not any(ref.start_line >= clarification.first_fact_line for ref in output.requirements[0].source_references):
                    raise ValueError("EXTRACTION_INVALID_CITATION")
            requirements = tuple(CampaignRequirement(**r.model_dump(), project_id=project_id, campaign_id=campaign_id,
                extraction_id=extraction.id, logical_key=f"REQ-{source.id.hex}-{r.key}",
                id=uuid5(NAMESPACE_URL, f"{source.id}:requirements-v1:{r.key}"),
                review_status=RequirementReviewStatus.NEEDS_CLARIFICATION if r.information_markers else RequirementReviewStatus.READY_FOR_REVIEW)
                for r in output.requirements)
        except ModelError as failure:
            error = failure.code
            try:
                metadata = None if failure.metadata is None else ModelMetadata.model_validate(failure.metadata.model_dump())
            except (AttributeError, ValidationError): metadata = None
        except (ValueError, TypeError) as failure:
            error = "EXTRACTION_INVALID_CITATION" if str(failure) == "EXTRACTION_INVALID_CITATION" else "EXTRACTION_INVALID_OUTPUT"
        except Exception:
            error = "MODEL_UNKNOWN_PROVIDER_ERROR"
        completed = RequirementExtraction.model_validate({**extraction.model_dump(),
            "status": ExtractionStatus.FAILED if error else ExtractionStatus.SUCCEEDED,
            "finished_at": datetime.now(timezone.utc), "error_code": error, "metadata": metadata})
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={"qa_job_write": True})
            uow.campaign_content.finish(completed, () if error else requirements)
            uow.commit()
            return extraction_view(completed, output=action_outputs(uow.session, [completed])[completed.id])

    def import_campaign_tests(self, project_id, campaign_id, *, name, format, content) -> TestImportView:
        project_id,campaign_id=identifier(project_id),identifier(campaign_id)
        try:
            record,cases=parse_import(project_id,campaign_id,name=name,format=format,content=content)
        except SourceTooLarge:
            raise ApplicationError(Code.SOURCE_SIZE_LIMIT) from None
        except (ValueError,TypeError):
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={'qa_job_write':True})
            self._campaign(uow,project_id,campaign_id)
            existing=uow.test_specifications.import_identity(record)
            if existing is not None:return record_view(existing,TestImportView)
            specs=[]
            for case,start,end in cases:
                known,unknown=[],[]
                for ref in case.requirement_refs:
                    requirement=uow.test_specifications.resolve_reference(campaign_id,ref)
                    (unknown if requirement is None else known).append(ref if requirement is None else requirement.id)
                markers=[]
                if unknown:markers.append(TestMarker(kind='UNRESOLVED_REQUIREMENT',description='Supplied references cannot be resolved exactly in this Campaign.'))
                if not known:markers.append(TestMarker(kind='MISSING_TRACEABILITY',description='No known Campaign Requirement is linked.'))
                try:specs.append(canonical_spec(record,case,known,unknown,markers,start,end))
                except (ValueError,TypeError):raise ApplicationError(Code.INVALID_INPUT) from None
            uow.test_specifications.add_import(record,specs)
            result=record_view(record,TestImportView)
            uow.commit()
            return result

    def _test_child(self,uow,project_id,campaign_id,id,kind):
        self._campaign(uow,project_id,campaign_id)
        getter={'import':uow.test_specifications.import_record,'generation':uow.test_specifications.generation,'specification':uow.test_specifications.specification}[kind]
        record=getter(id)
        if record is None:raise ApplicationError(Code.CAMPAIGN_TEST_CHILD_NOT_FOUND)
        if (record.project_id,record.campaign_id)!=(project_id,campaign_id):raise ApplicationError(Code.CAMPAIGN_TEST_CHILD_MISMATCH)
        return record

    def get_campaign_test_import(self,project_id,campaign_id,import_id) -> TestImportDetail:
        project_id,campaign_id,import_id=map(identifier,(project_id,campaign_id,import_id))
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            return record_view(self._test_child(uow,project_id,campaign_id,import_id,'import'),TestImportDetail)

    def list_campaign_test_imports(self,project_id,campaign_id,*,limit=50) -> CollectionPage[TestImportView]:
        project_id,campaign_id,limit=identifier(project_id),identifier(campaign_id),list_limit(limit)
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            self._campaign(uow,project_id,campaign_id)
            return self._operational_page(uow.test_specifications.imports(campaign_id,limit),limit,TestImportView)

    def get_campaign_test_specification(self,project_id,campaign_id,test_spec_id) -> TestSpecificationView:
        project_id,campaign_id,test_spec_id=map(identifier,(project_id,campaign_id,test_spec_id))
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            return record_view(self._test_child(uow,project_id,campaign_id,test_spec_id,'specification'),TestSpecificationView)

    def list_campaign_test_specifications(self,project_id,campaign_id,*,limit=50) -> CollectionPage[TestSpecificationView]:
        project_id,campaign_id,limit=identifier(project_id),identifier(campaign_id),list_limit(limit)
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            self._campaign(uow,project_id,campaign_id)
            return page(uow.test_specifications.specifications(campaign_id,limit),limit,TestSpecificationView)

    def get_campaign_test_generation(self,project_id,campaign_id,generation_id) -> TestGenerationView:
        project_id,campaign_id,generation_id=map(identifier,(project_id,campaign_id,generation_id))
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            record = self._test_child(uow,project_id,campaign_id,generation_id,'generation')
            return generation_view(record, output=action_outputs(uow.session, [record], generation=True)[record.id])

    def list_campaign_test_generations(self,project_id,campaign_id,*,limit=50) -> CollectionPage[TestGenerationView]:
        project_id,campaign_id,limit=identifier(project_id),identifier(campaign_id),list_limit(limit)
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            self._campaign(uow,project_id,campaign_id)
            records=uow.test_specifications.generations(campaign_id,limit)
            outputs = action_outputs(uow.session, records[:limit], generation=True)
            items=tuple(generation_view(r, output=outputs[r.id]) for r in records[:limit])
            return CollectionPage[TestGenerationView](items=items,total_returned=len(items),truncated=len(records)>limit)

    def generate_campaign_tests(self,project_id,campaign_id,*,requirement_ids) -> TestGenerationView:
        project_id,campaign_id=identifier(project_id),identifier(campaign_id)
        if not isinstance(requirement_ids,(list,tuple)) or not 1<=len(requirement_ids)<=20:
            raise ApplicationError(Code.INVALID_INPUT)
        ids=tuple(sorted((identifier(id) for id in requirement_ids),key=str))
        if len(set(ids))!=len(ids):raise ApplicationError(Code.INVALID_INPUT)
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            self._campaign(uow,project_id,campaign_id)
            requirements=[]
            for id in ids:
                requirement=uow.campaign_content.requirement(id)
                if requirement is None:raise ApplicationError(Code.CAMPAIGN_REQUIREMENT_NOT_FOUND)
                if (requirement.project_id,requirement.campaign_id)!=(project_id,campaign_id):raise ApplicationError(Code.CAMPAIGN_REQUIREMENT_MISMATCH)
                if not uow.campaign_content.is_current(requirement.id): raise ApplicationError(Code.REQUIREMENT_REVISION_CONFLICT)
                if requirement.review_status != 'APPROVED':
                    raise ApplicationError(Code.GENERATION_REQUIREMENT_NOT_APPROVED)
                requirements.append(requirement)
            versions,request_hash=generation_identity(requirements)
            existing=uow.test_specifications.generation_identity(campaign_id,request_hash)
            if existing is not None:
                if existing.status=='STARTED':raise ApplicationError(Code.GENERATION_RECONCILIATION_REQUIRED)
                return generation_view(existing, output=action_outputs(uow.session, [existing], generation=True)[existing.id])
        if self._test_generator is None:raise ApplicationError(Code.GENERATION_NOT_CONFIGURED)
        try:request=self._test_generator.prepare(requirements)
        except ModelError:raise ApplicationError(Code.GENERATION_CONTEXT_LIMIT) from None
        attempt=TestGeneration(project_id=project_id,campaign_id=campaign_id,requirement_versions=versions,request_hash=request_hash,model=request.model)
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            uow.session.connection(execution_options={'qa_job_write':True})
            self._campaign(uow,project_id,campaign_id)
            existing=uow.test_specifications.generation_identity(campaign_id,request_hash)
            if existing is not None:
                if existing.status=='STARTED':raise ApplicationError(Code.GENERATION_RECONCILIATION_REQUIRED)
                return generation_view(existing, output=action_outputs(uow.session, [existing], generation=True)[existing.id])
            uow.test_specifications.reserve(attempt);uow.commit()
        # Durable STARTED precedes external work; no transaction spans the one provider call.
        metadata,error,specs=None,None,()
        try:
            response=self._test_generator.generate(request)
            metadata=ModelMetadata.model_validate(response.metadata.model_dump())
            output=validate_generation(requirements,response.parsed_output)
            by_id={r.id:r for r in requirements}
            prepared=[]
            for case in output.tests:
                inherited=[TestMarker(kind=m.kind,description=m.description) for id in case.requirement_ids for m in by_id[id].information_markers]
                prepared.append(canonical_spec(attempt,case,case.requirement_ids,markers=inherited))
            specs=tuple(prepared)
        except ModelError as failure:
            error=failure.code
            try:metadata=None if failure.metadata is None else ModelMetadata.model_validate(failure.metadata.model_dump())
            except (AttributeError,ValidationError):metadata=None
        except (ValueError,TypeError) as failure:
            error='GENERATION_INVALID_LINK' if str(failure)=='GENERATION_INVALID_LINK' else 'GENERATION_INVALID_OUTPUT'
        except Exception:error='MODEL_UNKNOWN_PROVIDER_ERROR'
        completed=TestGeneration.model_validate({**attempt.model_dump(),'status':'FAILED' if error else 'SUCCEEDED',
            'finished_at':datetime.now(timezone.utc),'error_code':error,'metadata':metadata})
        with persistence_boundary(),UnitOfWork(self._factory) as uow:
            uow.test_specifications.finish(completed,() if error else specs);uow.commit()
            return generation_view(completed, output=action_outputs(uow.session, [completed], generation=True)[completed.id])

    def get_operational_summary(self) -> OperationalSummaryView:
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return OperationalSummaryView.model_validate(uow.operations.summary())

    @staticmethod
    def _operational_page(rows, limit, view):
        items = tuple(view.model_validate(row) for row in rows[:limit])
        return CollectionPage[view](items=items, total_returned=len(items), truncated=len(rows) > limit)

    def list_project_operational_summaries(self, *, limit=50) -> CollectionPage[ProjectOperationalSummaryView]:
        limit = list_limit(limit, 100)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return self._operational_page(uow.operations.projects(limit), limit, ProjectOperationalSummaryView)

    def list_task_operational_summaries(self, *, project_id=None, task_state=None,
            execution_status=None, attention=None, reconciliation_attention=None,
            active_only=False, attention_only=False, limit=50) -> CollectionPage[TaskOperationalSummaryView]:
        limit = list_limit(limit, 100)
        project_id = None if project_id is None else identifier(project_id)
        try:
            task_state = None if task_state is None else TaskState(task_state)
            execution_status = None if execution_status is None else JobStatus(execution_status)
            attention = None if attention is None else OperationalAttention(attention)
            if any(type(v) is not bool for v in (active_only, attention_only)) or (
                    reconciliation_attention is not None and type(reconciliation_attention) is not bool):
                raise ValueError
        except (TypeError, ValueError):
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            if project_id is not None:
                self._project(uow, project_id)
            rows = uow.operations.tasks(limit, project_id=project_id, task_state=task_state,
                execution_status=execution_status, attention=attention,
                reconciliation_attention=reconciliation_attention, active_only=active_only, attention_only=attention_only)
            return self._operational_page(rows, limit, TaskOperationalSummaryView)

    def list_operational_activity(self, *, project_id=None, limit=50) -> CollectionPage[OperationalActivityView]:
        limit = list_limit(limit, 100)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            if project_id is not None:
                self._project(uow, project_id)
            return self._operational_page(uow.operations.activity(limit, project_id), limit, OperationalActivityView)

    def create_task(self, *, project_id, title, requirement) -> TaskSummary:
        try:
            command = CreateTask(project_id=project_id, title=title, requirement=requirement)
        except ValidationError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._project(uow, command.project_id)
            task = Task(**command.model_dump())
            uow.tasks.add(task)
            result = task_view(task)
            uow.commit()
            return result

    def get_task(self, task_id, *, project_id=None) -> TaskSummary:
        return self._get_task(task_id, project_id, False)

    def get_task_detail(self, task_id, *, project_id=None) -> TaskDetail:
        return self._get_task(task_id, project_id, True)

    def _get_task(self, task_id, project_id, detail):
        task_id = identifier(task_id)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            return task_view(self._task(uow, task_id, project_id), detail)

    def list_tasks_for_project(self, project_id, *, limit=50) -> CollectionPage[TaskSummary]:
        project_id, limit = identifier(project_id), list_limit(limit)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._project(uow, project_id)
            return page(uow.reads.tasks(project_id, limit), limit, TaskSummary)

    def run_task(self, task_id, *, project_id=None) -> TaskDetail:
        task_id = identifier(task_id)
        admission = self._execution_admission
        with admission.task(task_id) if admission else nullcontext():
            self._assert_execution_available(task_id, getattr(admission, "job_id", None), project_id=project_id)
            self._assert_reconciled(task_id, project_id=project_id)
            return self._run_task(task_id, project_id=project_id)

    def assess_task_reconciliation(self, task_id, *, project_id=None):
        task_id = identifier(task_id)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            task = self._task(uow, task_id, project_id)
            evidence = ReconciliationEvidence(task, tuple(uow.invocations.list_by_task(task_id)),
                tuple(uow.artifacts.list_by_task(task_id)), tuple(uow.history.list_events(task_id)),
                tuple(uow.history.list_test_runs(task_id)), tuple(uow.history.list_errors(task_id)),
                tuple(uow.execution_jobs.list_by_task(task_id, 200)))
        # Detached evidence only. No transaction spans even read-only hash verification.
        return assess(evidence, self._resolver.resolve(task.project_id))

    def _assert_reconciled(self, task_id, *, project_id=None):
        assessment = self.assess_task_reconciliation(task_id, project_id=project_id)
        if assessment.status in {ReconciliationStatus.MANUAL_ACTION_REQUIRED, ReconciliationStatus.INCONSISTENT}:
            raise ApplicationError(Code.TASK_RECONCILIATION_REQUIRED)

    def _assert_execution_available(self, task_id, allowed_job_id=None, *, project_id=None):
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._task(uow, task_id, project_id)
            active = uow.execution_jobs.active(task_id)
            if allowed_job_id is not None and (active is None or active.id != allowed_job_id or active.status != JobStatus.RUNNING):
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            if active is not None and allowed_job_id is None:
                raise ApplicationError(Code.TASK_EXECUTION_ALREADY_ACTIVE)

    def _run_task(self, task_id, *, project_id=None) -> TaskDetail:
        task = self.get_task_detail(task_id, project_id=project_id)
        bundle = self._resolver.resolve(task.project_id)
        # No application transaction survives this point or wraps model/tool calls.
        try:
            runner = WorkflowRunner(self._factory, bundle.runtime, bundle.test_provider,
                workspace_binding=bundle.binding, repository_service=bundle.repository_service,
                mutation_service=bundle.mutation_service)
            runner.run(task.id)
        except Exception:
            # Includes reconciliation and unexpected host failures. Core evidence/state
            # remains authoritative; this boundary never retries or changes it.
            raise ApplicationError(Code.RUNTIME_STOPPED) from None
        return self.get_task_detail(task.id, project_id=task.project_id)

    def resume_task(self, task_id, *, project_id=None) -> TaskDetail:
        task_id = identifier(task_id)
        admission = self._execution_admission
        with admission.task(task_id) if admission else nullcontext():
            self._assert_execution_available(task_id, project_id=project_id)
            return self._resume_task(task_id, project_id=project_id)

    def _resume_task(self, task_id, *, project_id=None) -> TaskDetail:
        task = self.get_task_detail(task_id, project_id=project_id)
        if task.state != TaskState.BLOCKED:
            raise ApplicationError(Code.TASK_NOT_BLOCKED)
        if task.resume_state is None:
            raise ApplicationError(Code.TASK_RESUME_STATE_MISSING)
        # FAILED is a separate terminal command edge from BLOCKED, never a resume.
        if task.resume_state in TERMINAL_STATES or task.resume_state == TaskState.BLOCKED:
            raise ApplicationError(Code.TASK_RESUME_STATE_INVALID)
        self._assert_reconciled(task_id, project_id=project_id)
        try:
            WorkflowEngine(self._factory).transition(task_id=task.id, to_state=task.resume_state,
                reason_code="APPLICATION_RESUME", reason_details="Explicit host continuation",
                trigger="APPLICATION_RESUME")
        except WorkflowError:
            raise ApplicationError(Code.TASK_RESUME_STATE_INVALID) from None
        except Exception:
            raise ApplicationError(Code.RUNTIME_STOPPED) from None
        return self.get_task_detail(task.id, project_id=task.project_id)

    @contextmanager
    def _job_write(self):
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            # Set before the first statement/BEGIN; each lifecycle transaction ends
            # before any workflow call. SQLite serializes these short writer units.
            uow.session.connection(execution_options={"qa_job_write": True})
            yield uow

    def request_task_execution(self, task_id, *, project_id=None) -> ExecutionJobView:
        task_id = identifier(task_id)
        project_id = None if project_id is None else identifier(project_id)
        admission = self._execution_admission
        with admission.submission(task_id) if admission else nullcontext():
            self._assert_execution_available(task_id, project_id=project_id)
            self._assert_reconciled(task_id, project_id=project_id)
            with self._job_write() as uow:
                task = self._task(uow, task_id, project_id)
                if uow.execution_jobs.active(task.id) is not None:
                    raise ApplicationError(Code.TASK_EXECUTION_ALREADY_ACTIVE)
                if task.state in TERMINAL_STATES:
                    raise ApplicationError(Code.TASK_EXECUTION_TERMINAL)
                self._resolver.resolve(task.project_id)  # Lookup only, no execution.
                job = ExecutionJob(task_id=task.id, project_id=task.project_id)
                uow.execution_jobs.add(job)
                uow.commit()
        if self._execution_notify is not None:
            # Wakeup is advisory; the persisted queue is always authoritative.
            try:
                self._execution_notify()
            except Exception:
                pass
        return record_view(job, ExecutionJobView)

    def get_execution_job(self, job_id, *, project_id=None) -> ExecutionJobView:
        job_id = identifier(job_id)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            job = uow.execution_jobs.get(job_id)
            if job is None:
                raise ApplicationError(Code.EXECUTION_JOB_NOT_FOUND)
            self._task(uow, job.task_id, job.project_id)
            if project_id is not None and project_id != job.project_id:
                raise ApplicationError(Code.PROJECT_TASK_MISMATCH)
            return record_view(job, ExecutionJobView)

    def list_task_execution_jobs(self, task_id, *, project_id=None, limit=50) -> CollectionPage[ExecutionJobView]:
        task_id, limit = identifier(task_id), list_limit(limit)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            task = self._task(uow, task_id, project_id)
            jobs = uow.execution_jobs.list_by_task(task_id, limit)
            if any(job.project_id != task.project_id for job in jobs):
                raise ApplicationError(Code.PROJECT_TASK_MISMATCH)
            return page(jobs, limit, ExecutionJobView)

    # Trusted worker operations: no public HTTP route exposes lifecycle writes.
    def claim_next_execution_job(self) -> ExecutionJobView | None:
        with self._job_write() as uow:
            if uow.execution_jobs.running() is not None:
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            job = uow.execution_jobs.next_queued()
            if job is None:
                return None
            self._task(uow, job.task_id, job.project_id)
            job = ExecutionJob.model_validate({**job.model_dump(), "status": JobStatus.RUNNING,
                "started_at": max(datetime.now(timezone.utc), job.created_at)})
            if not uow.execution_jobs.transition(job, JobStatus.QUEUED):
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            uow.commit()
            return record_view(job, ExecutionJobView)

    def finish_execution_job(self, job_id, *, status, safe_error_code=None) -> ExecutionJobView:
        job_id = identifier(job_id)
        with self._job_write() as uow:
            job = uow.execution_jobs.get(job_id)
            if job is None:
                raise ApplicationError(Code.EXECUTION_JOB_NOT_FOUND)
            if job.status != JobStatus.RUNNING:
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            self._task(uow, job.task_id, job.project_id)
            try:
                job = ExecutionJob.model_validate({**job.model_dump(), "status": status,
                    "safe_error_code": safe_error_code, "finished_at": max(datetime.now(timezone.utc), job.started_at)})
            except ValidationError:
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE) from None
            if not uow.execution_jobs.transition(job, JobStatus.RUNNING):
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            uow.commit()
            return record_view(job, ExecutionJobView)

    def reconcile_execution_jobs(self) -> int:
        # Startup only, with exclusive host ownership. Never rerun uncertain work.
        with self._job_write() as uow:
            job = uow.execution_jobs.running()
            if job is None:
                return 0
            job = ExecutionJob.model_validate({**job.model_dump(), "status": JobStatus.STOPPED,
                "safe_error_code": ExecutionJobError.EXECUTION_INTERRUPTED,
                "finished_at": max(datetime.now(timezone.utc), job.started_at)})
            if not uow.execution_jobs.transition(job, JobStatus.RUNNING):
                raise ApplicationError(Code.EXECUTION_JOB_INVALID_STATE)
            uow.commit()
            return 1

    def _records(self, task_id, project_id, limit, query, view):
        task_id, limit = identifier(task_id), list_limit(limit)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._task(uow, task_id, project_id)
            return page(getattr(uow.reads, query)(task_id, limit), limit, view)

    def get_task_artifacts(self, task_id, *, project_id=None, limit=50) -> CollectionPage[ArtifactView]:
        return self._records(task_id, project_id, limit, "artifacts", ArtifactView)

    def get_task_model_usage(self, task_id, *, project_id=None, execution_job_id=None, limit=200) -> TaskModelUsage:
        task_id, limit = identifier(task_id), list_limit(limit)
        project_id = None if project_id is None else identifier(project_id)
        job_id = None if execution_job_id is None else identifier(execution_job_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            task = self._task(uow, task_id, project_id)
            job = None if job_id is None else uow.execution_jobs.get(job_id)
            if job_id is not None and job is None:
                raise ApplicationError(Code.EXECUTION_JOB_NOT_FOUND)
            if job is not None and (job.task_id != task.id or job.project_id != task.project_id):
                raise ApplicationError(Code.PROJECT_TASK_MISMATCH)
            records = uow.reads.invocations(task_id, limit)
            events = uow.reads.model_usage_events(task_id, [i.id for i in records[:limit]], MAX_USAGE_EVENTS)
            return assess_usage(task_id, records[:limit], events[:MAX_USAGE_EVENTS], job=job,
                truncated=len(records) > limit or len(events) > MAX_USAGE_EVENTS)

    def get_task_invocations(self, task_id, *, project_id=None, limit=50) -> CollectionPage[InvocationView]:
        return self._records(task_id, project_id, limit, "invocations", InvocationView)

    def get_task_test_runs(self, task_id, *, project_id=None, limit=50) -> CollectionPage[TestRunView]:
        return self._records(task_id, project_id, limit, "test_runs", TestRunView)

    def get_task_errors(self, task_id, *, project_id=None, limit=50) -> CollectionPage[ErrorView]:
        return self._records(task_id, project_id, limit, "errors", ErrorView)

    def get_task_decisions(self, task_id, *, project_id=None, limit=50) -> CollectionPage[DecisionView]:
        return self._records(task_id, project_id, limit, "decisions", DecisionView)

    def get_task_gate_evaluations(self, task_id, *, project_id=None, limit=50) -> CollectionPage[GateEvaluationView]:
        return self._records(task_id, project_id, limit, "gate_evaluations", GateEvaluationView)

    def get_task_timeline(self, task_id, *, project_id=None, limit=50) -> CollectionPage[TimelineEntry]:
        task_id, limit = identifier(task_id), list_limit(limit, maximum=500)
        project_id = None if project_id is None else identifier(project_id)
        with persistence_boundary(), UnitOfWork(self._factory) as uow:
            self._task(uow, task_id, project_id)
            rows = uow.reads.timeline(task_id, limit)
            items = []
            for index, (event, insertion, instant) in enumerate(rows[:limit]):
                tied = ((index > 0 and rows[index - 1][2] == instant) or
                        (index + 1 < len(rows) and rows[index + 1][2] == instant))
                allowed = {"from_state", "to_state", "reason_code", "error_code", "agent",
                           "status", "attempt", "domain", "turn_index", "tool", "defect_cycle"}
                details = {key: value for key, value in event.payload.items()
                           if key in allowed and isinstance(value, (str, int, bool, type(None)))}
                items.append(TimelineEntry(index=index + 1, insertion_order=insertion,
                    timestamp=event.timestamp, timestamp_tied=tied, event_id=event.id, task_id=event.task_id,
                    category="EVENT", event_type=event.event_type, actor=event.actor,
                    correlation=event.correlation, summary=event.event_type, details=details))
            return CollectionPage[TimelineEntry](items=tuple(items), total_returned=len(items), truncated=len(rows) > limit)
