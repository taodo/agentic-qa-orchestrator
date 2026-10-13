"""Checkpoint C: durable mixed batches, authoritative receipts and no browser fallback."""
from uuid import uuid4
import json
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from alembic import command
from qa_sentinel.application import ApplicationError
from qa_sentinel.domain.browser_execution import BrowserRuntimeIdentity,BrowserErrorCode
from qa_sentinel.domain.qa_run_evidence import TestExecutionResult as ExecutionResult,EvidenceDraft
from qa_sentinel.domain.evidence_variants import BrowserObservation
from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy
from qa_sentinel.execution.browser_network import BrowserExecutionError
from qa_sentinel.agents.browser_grounding import BrowserGroundingReasoner
from qa_sentinel.models.base import ModelSettings
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from test_browser_grounding import Observer,model_output,source_free,observation
from test_campaign_test_specifications import case,csv_text


class Runtime:
    identity=BrowserRuntimeIdentity(playwright_version="1.63.0",chromium_revision="1243",browser_version="153.0.8010.12")
    def __init__(self,calls=None,mode="HEADLESS",failure=False):self.calls=[] if calls is None else calls;self.mode=mode;self.failure=failure
    def policy_for(self,target):return BrowserExecutionPolicy()
    def for_mode(self,mode):return Runtime(self.calls,mode,self.failure)
    def execute(self,envelope,run,test):
        self.calls.append((test.content.key,self.mode))
        if self.failure:raise BrowserExecutionError(BrowserErrorCode.LAUNCH)
        matched=test.content.overall_expected_result=="Welcome"
        value=BrowserObservation(category="ASSERTION",run_test_id=test.id,plan_hash=envelope.plan_hash,step_number=2,action="ASSERT_TEXT",matched=matched,outcome="PASS" if matched else "FAIL",browser_version=self.identity.browser_version)
        return ExecutionResult(executor_kind="WEB_BROWSER",qa_result="PASS" if matched else "FAIL",evidence=(EvidenceDraft(source="web-browser",payload=value,summary=value.safe_summary()),))


@pytest.fixture
def batch(source_free,mock_openai):
    data=source_free;app=data[0];p,c=data[4:6]
    values=[]
    for key,action,expected in [("FAIL","Open the public page","Different"),("PASS","Open the public page","Welcome"),("ATTENTION","Click Missing","Welcome")]:
        value=case(key);value.update(title=key,preconditions=[],steps=[dict(index=1,action=action,expected=expected)],overall_expected_result=expected,required_evidence=["Heading assertion"]);values.append(value)
    app.import_campaign_tests(p.id,c.id,name="Canonical imported suite",format="CSV",content=csv_text(values))
    specs=app.list_campaign_test_specifications(p.id,c.id).items
    specs=tuple(next(t for t in specs if t.key==value["key"]) for value in values)
    for spec in specs:app.review_source_free_campaign_test(p.id,c.id,spec.id,reviewer_label="qa")
    def choose(request):
        value=model_output(request)
        if json.loads(request["input"][0]["content"])["approved_test_intent"]["steps"][0]["action"]=="Click Missing":
            value.update(disposition="CANNOT_GROUND",steps=[],reason="GROUNDING_UNAVAILABLE",affected_step=1)
        return value
    mock=mock_openai([choose]*3);runtime=Runtime();observer=Observer()
    app._browser_executor=runtime;app._browser_observer=observer
    app._browser_grounding_reasoner=BrowserGroundingReasoner(OpenAIModelAdapter(client=mock.client),ModelSettings(model="configured-model"))
    return data,specs,mock,runtime,observer


def submit(batch,*,key="batch",ids=None,mode="HEADLESS"):
    data,specs,*_=batch;app=data[0];p,c=data[4:6]
    return app.submit_browser_batch(p.id,c.id,idempotency_key=key,test_specification_ids=ids or tuple(t.id for t in specs),browser_mode=mode)


def execute(batch,view):
    data=batch[0];return data[0].execute_browser_batch(data[4].id,data[5].id,view.id)


