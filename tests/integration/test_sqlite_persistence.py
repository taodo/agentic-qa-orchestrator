
from uuid import uuid4
import pytest
from sqlalchemy import text, inspect
from sqlalchemy.exc import IntegrityError, StatementError
from qa_sentinel.domain.task import Task
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.database import create_engine,create_session_factory
from qa_sentinel.persistence.models import Base
from qa_sentinel.persistence.records import Requirement,AcceptanceCriterionRecord


def test_migrated_file_roundtrips_all_records(migrated_factory,bundle,store_bundle):
    factory,engine,config=migrated_factory
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    # New engine/connection verifies durable file contents, not identity-map values.
    fresh=create_engine(str(engine.url))
    try:
        with UnitOfWork(create_session_factory(fresh)) as uow:
            assert uow.tasks.get(bundle["task"].id)==bundle["task"]
            assert uow.invocations.get(bundle["invocation"].id)==bundle["invocation"]
            assert uow.artifacts.get(bundle["artifact"].id)==bundle["artifact"]
            for name in ["transition","gate_evaluation","decision","error","event","audit","test_run"]:
                assert getattr(uow.history,"get_"+name)(bundle[name].id)==bundle[name]
            assert uow.requirements.get(bundle["requirement"].id)==bundle["requirement"]
            assert uow.acceptance_criteria.get(bundle["acceptance_criterion"].persistence_id)==bundle["acceptance_criterion"]
            assert uow.failure_fingerprints.get(bundle["failure_fingerprint"].id)==bundle["failure_fingerprint"]
    finally:fresh.dispose()


def test_foreign_keys_are_on_and_invalid_required_reference_rejected(migrated_factory,bundle):
    factory,engine,config=migrated_factory
    with engine.connect() as connection:
        assert connection.scalar(text("PRAGMA foreign_keys"))==1
    orphan=bundle["artifact"].model_copy(update={"task_id":uuid4(),"invocation_id":None})
    with pytest.raises(IntegrityError):
        with UnitOfWork(factory) as uow:
            uow.artifacts.add(orphan)
            # Foreign keys are deferred until commit to permit cyclic references.
            uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.artifacts.get(orphan.id) is None


def test_acceptance_id_scoping_on_migrated_schema(migrated_factory):
    factory,engine,config=migrated_factory
    task_a=Task(title="A",requirement="A")
    task_b=Task(title="B",requirement="B")
    req_a=Requirement(task_id=task_a.id,text="A")
    req_b=Requirement(task_id=task_b.id,text="B")
    a=AcceptanceCriterionRecord(id="AC-1",requirement_id=req_a.id,text="A",verification_method="Assert A")
    b=AcceptanceCriterionRecord(id="AC-1",requirement_id=req_b.id,text="B",verification_method="Assert B")
    with UnitOfWork(factory) as uow:
        uow.tasks.add(task_a);uow.tasks.add(task_b)
        uow.requirements.add(req_a);uow.requirements.add(req_b)
        uow.acceptance_criteria.add(a);uow.acceptance_criteria.add(b);uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.acceptance_criteria.get_by_logical_id(req_a.id,"AC-1")==a
        assert uow.acceptance_criteria.get_by_logical_id(req_b.id,"AC-1")==b
    duplicate=AcceptanceCriterionRecord(id="AC-1",requirement_id=req_a.id,text="dup",verification_method="Assert")
    with pytest.raises(IntegrityError):
        with UnitOfWork(factory) as uow:
            uow.acceptance_criteria.add(duplicate);uow.commit()


def test_nonfinite_json_not_written(migrated_factory,bundle,store_bundle):
    factory,engine,config=migrated_factory
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    original=bundle["artifact"]
    artifact=type(original).model_validate({**original.model_dump(),"id":uuid4(),"content":{"value":float("nan")}})
    with pytest.raises(StatementError):
        with UnitOfWork(factory) as uow:
            uow.artifacts.add(artifact);uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.artifacts.get(artifact.id) is None
