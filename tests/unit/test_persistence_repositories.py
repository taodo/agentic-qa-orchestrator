from datetime import timedelta
from uuid import UUID, uuid4
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from qa_sentinel.domain.enums import TaskState, AgentInvocationStatus
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence import models
from qa_sentinel.persistence.repositories import ArtifactRepository, HistoryRepository, TaskRepository
from qa_sentinel.persistence.records import Requirement, AcceptanceCriterionRecord


def test_task_roundtrip_and_mutable_save(factory,bundle,store_bundle):
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    with UnitOfWork(factory) as uow:
        task=uow.tasks.get(bundle["task"].id)
        assert task==bundle["task"]
        assert isinstance(task.id,UUID)
        assert task.state is TaskState.CREATED
        task.title="Updated snapshot";task.state=TaskState.PLANNING
        task.resume_state=TaskState.RESEARCHING;task.implementation_attempt+=1
        task.updated_at+=timedelta(seconds=1)
        uow.tasks.save(task);uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(task.id)==task
    assert not hasattr(TaskRepository,"list_by_task")


def test_invocation_lifecycle_save(factory,bundle,store_bundle):
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    with UnitOfWork(factory) as uow:
        invocation=uow.invocations.get(bundle["invocation"].id)
        assert invocation==bundle["invocation"]
        assert invocation.status is AgentInvocationStatus.STARTED
        assert invocation.finished_at is None
        completed=type(invocation).model_validate({**invocation.model_dump(),"status":"COMPLETED",
                                                   "finished_at":invocation.started_at+timedelta(seconds=2)})
        uow.invocations.save(completed);uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.invocations.get(completed.id)==completed
        assert uow.invocations.list_by_task(completed.task_id)==[completed]


def test_artifact_supersession_get_and_list(factory,bundle,store_bundle):
    original=bundle["artifact"]
    replacement=type(original).model_validate({**original.model_dump(),"id":uuid4(),
                                              "content":{"revised":True},"supersedes_artifact_id":original.id})
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.artifacts.add(replacement);uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.artifacts.get(original.id)==original
        assert uow.artifacts.get(replacement.id)==replacement
        assert {r.id for r in uow.artifacts.list_by_task(original.task_id)}=={original.id,replacement.id}
        assert uow.artifacts.list_by_task(uuid4())==[]


def test_history_repository_roundtrips_every_entity(factory,bundle,store_bundle):
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    with UnitOfWork(factory) as uow:
        for name in ["transition","gate_evaluation","decision","error","event","audit","test_run"]:
            original=bundle[name]
            assert getattr(uow.history,"get_"+name)(original.id)==original
            assert getattr(uow.history,"list_"+name+"s")(original.task_id)==[original]
            assert getattr(uow.history,"get_"+name)(uuid4()) is None


@pytest.mark.parametrize("execution,outcome",[("COMPLETED","PASS"),("COMPLETED","FAIL"),("FAILED","UNKNOWN")])
def test_test_run_execution_and_outcome_roundtrip(factory,bundle,store_bundle,execution,outcome):
    original=bundle["test_run"]
    bundle["test_run"]=type(original).model_validate({**original.model_dump(),"execution_status":execution,
                                                    "outcome":outcome})
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    with UnitOfWork(factory) as uow:
        run=uow.history.get_test_run(original.id)
        assert run==bundle["test_run"]
        assert run.execution_status.value==execution
        assert run.outcome.value==outcome


def test_fingerprint_changes_only_occurrence_and_last_seen(factory,bundle,store_bundle):
    original=bundle["failure_fingerprint"]
    later=original.last_seen_at+timedelta(minutes=1)
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.failure_fingerprints.get(original.id)==original
        uow.failure_fingerprints.update_occurrence(original.id,2,later);uow.commit()
    with UnitOfWork(factory) as uow:
        updated=uow.failure_fingerprints.get(original.id)
        assert updated.occurrence_count==2
        assert updated.last_seen_at==later
        assert updated.model_dump(exclude={"occurrence_count","last_seen_at"})==original.model_dump(exclude={"occurrence_count","last_seen_at"})


def test_acceptance_identity_scoped_to_requirement(factory,bundle,store_bundle):
    original=bundle["acceptance_criterion"]
    second_requirement=Requirement(task_id=bundle["task"].id,text="Second requirement")
    second=AcceptanceCriterionRecord(id="AC-1",requirement_id=second_requirement.id,
                                     text="Second criterion",verification_method="Assert second")
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle)
        uow.requirements.add(second_requirement);uow.acceptance_criteria.add(second);uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.requirements.get(second_requirement.id)==second_requirement
        assert uow.acceptance_criteria.get(original.persistence_id)==original
        assert uow.acceptance_criteria.get(second.persistence_id)==second
        assert original.persistence_id!=second.persistence_id
        assert uow.acceptance_criteria.get_by_logical_id(original.requirement_id,"AC-1")==original
        assert uow.acceptance_criteria.get_by_logical_id(second_requirement.id,"AC-1")==second
        assert uow.acceptance_criteria.list_by_requirement(second_requirement.id)==[second]
    duplicate=AcceptanceCriterionRecord(id="AC-1",requirement_id=original.requirement_id,
                                        text="Duplicate",verification_method="Assert duplicate")
    with pytest.raises(IntegrityError):
        with UnitOfWork(factory) as uow:
            uow.acceptance_criteria.add(duplicate);uow.commit()


def test_duplicate_explicit_history_uuid_rejected(factory,bundle,store_bundle):
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    with pytest.raises(IntegrityError):
        with UnitOfWork(factory) as uow:
            uow.history.append_event(bundle["event"]);uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.history.list_events(bundle["task"].id)==[bundle["event"]]


def test_append_only_public_apis_have_no_mutation_methods():
    for cls in [ArtifactRepository,HistoryRepository]:
        public={name for name in dir(cls) if not name.startswith("_")}
        assert not public & {"update","save","delete","remove"}
        assert all(not name.startswith(("update_","save_","delete_","remove_")) for name in public)


def test_exact_enum_strings_in_storage(factory,bundle,store_bundle):
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    with factory() as session:
        assert session.scalar(select(models.TaskRow.state))=="CREATED"
        assert session.scalar(select(models.InvocationRow.status))=="STARTED"
        assert session.scalar(select(models.ArtifactRow.artifact_type))=="IMPLEMENTATION"
        assert session.scalar(select(models.TestRunRow.execution_status))=="COMPLETED"
        assert session.scalar(select(models.TestRunRow.outcome))=="PASS"


def test_missing_reads_and_missing_snapshot_save(factory,bundle):
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(uuid4()) is None
        assert uow.artifacts.get(uuid4()) is None
        assert uow.invocations.get(uuid4()) is None
        with pytest.raises(KeyError):uow.tasks.save(bundle["task"])
        with pytest.raises(KeyError):uow.invocations.save(bundle["invocation"])