def test_mixed_source_free_batch_preserves_all_selection_and_continues_after_fail(batch):
    data,specs,mock,runtime,observer=batch;app=data[0];p,c=data[4:6]
    view=submit(batch)
    assert view.status=="CREATED" and not mock.calls and not observer.calls and not runtime.calls
    assert app.next_browser_batch()==(str(p.id),str(c.id),str(view.id))
    done=execute(batch,view)
    assert done.status=="COMPLETED" and done.run.execution_status=="COMPLETED" and done.run.qa_outcome=="FAIL"
    assert done.summary["selected"]==3 and done.summary["runnable"]==2 and done.summary["needs_attention"]==1
    assert done.summary["passed"]==done.summary["failed"]==1
    assert [i.outcome for i in done.items.items]==["FAIL","PASS","NEEDS_ATTENTION"]
    assert done.items.items[-1].affected_step==1 and done.items.items[-1].hint
    assert [i.test_id for i in done.items.items]==[t.id for t in specs]
    assert runtime.calls==[("FAIL","HEADLESS"),("PASS","HEADLESS")] and len(mock.calls)==len(observer.calls)==3
    assert all(call["tools"]==[] and call["tool_choice"]=="none" for call in mock.calls)
    assert done.run.requirement_count==0 and done.run.snapshot_version=="qa-run-browser-v3" and done.run.preparation_id==done.id
    results=app.get_qa_run_results(p.id,c.id,done.run.id)
    assert results.summary.total==2 and all(t.evidence_count==1 for t in results.tests.items)
    assert all(t.browser_plan.origin=="DETERMINISTIC" for t in results.tests.items)
    assert app.next_browser_batch() is None
    with data[2].connect() as db:
        for table in ("campaign_sources","campaign_requirements","tasks","execution_jobs"):assert db.scalar(text("SELECT count(*) FROM "+table))==0
        assert db.scalar(text("SELECT count(*) FROM browser_batch_plans"))==2
        assert db.scalar(text("SELECT count(*) FROM browser_batch_run_items"))==2
        assert db.execute(text("PRAGMA foreign_key_check")).all()==[]
    assert submit(batch)==done and execute(batch,done)==done
    assert len(mock.calls)==len(observer.calls)==3 and len(runtime.calls)==2


def test_zero_runnable_creates_no_run_or_fake_qa_result(batch):
    data,specs,mock,runtime,_=batch
    view=submit(batch,ids=[specs[2].id]);done=execute(batch,view)
    assert done.status=="COMPLETED" and done.run is None and done.summary["needs_attention"]==1
    assert done.summary["passed"]==done.summary["failed"]==done.summary["total"]==0
    assert done.items.items[0].qa_result is None and not runtime.calls and len(mock.calls)==1
    assert data[0].next_browser_batch() is None


def test_preparation_infrastructure_failure_isolated_from_other_items(batch):
    data,specs,mock,runtime,observer=batch;original=observer.build;calls=[]
    def fail_once(scope):
        calls.append(scope)
        if len(calls)==1:raise BrowserExecutionError(BrowserErrorCode.LAUNCH)
        return original(scope)
    observer.build=fail_once
    done=execute(batch,submit(batch))
    assert done.summary["preparation_errors"]==1 and done.summary["passed"]==1 and done.summary["needs_attention"]==1
    assert done.items.items[0].outcome=="PREPARATION_ERROR" and done.items.items[0].qa_result is None
    assert runtime.calls==[("PASS","HEADLESS")]


def test_system_execution_failure_is_distinct_and_preserves_not_evaluated(batch):
    batch[3].failure=True;done=execute(batch,submit(batch))
    assert done.run.execution_status=="FAILED" and done.run.qa_outcome=="NOT_EVALUATED" and done.run.browser_error_code=="BROWSER_LAUNCH_FAILED"
    assert done.summary["failed"]==0 and done.summary["remaining"]==2
    assert len(batch[3].calls)==1 and done.items.items[-1].outcome=="NEEDS_ATTENTION"


