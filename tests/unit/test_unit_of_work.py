import pytest
from sqlalchemy import func, select
from qa_sentinel.persistence.models import Base
from qa_sentinel.persistence.unit_of_work import UnitOfWork


def test_explicit_commit_persists_related_records(factory,bundle,store_bundle):
    with UnitOfWork(factory) as uow:
        store_bundle(uow,bundle);uow.commit()
    with UnitOfWork(factory) as uow:
        assert uow.tasks.get(bundle["task"].id)==bundle["task"]
        assert uow.history.get_event(bundle["event"].id)==bundle["event"]
        assert uow.history.get_transition(bundle["transition"].id)==bundle["transition"]
    with factory() as session:
        for table in Base.metadata.tables.values():
            assert session.scalar(select(func.count()).select_from(table))==1


@pytest.mark.parametrize("mode",["exception","explicit_rollback","no_commit"])
def test_no_partial_records_after_rollback(factory,bundle,store_bundle,mode):
    def write():
        with UnitOfWork(factory) as uow:
            store_bundle(uow,bundle)
            if mode=="exception":raise RuntimeError("abort")
            if mode=="explicit_rollback":uow.rollback()
    if mode=="exception":
        with pytest.raises(RuntimeError,match="abort"):write()
    else:write()
    with factory() as session:
        for table in Base.metadata.tables.values():
            assert session.scalar(select(func.count()).select_from(table))==0
