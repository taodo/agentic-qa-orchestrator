"""Selective immutable Run proving; unrelated ambiguity never blocks selection."""
import base64
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import text
from fastapi.testclient import TestClient
from qa_sentinel.api import create_api_app
from qa_sentinel.application import ApplicationError
from test_campaign_review import review
from test_campaign_test_specifications import seed_requirement,case,csv_text


def approve_selected(review):
    app,_,_,_,p,c,req,test=review
    app.review_campaign_requirement(p.id,c.id,req.id,reviewer_label='qa')
    app.review_campaign_test_specification(p.id,c.id,test.id,reviewer_label='qa')
    return app,p,c,test


def test_selection_runs_without_global_readiness_and_excludes_unselected(review):
    app,p,c,test=approve_selected(review)
    _,factory,_,_,_,_,_,_=review
    seed_requirement(factory,p,c,'UNCLEAR',markers=[dict(kind='AMBIGUITY',description='Missing behavior')])
    assert app.get_campaign_readiness(p.id,c.id).status=='NOT_READY'
    run=app.create_qa_run(p.id,c.id,idempotency_key='selected',test_specification_ids=[test.id])
    assert run.snapshot_version=='qa-run-selection-v2' and run.campaign_snapshot.status=='DRAFT'
    assert run.test_count==run.requirement_count==1
    assert app.list_qa_run_tests(p.id,c.id,run.id).items[0].content.id==test.id
    done=app.start_qa_run(p.id,c.id,run.id)
    assert (done.execution_status,done.qa_outcome)==('COMPLETED','PASS')
    assert app.get_qa_run_results(p.id,c.id,run.id).summary.total==1


@pytest.mark.parametrize('selection',[[],[uuid4()],None])
def test_ineligible_missing_empty_and_legacy_unready_rejected(review,selection):
    app,_,engine,_,p,c,_,_=review
    with pytest.raises(ApplicationError):app.create_qa_run(p.id,c.id,idempotency_key='bad',test_specification_ids=selection)
    with engine.connect() as db:assert db.scalar(text('SELECT count(*) FROM qa_runs'))==0


def test_unapproved_and_duplicate_selection_rejected(review):
    app,_,_,_,p,c,_,test=review
    for ids in [[test.id],[test.id,test.id]]:
        with pytest.raises(ApplicationError):app.create_qa_run(p.id,c.id,idempotency_key='bad',test_specification_ids=ids)


def test_selection_replay_conflict_and_historical_content(review):
    app,p,c,test=approve_selected(review)
    run=app.create_qa_run(p.id,c.id,idempotency_key='key',test_specification_ids=[test.id])
    app.update_campaign(p.id,c.id,name='Changed after capture')
    assert app.create_qa_run(p.id,c.id,idempotency_key='key',test_specification_ids=[test.id])==run
    with pytest.raises(ApplicationError,match='RUN_IDEMPOTENCY_CONFLICT'):
        app.create_qa_run(p.id,c.id,idempotency_key='key',test_specification_ids=[uuid4()])
    assert app.get_qa_run(p.id,c.id,run.id).campaign_snapshot.name==run.campaign_snapshot.name


def test_document_api_is_scoped_inert_and_bounded(review):
    app,_,_,_,p,c,_,_=review
    with TestClient(create_api_app(app)) as client:
        path=f'/api/v1/projects/{p.id}/campaigns/{c.id}/documents'
        body={'name':'spec.md','content_base64':base64.b64encode(b'# Supported cities\r\nHanoi').decode()}
        response=client.post(path,json=body);assert response.status_code==201,response.text
        assert response.json()['source_type']=='MARKDOWN'
        assert client.post(path,json=body).json()['id']==response.json()['id']
        assert client.post(path,json={**body,'name':'../spec.md'}).status_code==422
        assert client.post(path,json={**body,'content_base64':'not-base64'}).status_code==422
        assert client.post(path.replace(str(p.id),str(uuid4())),json=body).status_code==404
        assert app.get_campaign(p.id,c.id).status=='DRAFT'


def test_migration_roundtrip_and_no_audit_erasure(review):
    app,_,engine,config,p,c,_,_=review
    command.check(config)
    command.downgrade(config,'0011');command.upgrade(config,'head');command.check(config)
    with engine.connect() as db:
        assert not db.exec_driver_sql('PRAGMA foreign_key_check').all()
        assert db.scalar(text('SELECT version_num FROM alembic_version'))=='0018'
    app,p,c,test=approve_selected(review)
    app.create_qa_run(p.id,c.id,idempotency_key='v2',test_specification_ids=[test.id])
    with pytest.raises(RuntimeError,match='cannot discard'):command.downgrade(config,'0011')


