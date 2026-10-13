"""Inert preparation composition; no model, browser, source or execution service."""
from sqlalchemy import select
from qa_sentinel.domain.browser_preparation import CreateBrowserPreparation, PreparationError, PreparationSizeError, create_preparation
from qa_sentinel.domain.target import TargetSnapshot
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy
from qa_sentinel.persistence.models import TestSpecificationRow
from qa_sentinel.persistence.preparation_current import current_test
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from .errors import ApplicationError, ApplicationErrorCode as Code


def create(app, project_id, campaign_id, **arguments):
    from .service import identifier, persistence_boundary
    project_id, campaign_id = map(identifier, (project_id, campaign_id))
    try:
        command = CreateBrowserPreparation(**arguments)
    except ValueError:
        raise ApplicationError(Code.INVALID_INPUT) from None
    with persistence_boundary(), UnitOfWork(app._factory) as uow:
        uow.session.connection(execution_options={"qa_job_write": True})
        campaign = app._campaign(uow, project_id, campaign_id)
        if campaign.target_id is None:
            raise ApplicationError(Code.TARGET_NOT_FOUND)
        target = TargetSnapshot.capture(app._target(uow, project_id, campaign.target_id))
        try:
            BrowserExecutionPolicy().validate_target(target)  # Pure static validation, no resolver/SDK.
        except ValueError:
            raise ApplicationError(Code.INVALID_INPUT) from None
        rows = list(uow.session.scalars(select(TestSpecificationRow).where(
            TestSpecificationRow.project_id == str(project_id), TestSpecificationRow.campaign_id == str(campaign_id),
            TestSpecificationRow.id.in_([str(id) for id in command.test_specification_ids]), current_test()).limit(501)))
        if len(rows) != len(command.test_specification_ids):
            raise ApplicationError(Code.RUN_SELECTION_INVALID)
        tests = {test.id: test for test in uow.test_specifications._specs(rows)}
        ordered = [tests[id] for id in command.test_specification_ids]
        if any(not uow.campaign_content.is_current(id) for test in ordered for id in test.requirement_ids):
            raise ApplicationError(Code.RUN_SELECTION_INVALID)
        try:
            selected = uow.campaign_reviews.evidence_batch(ordered, "TEST_SPECIFICATION")
            record = create_preparation(project_id, campaign_id, command, target, selected)
        except PreparationSizeError:
            raise ApplicationError(Code.PREPARATION_SIZE_LIMIT) from None
        except PreparationError as error:
            raise ApplicationError(Code(str(error))) from None
        except ValueError:
            raise ApplicationError(Code.REVIEW_NOT_REVIEWABLE) from None
        existing = uow.browser_preparations.by_key(project_id, campaign_id, command.idempotency_key)
        if existing is not None:
            if existing.selection_hash != record.selection_hash:
                raise ApplicationError(Code.PREPARATION_IDEMPOTENCY_CONFLICT)
            return uow.browser_preparations.view(existing)
        record = uow.browser_preparations.add(record)
        uow.commit()
        return uow.browser_preparations.view(record)


def read(app, project_id, campaign_id, preparation_id):
    from .service import identifier, persistence_boundary
    project_id, campaign_id, preparation_id = map(identifier, (project_id, campaign_id, preparation_id))
    with persistence_boundary(), UnitOfWork(app._factory) as uow:
        app._campaign(uow, project_id, campaign_id)
        record = uow.browser_preparations.get(project_id, campaign_id, preparation_id)
        if record is None:
            raise ApplicationError(Code.PREPARATION_NOT_FOUND)
        return uow.browser_preparations.view(record)
