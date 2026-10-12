"""Offline explicit human review, atomicity, scoped traceability and derived readiness."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, event, select, func
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ApplicationError
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.api import create_api_app
from qa_sentinel.persistence.models import Base
from qa_sentinel.persistence.unit_of_work import UnitOfWork
from test_campaign_test_specifications import seed_requirement, case, csv_text


@pytest.fixture
def review(migrated_factory):
    factory, engine, config = migrated_factory
    app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    project = app.create_project(key='review', name='Review')
    campaign = app.create_campaign(project.id, name='Black box QA')
    req = seed_requirement(factory, project, campaign)
    app.import_campaign_tests(project.id, campaign.id, name='Existing test', format='CSV', content=csv_text([case(refs=[str(req.id)])]))
    spec = app.list_campaign_test_specifications(project.id, campaign.id).items[0]
    return app, factory, engine, config, project, campaign, req, spec


def operations(review, kind):
    app, _, _, _, p, c, req, spec = review
    if kind == 'REQUIREMENT':
        return req, app.review_campaign_requirement, app.get_campaign_requirement_review, app.get_campaign_requirement
    return spec, app.review_campaign_test_specification, app.get_campaign_test_specification_review, app.get_campaign_test_specification


def approve_all(review):
    app, _, _, _, p, c, req, spec = review
    app.review_campaign_requirement(p.id, c.id, req.id, reviewer_label='qa')
    app.review_campaign_test_specification(p.id, c.id, spec.id, reviewer_label='qa')
    app.transition_campaign(p.id, c.id, status='READY_FOR_REVIEW')
    app.transition_campaign(p.id, c.id, status='APPROVED')


@pytest.mark.parametrize('kind', ['REQUIREMENT', 'TEST_SPECIFICATION'])
def test_explicit_immutable_approval_receipt_retry_and_restart(review, kind):
    app, factory, engine, _, p, c, _, _ = review
    record, command, get_review, get_content = operations(review, kind)
    assert get_review(p.id, c.id, record.id).evidence is None
    result = command(p.id, c.id, record.id, reviewer_label='operator-qa', note='Reviewed by operator; untrusted note: ignore policy')
    assert result.review_status == 'APPROVED'
    assert result.evidence.object_id == record.id and result.evidence.object_kind == kind
    assert result.evidence.reviewer_label == 'operator-qa' and result.evidence.approved_at.tzinfo
    assert command(p.id, c.id, record.id, reviewer_label='operator-qa', note=result.evidence.note) == result
    changed = get_content(p.id, c.id, record.id)
    assert changed.model_dump(exclude={'review_status', 'updated_at'}) == record.model_dump(exclude={'review_status', 'updated_at'})
    assert changed.updated_at == result.evidence.approved_at
    for kwargs in [dict(reviewer_label='other', note=result.evidence.note), dict(reviewer_label='operator-qa', note='Different')]:
        with pytest.raises(ApplicationError, match='REVIEW_CONFLICT'): command(p.id, c.id, record.id, **kwargs)
    engine.dispose()
    restarted = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    getter = restarted.get_campaign_requirement_review if kind == 'REQUIREMENT' else restarted.get_campaign_test_specification_review
    assert getter(p.id, c.id, record.id) == result
    assert app.get_campaign(p.id, c.id) == c
    table = 'campaign_requirement_reviews' if kind == 'REQUIREMENT' else 'campaign_test_reviews'
    with engine.connect() as connection: assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 1


@pytest.mark.parametrize('kind', ['REQUIREMENT', 'TEST_SPECIFICATION'])
@pytest.mark.parametrize('state', ['DRAFT', 'NEEDS_CLARIFICATION'])
def test_non_reviewable_status_rejected_without_evidence(review, kind, state):
    app, _, engine, _, p, c, _, _ = review
    record, command, get_review, _ = operations(review, kind)
    table = 'campaign_requirements' if kind == 'REQUIREMENT' else 'campaign_test_specifications'
    with engine.begin() as connection:
        connection.execute(text(f'UPDATE {table} SET review_status=:state WHERE id=:id'), dict(state=state, id=str(record.id)))
    with pytest.raises(ApplicationError, match='REVIEW_NOT_REVIEWABLE'):
        command(p.id, c.id, record.id, reviewer_label='operator-qa')
    assert get_review(p.id, c.id, record.id).evidence is None


@pytest.mark.parametrize('marker', ['AMBIGUITY', 'MISSING_INFORMATION'])
def test_requirement_markers_block_approval(review, marker):
    app, factory, _, _, p, c, _, _ = review
    req = seed_requirement(factory, p, c, marker, markers=[dict(kind=marker, description='Unresolved')])
    with pytest.raises(ApplicationError, match='REVIEW_NOT_REVIEWABLE'):
        app.review_campaign_requirement(p.id, c.id, req.id, reviewer_label='operator-qa')
    assert app.get_campaign_readiness(p.id, c.id).clarification_requirements == 1


@pytest.mark.parametrize('problem', ['AMBIGUITY', 'MISSING_INFORMATION', 'unknown', 'unlinked'])
def test_test_blockers_and_missing_traceability_cannot_be_approved(review, problem):
    app, _, _, _, p, c, req, _ = review
    item = case(key='BLOCKED', refs=[] if problem == 'unlinked' else ['UNKNOWN'] if problem == 'unknown' else [str(req.id)])
    if problem in {'AMBIGUITY', 'MISSING_INFORMATION'}: item['information_markers'] = [dict(kind=problem, description='Unresolved')]
    app.import_campaign_tests(p.id, c.id, name='Blocked', format='CSV', content=csv_text([item]))
    spec = next(s for s in app.list_campaign_test_specifications(p.id, c.id).items if s.key == 'BLOCKED')
    with pytest.raises(ApplicationError, match='REVIEW_NOT_REVIEWABLE'):
        app.review_campaign_test_specification(p.id, c.id, spec.id, reviewer_label='operator-qa')
    assert app.get_campaign_test_specification_review(p.id, c.id, spec.id).evidence is None


@pytest.mark.parametrize('kind', ['REQUIREMENT', 'TEST_SPECIFICATION'])
@pytest.mark.parametrize('different_intent', [False, True])
def test_concurrent_approvals_one_receipt_and_explicit_conflict(review, kind, different_intent):
    app, _, engine, _, p, c, _, _ = review
    record, command, getter, _ = operations(review, kind)
    barrier = Barrier(2)
    def run(index):
        barrier.wait(timeout=10)
        try: return command(p.id, c.id, record.id, reviewer_label='second' if different_intent and index else 'first')
        except ApplicationError as error: return error.code.value
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(run, [0, 1]))
    if different_intent: assert sum(r == 'REVIEW_CONFLICT' for r in results) == 1
    else: assert results[0] == results[1]
    table = 'campaign_requirement_reviews' if kind == 'REQUIREMENT' else 'campaign_test_reviews'
    with engine.connect() as connection: assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 1
    assert getter(p.id, c.id, record.id).review_status == 'APPROVED'


@pytest.mark.parametrize('kind', ['REQUIREMENT', 'TEST_SPECIFICATION'])
def test_failed_commit_rolls_back_status_and_receipt(review, monkeypatch, kind):
    _, _, _, _, p, c, _, _ = review
    record, command, getter, get_content = operations(review, kind)
    def fail(*args): raise RuntimeError('Synthetic persistence failure')
    monkeypatch.setattr(UnitOfWork, 'commit', fail)
    with pytest.raises(ApplicationError, match='PERSISTENCE_ERROR'): command(p.id, c.id, record.id, reviewer_label='qa')
    assert get_content(p.id, c.id, record.id).model_dump() == record.model_dump() and getter(p.id, c.id, record.id).evidence is None


def test_coverage_progression_and_approved_campaign_can_be_not_ready(review):
    app, _, _, _, p, c, req, spec = review
    before = app.get_campaign_traceability(p.id, c.id)
    assert before.requirements.items[0].coverage == 'PARTIAL'
    assert before.requirements.items[0].linked_test_review_states == {'READY_FOR_REVIEW': 1}
    app.transition_campaign(p.id, c.id, status='READY_FOR_REVIEW');app.transition_campaign(p.id, c.id, status='APPROVED')
    assert app.get_campaign_readiness(p.id, c.id).status == 'NOT_READY'
    app.review_campaign_test_specification(p.id, c.id, spec.id, reviewer_label='qa')
    trace = app.get_campaign_traceability(p.id, c.id)
    assert trace.requirements.items[0].coverage == 'COVERED' and trace.requirements.items[0].approved_test_count == 1
    assert trace.requirements.items[0].review_status == 'READY_FOR_REVIEW'
    assert trace.links.items[0].test_spec_id == spec.id
    assert app.get_campaign_readiness(p.id, c.id).status == 'NOT_READY'
    app.review_campaign_requirement(p.id, c.id, req.id, reviewer_label='qa')
    ready = app.get_campaign_readiness(p.id, c.id)
    assert ready.status == 'READY' and ready.blocker_codes == ()
    assert ready.covered_requirements == ready.total_requirements == ready.approved_requirements == 1
    assert app.get_campaign(p.id, c.id).status == 'APPROVED'


def test_empty_campaign_and_no_generated_tests_are_gaps(review):
    app, factory, _, _, p, _, _, _ = review
    c = app.create_campaign(p.id, name='Empty')
    app.transition_campaign(p.id, c.id, status='READY_FOR_REVIEW');app.transition_campaign(p.id, c.id, status='APPROVED')
    empty = app.get_campaign_readiness(p.id, c.id)
    assert empty.status == 'NOT_READY' and empty.blocker_codes == ('NO_REQUIREMENTS', 'NO_TEST_SPECIFICATIONS')
    req = seed_requirement(factory, p, c)
    app.review_campaign_requirement(p.id, c.id, req.id, reviewer_label='qa')
    assert app.get_campaign_traceability(p.id, c.id).requirements.items[0].coverage == 'NOT_COVERED'
    assert 'REQUIREMENT_COVERAGE_GAP' in app.get_campaign_readiness(p.id, c.id).blocker_codes
    app.import_campaign_tests(p.id, c.id, name='Unlinked', format='CSV', content=csv_text([case()]))
    assert app.get_campaign_readiness(p.id, c.id).uncovered_requirements == 1
    assert app.get_campaign_traceability(p.id, c.id).links.items == ()


def test_campaign_explicit_approval_required_and_blocked_extras_do_not_fake_coverage(review):
    app, _, _, _, p, c, req, spec = review
    app.review_campaign_requirement(p.id, c.id, req.id, reviewer_label='qa')
    app.review_campaign_test_specification(p.id, c.id, spec.id, reviewer_label='qa')
    assert app.get_campaign_readiness(p.id, c.id).blocker_codes == ('CAMPAIGN_NOT_APPROVED',)
    blocked = case('EXTRA', refs=[str(req.id)]);blocked['information_markers'] = [dict(kind='AMBIGUITY', description='Unknown')]
    app.import_campaign_tests(p.id, c.id, name='Extra', format='CSV', content=csv_text([blocked]))
    approve_all(review)
    assert app.get_campaign_readiness(p.id, c.id).status == 'READY'
    row = app.get_campaign_traceability(p.id, c.id).requirements.items[0]
    assert row.linked_test_count == 2 and row.approved_test_count == 1 and row.coverage == 'COVERED'


def test_traceability_bounded_but_readiness_uses_all_persisted_requirements(review):
    app, factory, _, _, p, c, _, _ = review
    approve_all(review)
    for index in range(3): seed_requirement(factory, p, c, f'R{index}')
    a = app.get_campaign_traceability(p.id, c.id, limit=1)
    assert len(a.requirements.items) == 1 and a.requirements.truncated
    assert app.get_campaign_traceability(p.id, c.id, limit=1) == a
    result = app.get_campaign_readiness(p.id, c.id)
    assert result.total_requirements == 4 and result.uncovered_requirements == 3 and result.status == 'NOT_READY'
    for limit in (0, 201, True):
        with pytest.raises(ApplicationError, match='INVALID_LIST_LIMIT'): app.get_campaign_traceability(p.id, c.id, limit=limit)


@pytest.mark.parametrize('kind', ['REQUIREMENT', 'TEST_SPECIFICATION'])
def test_review_and_reads_are_scoped_and_unknown_ids_rejected(review, kind):
    app, _, _, _, p, c, _, _ = review
    record, command, getter, _ = operations(review, kind)
    p2 = app.create_project(key='other', name='Other');c2 = app.create_campaign(p2.id, name='Other')
    c3 = app.create_campaign(p.id, name='Sibling')
    suffix = 'CAMPAIGN_REQUIREMENT_MISMATCH' if kind == 'REQUIREMENT' else 'CAMPAIGN_TEST_CHILD_MISMATCH'
    for project, campaign, code in [(p2.id, c.id, 'PROJECT_CAMPAIGN_MISMATCH'), (p2.id, c2.id, suffix), (p.id, c3.id, suffix)]:
        with pytest.raises(ApplicationError, match=code): command(project, campaign, record.id, reviewer_label='qa')
        with pytest.raises(ApplicationError, match=code): getter(project, campaign, record.id)
    for method in (app.get_campaign_readiness, app.get_campaign_traceability):
        with pytest.raises(ApplicationError, match='PROJECT_CAMPAIGN_MISMATCH'): method(p2.id, c.id)
    with pytest.raises(ApplicationError, match='NOT_FOUND'): getter(p.id, c.id, uuid4())


def test_zero_external_actions_read_only_visibility_and_unchanged_usage(review, monkeypatch):
    app, factory, engine, _, p, c, req, spec = review
    usage_before = app.get_campaign_model_usage(p.id, c.id)
    def forbidden(*args, **kwargs): raise AssertionError('Review cannot do external work')
    monkeypatch.setattr(app._resolver, 'resolve', forbidden)
    import subprocess
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    for cls, method in [('qa_sentinel.models.openai_adapter.OpenAIModelAdapter', 'generate'),
                        ('qa_sentinel.execution.service.TestExecutionService', 'execute'),
                        ('qa_sentinel.repository.service.RepositoryReadService', 'execute')]:
        monkeypatch.setattr(cls + '.' + method, forbidden)
    monkeypatch.setattr('qa_sentinel.mutation.service.MutationService.__init__', forbidden)
    approve_all(review)
    before = {}
    with UnitOfWork(factory) as uow:
        before = {t.name: uow.session.scalar(select(func.count()).select_from(t)) for t in Base.metadata.tables.values()}
    writes = []
    def record_sql(conn, cursor, statement, parameters, context, many):
        if statement.split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP'}: writes.append(statement)
    event.listen(engine, 'before_cursor_execute', record_sql)
    try:
        app.get_campaign_readiness(p.id, c.id);app.get_campaign_traceability(p.id, c.id)
        app.get_campaign_requirement_review(p.id, c.id, req.id);app.get_campaign_test_specification_review(p.id, c.id, spec.id)
    finally: event.remove(engine, 'before_cursor_execute', record_sql)
    assert not writes and app.get_campaign_model_usage(p.id, c.id) == usage_before
    with UnitOfWork(factory) as uow:
        after = {t.name: uow.session.scalar(select(func.count()).select_from(t)) for t in Base.metadata.tables.values()}
    assert after == before
    assert all(after[name] == 0 for name in ('tasks', 'execution_jobs', 'invocations', 'events', 'artifacts', 'test_runs'))


@pytest.mark.parametrize('body', [{}, {'reviewer_label': ''}, {'reviewer_label': 'x'*65}, {'reviewer_label': 'unsafe\nlabel'},
    {'reviewer_label': 'qa', 'note': 'x'*1001}, {'reviewer_label': 'qa', 'action': 'REJECT'}, {'reviewer_label': 'qa', 'status': 'APPROVED'}])
def test_api_review_input_is_bounded_explicit_and_safe(review, body):
    app, _, _, _, p, c, req, _ = review
    with TestClient(create_api_app(app)) as client:
        response = client.post(f'/api/v1/projects/{p.id}/campaigns/{c.id}/requirements/{req.id}/review', json=body)
        assert response.status_code == 422 and set(response.json()) == {'error'}
    assert app.get_campaign_requirement_review(p.id, c.id, req.id).evidence is None


def test_api_review_and_read_models_roundtrip(review):
    app, _, _, _, p, c, req, spec = review
    prefix = f'/api/v1/projects/{p.id}/campaigns/{c.id}'
    with TestClient(create_api_app(app)) as client:
        for path in (f'/requirements/{req.id}/review', f'/test-specifications/{spec.id}/review'):
            assert client.get(prefix+path).json()['evidence'] is None
            response = client.post(prefix+path, json={'reviewer_label': 'qa-human', 'note': '<script>untrusted</script>'})
            assert response.status_code == 200 and response.json()['evidence']['reviewer_label'] == 'qa-human'
            assert client.get(prefix+path).json() == response.json()
            assert client.post(prefix+path, json={'reviewer_label': 'qa-human', 'note': '<script>untrusted</script>'}).json() == response.json()
            conflict = client.post(prefix+path, json={'reviewer_label': 'someone-else'})
            assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'REVIEW_CONFLICT'
        assert client.get(prefix+'/traceability').json()['requirements']['items'][0]['coverage'] == 'COVERED'
        assert client.get(prefix+'/traceability?limit=201').status_code == 422
        assert client.get(prefix+'/readiness').json()['status'] == 'NOT_READY'
        assert client.get(prefix+'/requirements/'+str(req.id)).json()['review_status'] == 'APPROVED'
        assert client.get(prefix+'/test-specifications/'+str(spec.id)).json()['review_status'] == 'APPROVED'


def test_links_are_bounded_counts_are_complete_and_new_content_invalidates_readiness(review):
    app, factory, _, _, p, c, req, _ = review
    approve_all(review)
    for index in range(3):
        app.import_campaign_tests(p.id, c.id, name='More', format='CSV', content=csv_text([case(f'T{index}', refs=[str(req.id)])]))
    trace = app.get_campaign_traceability(p.id, c.id, limit=1)
    assert trace.links.truncated and len(trace.links.items) == 1
    assert trace.requirements.items[0].linked_test_count == 4 and trace.requirements.items[0].approved_test_count == 1
    assert app.get_campaign_readiness(p.id, c.id).status == 'READY'
    added = seed_requirement(factory, p, c, 'NEW')
    ready = app.get_campaign_readiness(p.id, c.id)
    assert ready.status == 'NOT_READY' and ready.uncovered_requirements == 1
    assert app.get_campaign_requirement_review(p.id, c.id, added.id).evidence is None
    assert app.get_campaign(p.id, c.id).status == 'APPROVED'


@pytest.mark.parametrize('kind', ['REQUIREMENT', 'TEST_SPECIFICATION'])
def test_stale_approval_hash_is_never_overwritten_or_accepted_on_retry(review, kind):
    _, _, engine, _, p, c, _, _ = review
    record, command, getter, _ = operations(review, kind)
    result = command(p.id, c.id, record.id, reviewer_label='qa')
    table = 'campaign_requirements' if kind == 'REQUIREMENT' else 'campaign_test_specifications'
    with engine.begin() as connection: connection.execute(text(f'UPDATE {table} SET title=:title WHERE id=:id'), dict(title='Unauthorized changed content', id=str(record.id)))
    for call in [lambda: getter(p.id,c.id,record.id), lambda: command(p.id,c.id,record.id,reviewer_label='qa')]:
        with pytest.raises(ApplicationError, match='REVIEW_EVIDENCE_INVALID'): call()
    review_table = 'campaign_requirement_reviews' if kind == 'REQUIREMENT' else 'campaign_test_reviews'
    with engine.connect() as connection:
        assert connection.scalar(text(f'SELECT content_hash FROM {review_table}')) == result.evidence.content_hash


@pytest.mark.parametrize('kind', ['REQUIREMENT', 'TEST_SPECIFICATION'])
@pytest.mark.parametrize('corruption', ['missing_receipt', 'unresolved_marker'])
def test_missing_audit_or_corrupt_approved_blockers_cannot_claim_ready(review, kind, corruption):
    app, _, engine, _, p, c, req, spec = review
    approve_all(review)
    table = 'campaign_requirement_reviews' if kind == 'REQUIREMENT' else 'campaign_test_reviews'
    with engine.begin() as connection:
        if corruption == 'missing_receipt': connection.execute(text(f'DELETE FROM {table}'))
        else:
            child = 'campaign_requirements' if kind == 'REQUIREMENT' else 'campaign_test_specifications'
            connection.execute(text(f"UPDATE {child} SET information_markers='[{{\"kind\":\"AMBIGUITY\",\"description\":\"Unresolved\"}}]' WHERE review_status='APPROVED'"))
    result = app.get_campaign_readiness(p.id, c.id)
    assert result.status == 'NOT_READY'
    assert ('INVALID_REQUIREMENT_APPROVAL' if kind == 'REQUIREMENT' else 'INVALID_TEST_APPROVAL') in result.blocker_codes
    if kind == 'TEST_SPECIFICATION': assert app.get_campaign_traceability(p.id, c.id).requirements.items[0].coverage == 'PARTIAL'


def test_import_generation_repository_cannot_auto_approve(review):
    app, factory, _, _, p, c, req, spec = review
    with UnitOfWork(factory) as uow:
        imported = uow.test_specifications.import_record(spec.provenance.record_id)
        with pytest.raises(ValueError, match='cannot approve'):
            uow.test_specifications._add_specs([type(spec).model_validate({**spec.model_dump(), 'review_status': 'APPROVED'})], imported)
    assert app.get_campaign_test_specification_review(p.id, c.id, spec.id).evidence is None


def test_requirement_extraction_repository_cannot_auto_approve(review, monkeypatch):
    app, factory, _, _, p, c, _, _ = review
    from qa_sentinel.persistence.campaign_content import CampaignContentRepository
    original = CampaignContentRepository.finish
    def attempted_approval(repository, extraction, requirements=()):
        approved = [type(r).model_validate({**r.model_dump(), 'review_status': 'APPROVED'}) for r in requirements]
        return original(repository, extraction, approved)
    monkeypatch.setattr(CampaignContentRepository, 'finish', attempted_approval)
    with pytest.raises(ValueError, match='cannot approve'): seed_requirement(factory, p, c, 'NEW')
    assert app.list_campaign_requirements(p.id, c.id).total_returned == 1


def test_oversized_review_body_is_rejected_before_json_parsing(review):
    app, _, _, _, p, c, req, _ = review
    with TestClient(create_api_app(app)) as client:
        result = client.post(f'/api/v1/projects/{p.id}/campaigns/{c.id}/requirements/{req.id}/review', content=b'x'*8193,
            headers={'content-type':'application/json'})
        assert result.status_code == 413 and result.json()['error']['code'] == 'REVIEW_SIZE_LIMIT'
