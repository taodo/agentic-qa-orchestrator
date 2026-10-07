import pytest
from sqlalchemy import func, select
from qa_sentinel.domain.execution_job import ExecutionJob
from qa_sentinel.persistence.models import Base
from qa_sentinel.persistence.unit_of_work import UnitOfWork


def test_explicit_commit_persists_related_records(factory,bundle,store_bundle):
    job = ExecutionJob(task_id=bundle["task"].id, project_id=bundle["task"].project_id)
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle)
        uow.execution_jobs.add(job)
        uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(bundle["task"].id)==bundle["task"]
        assert uow.history.get_event(bundle["event"].id)==bundle["event"]
        assert uow.history.get_transition(bundle["transition"].id)==bundle["transition"]
        assert uow.execution_jobs.get(job.id)==job
    with factory() as session:
        for table in Base.metadata.tables.values():
            expected = 0 if table.name in {"campaign_requirement_reviews", "campaign_test_reviews", "qa_campaigns", "campaign_sources", "campaign_requirement_extractions", "campaign_requirements", "campaign_test_imports", "campaign_test_generations", "campaign_test_specifications", "campaign_test_requirement_links"} else 1  # Workflow writes never create a Campaign.
            assert session.scalar(select(func.count()).select_from(table)) == expected


@pytest.mark.parametrize("mode",["exception","explicit_rollback","no_commit"])
def test_no_partial_records_after_rollback(factory,bundle,store_bundle,mode):
    def write():
        with UnitOfWork(factory) as uow:
            store_bundle(uow,bundle)
            uow.execution_jobs.add(ExecutionJob(task_id=bundle["task"].id,
                                                project_id=bundle["task"].project_id))
            if mode=="exception":raise RuntimeError("abort")
            if mode=="explicit_rollback":uow.rollback()
    if mode=="exception":
        with pytest.raises(RuntimeError,match="abort"):write()
    else:write()
    with factory() as session:
        for table in Base.metadata.tables.values():
            assert session.scalar(select(func.count()).select_from(table))==0