def test_human_edit_is_versioned_audited_and_requires_new_approval(review):
    from qa_sentinel.domain.campaign_review import content_hash
    from qa_sentinel.domain.test_specification import TestDesign
    from sqlalchemy.exc import IntegrityError
    app,p,c,test=approve_selected(review)
    run=app.create_qa_run(p.id,c.id,idempotency_key='before-edit',test_specification_ids=[test.id])
    original=app.get_campaign_test_specification(p.id,c.id,test.id)
    design={k:v for k,v in original.model_dump().items() if k in TestDesign.model_fields};design['title']='Human corrected title'
    new=app.edit_campaign_test(p.id,c.id,test.id,design=design,previous_hash=content_hash(original),reviewer_label='qa',note='Operator supplied the supported expected result.')
    assert new.id!=original.id and new.review_status=='READY_FOR_REVIEW' and new.provenance.origin=='HUMAN_EDIT'
    assert new.requirement_ids==original.requirement_ids
    assert app.list_campaign_test_specifications(p.id,c.id).items== (new,)
    receipt=app.get_test_edit_evidence(p.id,c.id,new.id)
    assert receipt.previous_id==original.id and receipt.version==2
    assert app.get_campaign_source(p.id,c.id,receipt.source_id).purpose=='TEST_REVIEW'
    assert receipt.source_id not in {s.id for s in app.list_campaign_sources(p.id,c.id,purpose='SPECIFICATION').items}
    assert app.list_campaign_sources(p.id,c.id,purpose='TEST_REVIEW').items[0].id==receipt.source_id
    assert app.get_campaign_test_specification_review(p.id,c.id,original.id).evidence is not None
    with pytest.raises(ApplicationError,match='REVIEW_NOT_REVIEWABLE'):
        app.review_campaign_test_specification(p.id,c.id,original.id,reviewer_label='qa')
    with pytest.raises(ApplicationError,match='REVIEW_CONFLICT'):
        app.edit_campaign_test(p.id,c.id,test.id,design=design,previous_hash=content_hash(original),reviewer_label='qa',note='Stale')
    frozen=app.list_qa_run_tests(p.id,c.id,run.id).items[0]
    assert frozen.content.title==original.title
    app.review_campaign_test_specification(p.id,c.id,new.id,reviewer_label='qa')
    assert app.list_execution_candidates(p.id,c.id).items[0].eligible
    engine=review[2]
    with pytest.raises(IntegrityError):
        with engine.begin() as db:db.execute(text('DELETE FROM campaign_test_edits'))


def test_incomplete_edit_cannot_clear_missing_facts(review):
    from qa_sentinel.domain.campaign_review import content_hash
    from qa_sentinel.domain.test_specification import TestDesign
    app,_,_,_,p,c,_,test=review
    original=app.get_campaign_test_specification(p.id,c.id,test.id)
    design={k:v for k,v in original.model_dump().items() if k in TestDesign.model_fields}
    design.update(overall_expected_result=None,information_markers=[])
    with pytest.raises(ApplicationError,match='INVALID_INPUT'):
        app.edit_campaign_test(p.id,c.id,test.id,design=design,previous_hash=content_hash(original),reviewer_label='qa',note='Cannot invent completeness')


@pytest.mark.parametrize('format',['CSV','XLSX'])
def test_export_is_real_bounded_and_scoped(review,format):
    import csv
    from io import BytesIO,StringIO
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    app,_,_,_,p,c,_,test=review
    result=app.export_campaign_tests(p.id,c.id,test_specification_ids=[test.id],format=format)
    raw=base64.b64decode(result['content_base64'])
    assert result['count']==1 and result['filename'].endswith('.'+format.lower())
    if format=='CSV':
        rows=list(csv.reader(StringIO(raw.decode('utf-8-sig'))));assert len(rows)==2 and rows[0][0]=='Test Case ID'
    else:
        with ZipFile(BytesIO(raw)) as z:
            assert '[Content_Types].xml' in z.namelist()
            assert ET.fromstring(z.read('xl/worksheets/sheet1.xml')).findall('.//{*}row')
            assert b'<f>' not in z.read('xl/worksheets/sheet1.xml')
    for ids in [[uuid4()],[],[test.id,test.id]]:
        with pytest.raises(ApplicationError):app.export_campaign_tests(p.id,c.id,test_specification_ids=ids,format=format)