@pytest.mark.parametrize("mode",["HEADLESS","HEADED"])
def test_mode_is_immutable_audited_and_reaches_same_runtime_contract(batch,mode):
    view=submit(batch,mode=mode);done=execute(batch,view)
    assert done.browser_mode==mode and all(call[1]==mode for call in batch[3].calls)
    with UnitOfWork(batch[0][1]) as uow:
        root=uow.browser_preparations.get(done.project_id,done.campaign_id,done.id)
        for item in root.items:
            if item.status=="RUNNABLE":
                receipt=uow.browser_batches.plan(root.project_id,root.campaign_id,root.id,item.id)
                assert receipt.browser_mode==mode and receipt.selection_hash==root.selection_hash
    with pytest.raises(ApplicationError,match="PREPARATION_IDEMPOTENCY_CONFLICT"):submit(batch,mode="HEADLESS" if mode=="HEADED" else "HEADED")


def test_persisted_grounding_is_reloaded_not_trusted_from_return_value(batch,monkeypatch):
    app=batch[0][0];original=app.ground_browser_preparation_item
    def claimed(*args):
        actual=original(*args)
        return actual.model_copy(update={"id":uuid4()})
    monkeypatch.setattr(app,"ground_browser_preparation_item",claimed)
    view=submit(batch)
    with pytest.raises(ApplicationError,match="PERSISTENCE_ERROR"):execute(batch,view)
    current=app.get_browser_batch(view.project_id,view.campaign_id,view.id)
    assert current.run is None and current.reconciliation_required and not batch[3].calls
    with batch[0][2].connect() as db:assert db.scalar(text("SELECT count(*) FROM browser_batch_plans"))==0


def test_started_interruption_never_replays_and_ack_preserves_started_evidence(batch):
    data,_,mock,runtime,observer=batch;view=submit(batch)
    def interrupt(scope):raise KeyboardInterrupt()
    observer.build=interrupt
    with pytest.raises(KeyboardInterrupt):execute(batch,view)
    state=data[0].get_browser_batch(view.project_id,view.campaign_id,view.id)
    assert state.reconciliation_required and state.items.items[0].outcome=="INTERRUPTED"
    with pytest.raises(ApplicationError,match="BROWSER_BATCH_RECONCILIATION_REQUIRED"):execute(batch,view)
    assert data[0].next_browser_batch() is None and not mock.calls and not runtime.calls
    acknowledged=data[0].acknowledge_browser_batch_interruption(view.project_id,view.campaign_id,view.id)
    assert acknowledged.status=="FAILED" and acknowledged.interruption_acknowledged_at is not None
    with data[2].connect() as db:assert db.scalar(text("SELECT status FROM browser_groundings"))=="STARTED"
    assert execute(batch,view)==acknowledged and len(observer.calls)==1


def test_created_sealed_run_resumes_without_reobserving_or_model_calls(batch,monkeypatch):
    app=batch[0][0];view=submit(batch);start=app.start_browser_qa_run
    def pause(*args):raise KeyboardInterrupt()
    monkeypatch.setattr(app,"start_browser_qa_run",pause)
    with pytest.raises(KeyboardInterrupt):execute(batch,view)
    current=app.get_browser_batch(view.project_id,view.campaign_id,view.id)
    assert current.run.execution_status=="CREATED" and not current.reconciliation_required
    before=len(batch[2].calls);monkeypatch.setattr(app,"start_browser_qa_run",start)
    done=execute(batch,view)
    assert done.run.id==current.run.id and done.run.execution_status=="COMPLETED" and len(batch[2].calls)==before


def test_old_inert_preparation_is_not_a_submitted_execution(batch):
    data,specs,*_=batch;app=data[0];p,c=data[4:6]
    old=app.create_browser_preparation(p.id,c.id,idempotency_key="inert",test_specification_ids=[specs[0].id])
    assert app.next_browser_batch() is None
    with pytest.raises(ApplicationError,match="BROWSER_BATCH_NOT_FOUND"):app.get_browser_batch(p.id,c.id,old.id)


