"""Pure synthetic execution from frozen snapshots, durable results and no fail-fast."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, select, func
from pydantic import ValidationError
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError, QASentinelApplication, ProjectExecutionResolver
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.domain.qa_run import QARunTest, QARun
from qa_sentinel.domain.qa_run_lifecycle import start_run, start_test, finish_test, finish_run, RunLifecycleError
from qa_sentinel.execution.synthetic_run import SyntheticRunExecutor
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from qa_sentinel.persistence.models import Base
from test_qa_runs import ready, review, create
from test_campaign_test_specifications import case, csv_text, seed_requirement


@pytest.fixture
def showcase(ready):
    app, _, _, _, p, c, req, _ = ready
    app.import_campaign_tests(p.id, c.id, name="Showcase", format="CSV", content=csv_text([
        case("SECOND", refs=[str(req.id)]), case("THIRD", refs=[str(req.id)])]))
    for test in app.list_campaign_test_specifications(p.id, c.id).items:
        if test.review_status != "APPROVED": app.review_campaign_test_specification(p.id, c.id, test.id, reviewer_label="qa")
    return ready, create(ready)


def start(ready, run):
    app, _, _, _, p, c, _, _ = ready
    return app.start_qa_run(p.id, c.id, run.id)


def entries(ready, run):
    app, _, _, _, p, c, _, _ = ready
    return app.list_qa_run_tests(p.id, c.id, run.id).items


def test_showcase_frozen_content_fail_continues_durable_results_and_no_legacy(showcase, monkeypatch):
    ready, run = showcase
    app, factory, engine, _, p, c, _, _ = ready
    snapshots = entries(ready, run)
    with UnitOfWork(factory) as uow:
        before = {t.name: uow.session.scalar(select(func.count()).select_from(t)) for t in Base.metadata.tables.values()}
    app.update_campaign(p.id, c.id, name="Later Campaign")
    seed_requirement(factory, p, c, "LATER")
    with engine.begin() as connection:
        connection.execute(text("UPDATE campaign_test_specifications SET title='Changed live design'"))
    from qa_sentinel.persistence.test_specifications import TestSpecificationRepository
    from qa_sentinel.persistence.campaign_review import CampaignReviewRepository
    import subprocess, socket
    from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
    from qa_sentinel.mutation.service import MutationService
    def forbidden(*args, **kwargs): raise AssertionError("Forbidden external/live workflow path")
    for obj, name in [(TestSpecificationRepository, 'specification'), (TestSpecificationRepository, 'specifications'),
        (CampaignReviewRepository, 'readiness_counts'), (subprocess, 'Popen'), (socket.socket, 'connect'),
        (OpenAIModelAdapter, 'generate'), (MutationService, 'apply'), (app._resolver, 'resolve'), (app, 'run_task')]:
        monkeypatch.setattr(obj, name, forbidden)
    calls = []
    class Recording(SyntheticRunExecutor):
        def evaluate(self, snapshot):
            persisted = entries(ready, run)
            assert app.get_qa_run(p.id, c.id, run.id).execution_status == 'RUNNING'
            assert persisted[snapshot.position - 1].execution_status == 'RUNNING'
            assert all(t.execution_status == 'COMPLETED' for t in persisted[:snapshot.position - 1])
            calls.append(snapshot.content)
            return super().evaluate(snapshot)
    app._synthetic_run_executor = Recording()
    result = start(ready, run)
    tests = entries(ready, run)
    assert result.execution_status == 'COMPLETED' and result.qa_outcome == 'FAIL' and result.execution_error_code is None
    assert [t.qa_result for t in tests] == ['PASS', 'FAIL', 'PASS']
    assert all(t.execution_status == 'COMPLETED' for t in tests) and len(calls) == 3
    assert calls == [t.content for t in snapshots]
    for old, new in zip(snapshots, tests):
        assert old.model_dump(exclude={'execution_status','qa_result'}) == new.model_dump(exclude={'execution_status','qa_result'})
    assert result.snapshot_hash == run.snapshot_hash and result.started_at <= result.completed_at
    engine.dispose()
    restarted = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    assert restarted.get_qa_run(p.id, c.id, run.id) == result and restarted.list_qa_run_tests(p.id, c.id, run.id).items == tests
    with UnitOfWork(factory) as uow:
        for table in ('tasks','execution_jobs','invocations','artifacts','events','test_runs'):
            assert uow.session.scalar(select(func.count()).select_from(Base.metadata.tables[table])) == before[table] == 0


@pytest.mark.parametrize('fail_position', [1, 2, 3])
def test_infrastructure_failure_preserves_committed_results_and_stops(showcase, fail_position):
    ready, run = showcase
    app = ready[0]
    class Broken(SyntheticRunExecutor):
        def evaluate(self, snapshot):
            if snapshot.position == fail_position: raise RuntimeError('sensitive credentials and stack text')
            return super().evaluate(snapshot)
    app._synthetic_run_executor = Broken()
    result = start(ready, run)
    tests = entries(ready, run)
    assert result.execution_status == 'FAILED' and result.execution_error_code == 'RUN_EXECUTION_FAILED'
    assert result.qa_outcome == ('PARTIAL' if fail_position > 1 else 'NOT_EVALUATED')
    assert all(t.execution_status == 'COMPLETED' for t in tests[:fail_position-1])
    assert tests[fail_position-1].execution_status == 'RUNNING' and tests[fail_position-1].qa_result == 'NOT_EVALUATED'
    assert all(t.execution_status == 'NOT_STARTED' for t in tests[fail_position:])
    assert 'sensitive' not in result.model_dump_json()
    if fail_position == 3: assert tests[1].qa_result == 'FAIL'
    with pytest.raises(ApplicationError, match='RUN_INVALID_STATE'): start(ready, run)


def test_concurrent_double_start_one_claim_no_duplicate_evaluation(showcase):
    ready, run = showcase
    entered, release = Event(), Event()
    calls = []
    class Paused(SyntheticRunExecutor):
        def evaluate(self, snapshot):
            calls.append(snapshot.id)
            if snapshot.position == 1:
                entered.set()
                assert release.wait(10)
            return super().evaluate(snapshot)
    ready[0]._synthetic_run_executor = Paused()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(start, ready, run)
        try:
            assert entered.wait(10)
            with pytest.raises(ApplicationError, match='RUN_INVALID_STATE'): start(ready, run)
        finally: release.set()
        assert first.result().execution_status == 'COMPLETED'
    assert len(calls) == len(set(calls)) == 3
    with pytest.raises(ApplicationError, match='RUN_INVALID_STATE'): start(ready, run)


@pytest.mark.parametrize('results,expected', [(['PASS'],'PASS'), (['SKIP'],'NOT_EVALUATED'), (['SKIP','PASS','SKIP'],'PASS')])
def test_aggregation_does_not_fabricate_pass_without_pass(showcase, results, expected):
    ready, run = showcase
    class Fixture:
        def evaluate(self, snapshot): return results[(snapshot.position-1) % len(results)]
    ready[0]._synthetic_run_executor = Fixture()
    result = start(ready, run)
    assert result.execution_status == 'COMPLETED' and result.qa_outcome == expected


def test_identical_preparation_new_runs_have_identical_results(showcase):
    ready, first = showcase
    second = create(ready, 'second-run')
    assert first.snapshot_hash == second.snapshot_hash
    start(ready, first); start(ready, second)
    assert [t.qa_result for t in entries(ready, first)] == [t.qa_result for t in entries(ready, second)]


def test_domain_rejects_invalid_pairs_and_terminal_transitions(showcase):
    ready, run = showcase
    test = entries(ready, run)[0]
    for state, outcome in [('NOT_STARTED','PASS'), ('RUNNING','FAIL'), ('COMPLETED','NOT_EVALUATED')]:
        with pytest.raises(ValidationError): QARunTest.model_validate({**test.model_dump(), 'execution_status':state, 'qa_result':outcome})
    with pytest.raises(RunLifecycleError): finish_test(test, 'PASS')
    running = start_test(test); complete = finish_test(running, 'FAIL')
    with pytest.raises(RunLifecycleError): start_test(complete)
    with pytest.raises(RunLifecycleError): finish_test(running, 'NOT_EVALUATED')
    with pytest.raises(RunLifecycleError): finish_run(start_run(run), [running])
    completed = start(ready, run)
    with pytest.raises(RunLifecycleError): start_run(completed)
    with pytest.raises(ValidationError): QARun.model_validate({**run.model_dump(), 'qa_outcome':'PASS'})


def test_api_start_body_scope_safe_failures_and_terminal_rules(showcase):
    ready, run = showcase
    app, _, _, _, p, c, _, _ = ready
    path = f'/api/v1/projects/{p.id}/campaigns/{c.id}/runs/{run.id}/start'
    with TestClient(create_api_app(app)) as client:
        assert client.post(path, json={'target_url':'forbidden'}).status_code == 422
        assert client.post(path, content=b'x'*8193).status_code == 413
        assert client.post(path.replace(str(run.id), str(uuid4()))).json()['error']['code'] == 'RUN_NOT_FOUND'
        response = client.post(path, json={})
        assert response.status_code == 200 and response.json()['execution_status'] == 'COMPLETED' and response.json()['qa_outcome'] == 'FAIL'
        assert client.post(path).json()['error']['code'] == 'RUN_INVALID_STATE'


def test_start_scope_checks_and_corrupt_snapshot_precede_evaluation(showcase):
    ready, run = showcase
    app, _, engine, _, p, c, _, _ = ready
    calls = []
    class Recording(SyntheticRunExecutor):
        def evaluate(self, snapshot):
            calls.append(snapshot.id)
            return super().evaluate(snapshot)
    app._synthetic_run_executor = Recording()
    other_campaign = app.create_campaign(p.id, name="Other Campaign")
    foreign_project = app.create_project(key="foreign", name="Foreign Project")
    foreign_campaign = app.create_campaign(foreign_project.id, name="Foreign Campaign")
    with pytest.raises(ApplicationError, match="RUN_CAMPAIGN_MISMATCH"):
        app.start_qa_run(p.id, other_campaign.id, run.id)
    with pytest.raises(ApplicationError, match="RUN_NOT_FOUND"):
        app.start_qa_run(foreign_project.id, foreign_campaign.id, run.id)
    with engine.begin() as connection:
        connection.execute(text("UPDATE qa_run_tests SET content=json_set(content, '$.title', 'tampered snapshot') WHERE run_id=:id"), {"id":str(run.id)})
    with pytest.raises(ApplicationError, match="PERSISTENCE_ERROR"):
        start(ready, run)
    assert calls == [] and app.get_qa_run(p.id, c.id, run.id).execution_status == 'CREATED'


def test_result_persistence_failure_stops_and_preserves_earlier_result(showcase, monkeypatch):
    ready, run = showcase
    from qa_sentinel.persistence.qa_runs import QARunRepository
    original = QARunRepository.complete_test
    def fail_second(self, current, test, result):
        if test.position == 2: raise RuntimeError('sensitive database exception')
        return original(self, current, test, result)
    monkeypatch.setattr(QARunRepository, 'complete_test', fail_second)
    result = start(ready, run)
    tests = entries(ready, run)
    assert (result.execution_status, result.qa_outcome, result.execution_error_code) == ('FAILED','PARTIAL','RUN_EXECUTION_FAILED')
    assert [(t.execution_status,t.qa_result) for t in tests] == [('COMPLETED','PASS'),('RUNNING','NOT_EVALUATED'),('NOT_STARTED','NOT_EVALUATED')]


def test_api_failure_response_contains_only_safe_code(showcase):
    ready, run = showcase
    app, _, _, _, p, c, _, _ = ready
    class Broken:
        def evaluate(self, snapshot): raise RuntimeError('raw secret runtime exception')
    app._synthetic_run_executor = Broken()
    with TestClient(create_api_app(app)) as client:
        response = client.post(f'/api/v1/projects/{p.id}/campaigns/{c.id}/runs/{run.id}/start')
    assert response.status_code == 200
    assert response.json()['execution_status'] == 'FAILED'
    assert response.json()['execution_error_code'] == 'RUN_EXECUTION_FAILED'
    assert 'secret' not in response.text and 'exception' not in response.text