def test_candidates_and_approvals_are_batched_for_500_tests(review):
    from qa_sentinel.domain.test_specification import CampaignTestSpecification
    from qa_sentinel.domain.campaign_review import ApprovalCommand
    from qa_sentinel.persistence.unit_of_work import UnitOfWork
    from sqlalchemy import event
    app,p,c,test=approve_selected(review)
    factory,engine=review[1:3]
    base=app.get_campaign_test_specification(p.id,c.id,test.id)
    with UnitOfWork(factory) as uow:
        owner=uow.test_specifications.import_record(base.provenance.record_id)
        for start in range(0,500,100):
            records=[CampaignTestSpecification.model_validate({**base.model_dump(),'id':uuid4(),'key':f'CASE_{i:03}', 'logical_key':f'CASE-{i:03}','review_status':'READY_FOR_REVIEW'}) for i in range(start,start+100)]
            uow.test_specifications._add_specs(records,owner)
            for record in records:uow.campaign_reviews.approve(record,'TEST_SPECIFICATION',ApprovalCommand(reviewer_label='qa'))
        uow.commit()
    first=app.list_execution_candidates(p.id,c.id,limit=200)
    second=app.list_execution_candidates(p.id,c.id,limit=200,after_id=first.items[-1].test.id)
    third=app.list_execution_candidates(p.id,c.id,limit=200,after_id=second.items[-1].test.id)
    all_rows=first.items+second.items+third.items
    assert len(all_rows)==501 and len({r.test.id for r in all_rows})==501
    assert all(r.eligible for r in all_rows) and first.truncated and second.truncated and not third.truncated
    calls=[]
    def query(conn,cursor,statement,*args):
        if statement.lstrip().upper().startswith('SELECT'):calls.append(statement)
    event.listen(engine,'before_cursor_execute',query)
    try:
        with TestClient(create_api_app(app)) as client:
            response=client.post(f'/api/v1/projects/{p.id}/campaigns/{c.id}/runs',json={'idempotency_key':'five-hundred','test_specification_ids':[str(r.test.id) for r in all_rows[:500]]})
            assert response.status_code==201,response.text
            assert response.json()['test_count']==500
    finally:event.remove(engine,'before_cursor_execute',query)
    assert len(calls)<40  # Independent of number of selected records, no receipt N+1.


def test_selected_fail_continues_and_evidence_is_atomic(review):
    app,p,c,test=approve_selected(review)
    requirement=review[6]
    for index in range(2):
        app.import_campaign_tests(p.id,c.id,name=f'Case {index}',format='CSV',content=csv_text([case(refs=[str(requirement.id)],key=f'ADDITIONAL_{index}')]))
    tests=app.list_campaign_test_specifications(p.id,c.id).items
    for t in tests:
        if t.review_status!='APPROVED':app.review_campaign_test_specification(p.id,c.id,t.id,reviewer_label='qa')
    run=app.create_qa_run(p.id,c.id,idempotency_key='three',test_specification_ids=[t.id for t in tests])
    done=app.start_qa_run(p.id,c.id,run.id)
    result=app.get_qa_run_results(p.id,c.id,run.id)
    assert (done.execution_status,done.qa_outcome)==('COMPLETED','FAIL')
    assert [t.qa_result for t in app.list_qa_run_tests(p.id,c.id,run.id).items]==['PASS','FAIL','PASS']
    assert result.summary.total==3 and result.summary.completed==3


def test_legacy_run_survives_v2_migration(review):
    from test_campaign_review import approve_all
    app,_,_,config,p,c,_,_=review
    approve_all(review)
    old=app.create_qa_run(p.id,c.id,idempotency_key='legacy')
    command.downgrade(config,'0011');command.upgrade(config,'head')
    assert app.get_qa_run(p.id,c.id,old.id)==old