def test_scoped_bounded_reads_and_immutable_provenance(batch):
    data,specs,*_=batch;app=data[0];p,c=data[4:6];done=execute(batch,submit(batch))
    first=app.get_browser_batch(p.id,c.id,done.id,limit=1);assert first.items.truncated and len(first.items.items)==1
    second=app.get_browser_batch(p.id,c.id,done.id,limit=1,after_position=first.items.items[0].position);assert second.items.items[0].test_id==specs[1].id
    other=app.create_campaign(p.id,name="Other")
    with pytest.raises(ApplicationError,match="BROWSER_BATCH_NOT_FOUND"):app.get_browser_batch(p.id,other.id,done.id)
    for table in ("browser_batch_submissions","browser_batch_plans","browser_batch_run_items"):
        with pytest.raises(IntegrityError),data[2].begin() as db:db.execute(text("DELETE FROM "+table))
    with pytest.raises(RuntimeError,match="cannot erase"):command.downgrade(data[3],"0017")


@pytest.mark.parametrize("field",["attempt_id","test_hash","target_hash","project_id","campaign_id"])
def test_stale_or_cross_scope_receipt_cannot_materialize(batch,field):
    from qa_sentinel.domain.browser_grounding import GroundingLimitation
    from qa_sentinel.domain.browser_batch import BrowserBatchPlan
    done=execute(batch,submit(batch));data=batch[0]
    with UnitOfWork(data[1]) as uow:
        root=uow.browser_preparations.get(done.project_id,done.campaign_id,done.id);item=root.items[0]
        receipt=uow.browser_batches.plan(root.project_id,root.campaign_id,root.id,item.id)
        value=receipt.model_dump();value["scope"][field]="0"*64 if field.endswith("hash") else uuid4()
        with pytest.raises((ValueError,GroundingLimitation)):
            uow.browser_batches.validate_plan(root,item,BrowserBatchPlan.model_validate(value))


def test_0018_upgrade_downgrade_upgrade_preserves_prior_history(batch):
    data=batch[0];app=data[0];p,c=data[4:6]
    inert=data[0].create_browser_preparation(p.id,c.id,idempotency_key="prior",test_specification_ids=[batch[1][0].id])
    command.downgrade(data[3],"0017");command.upgrade(data[3],"head");command.check(data[3])
    assert data[0].get_browser_preparation(p.id,c.id,inert.id)==inert
    with data[2].connect() as db:assert db.execute(text("PRAGMA foreign_key_check")).all()==[]


def test_immutable_target_snapshot_survives_live_target_edits(batch):
    data,specs,*_=batch;app=data[0];p,c=data[4:6]
    view=submit(batch,ids=[specs[1].id])
    # Operator edits after submission cannot replace the sealed Target.
    app.update_target(p.id,view.target_snapshot.target_id,name="Changed live name",configuration={"base_url":"https://other.example"})
    done=execute(batch,view)
    assert done.target_snapshot==view.target_snapshot and done.run.target_snapshot==view.target_snapshot


def test_manual_browser_operations_share_batch_global_admission(batch):
    from threading import Event,Thread
    from qa_sentinel.host.admission import ExecutionAdmission
    data,specs,mock,runtime,observer=batch;app=data[0];p,c=data[4:6]
    app._execution_admission=ExecutionAdmission()
    entered,release=Event(),Event()
    def reserve():
        with app._execution_admission.enter():entered.set();release.wait(5)
    worker=Thread(target=reserve);worker.start();assert entered.wait(2)
    try:
        with pytest.raises(ApplicationError,match="RUNTIME_STOPPED"):app.start_browser_qa_run(p.id,c.id,uuid4())
        with pytest.raises(ApplicationError,match="RUNTIME_STOPPED"):app.generate_browser_plan(p.id,c.id,specs[0].id)
        assert not mock.calls and not observer.calls and not runtime.calls
    finally:release.set();worker.join(2)