@pytest.mark.parametrize('format', ['CSV', 'XLSX'])
def test_export_formula_content_is_never_executable(review, format):
    from qa_sentinel.application.test_export import export_tests
    from io import BytesIO
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from qa_sentinel.domain.test_specification import CampaignTestSpecification
    original = review[0].get_campaign_test_specification(review[4].id, review[5].id, review[7].id)
    formula = '=HYPERLINK("https://example.invalid", "not executed")'
    edited = CampaignTestSpecification.model_validate({**original.model_dump(), 'title': formula})
    exported = export_tests([edited], [], format)
    data = base64.b64decode(exported['content_base64'])
    if format == 'CSV':
        import csv
        from io import StringIO
        assert list(csv.reader(StringIO(data.decode('utf-8-sig'))))[1][1] == "'" + formula
    else:
        with ZipFile(BytesIO(data)) as archive:
            sheet = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            assert not sheet.findall('.//{*}f')
            assert sheet.find(".//{*}c[@r='B2']").get('t') == 'inlineStr'
            assert sheet.find(".//{*}c[@r='B2']/{*}is/{*}t").text == formula


def test_cross_project_selection_edit_and_export_are_rejected(review):
    from qa_sentinel.domain.campaign_review import content_hash
    from qa_sentinel.domain.test_specification import TestDesign
    app, p, c, test = approve_selected(review)
    other = app.create_project(key='other', name='Other Project')
    with pytest.raises(ApplicationError):
        app.create_qa_run(other.id, c.id, idempotency_key='wrong-scope', test_specification_ids=[test.id])
    with pytest.raises(ApplicationError):
        app.export_campaign_tests(other.id, c.id, test_specification_ids=[test.id], format='CSV')
    original = app.get_campaign_test_specification(p.id, c.id, test.id)
    design = {k:v for k,v in original.model_dump().items() if k in TestDesign.model_fields}
    with pytest.raises(ApplicationError):
        app.edit_campaign_test(other.id, c.id, test.id, design=design, previous_hash=content_hash(original), reviewer_label='qa', note='Scoped')
    with review[2].connect() as db:
        assert db.scalar(text('SELECT count(*) FROM qa_runs')) == 0
        assert db.scalar(text('SELECT count(*) FROM campaign_test_edits')) == 0



def test_document_list_is_metadata_only_and_coordinates_are_lazy(review):
    from io import BytesIO
    from zipfile import ZipFile
    raw = BytesIO()
    with ZipFile(raw, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Booking dates</w:t></w:r></w:p></w:body></w:document>')
    app, _, _, _, p, c, _, _ = review
    source = app.upload_campaign_document(p.id, c.id, name='spec.docx', content=raw.getvalue())
    assert 'coordinates' not in source.model_dump()['document']
    listed = next(s for s in app.list_campaign_sources(p.id, c.id).items if s.id == source.id)
    assert 'coordinates' not in listed.model_dump()['document']
    assert not hasattr(listed, 'normalized_text')
    detail = app.get_campaign_source(p.id, c.id, source.id)
    assert detail.normalized_text == 'Booking dates'
    assert detail.document.coordinates[0].index == 1



def test_current_test_hash_mismatch_cannot_create_a_human_version(review):
    from qa_sentinel.domain.test_specification import TestDesign
    app, _, engine, _, p, c, _, test = review
    original = app.get_campaign_test_specification(p.id, c.id, test.id)
    design = {k:v for k,v in original.model_dump().items() if k in TestDesign.model_fields}
    with pytest.raises(ApplicationError, match='REVIEW_CONFLICT'):
        app.edit_campaign_test(p.id, c.id, test.id, design=design, previous_hash='0'*64, reviewer_label='qa', note='Stale content')
    assert app.get_campaign_test_specification(p.id, c.id, test.id) == original
    with engine.connect() as db:
        assert db.scalar(text('SELECT count(*) FROM campaign_test_edits')) == 0


def test_downgrade_refuses_to_collapse_distinct_source_provenance(review):
    from qa_sentinel.agents.requirement_extraction import ingest
    from qa_sentinel.persistence.unit_of_work import UnitOfWork
    app, factory, engine, config, p, c, _, _ = review
    one = ingest(p.id, c.id, name='Spec', source_type='TEXT', content='Same bounded content')
    two = type(one).model_validate({**one.model_dump(), 'id':uuid4(), 'purpose':'CLARIFICATION'})
    with UnitOfWork(factory) as uow:
        uow.campaign_content.add_source(one)
        uow.campaign_content.add_source(two)
        uow.commit()
    with pytest.raises(RuntimeError, match='cannot collapse'):
        command.downgrade(config, '0011')
    with engine.connect() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version')) == '0018'
        assert db.scalar(text('SELECT count(*) FROM campaign_sources WHERE content_hash=:hash'), {'hash':one.content_hash}) == 2
