"""Architecture boundary regressions for the closed reviewed evidence policy."""
import ast
from pathlib import Path
import pytest
from pydantic import ValidationError
from qa_sentinel.domain.qa_run_evidence import EvidenceDraft, TestExecutionResult as ResultContract
from qa_sentinel.domain.evidence_variants import (
    SyntheticObservation, evidence_policy, EvidencePresentation, MAX_EVIDENCE_DETAILS,
)
from qa_sentinel.domain.campaign_content import Frozen


def test_closed_discriminated_schema_and_unknown_variants_fail_closed():
    schema=EvidenceDraft.model_json_schema()['properties']['payload']
    assert schema['discriminator']['propertyName']=='variant'
    assert set(schema['discriminator']['mapping'])=={'synthetic-observation-v1'}
    assert len(schema['oneOf'])==1
    class Unreviewed(Frozen): pass
    with pytest.raises(ValueError,match='Unregistered'): evidence_policy(Unreviewed())
    payload=SyntheticObservation(position=1,outcome='PASS')
    data=dict(source='synthetic',payload=payload,summary=payload.safe_summary())
    with pytest.raises(ValidationError): EvidenceDraft(**{**data,'payload':Unreviewed()})
    for change in [{'source':'unreviewed'},{'kind':'UNREVIEWED'},{'schema_version':'unreviewed'},
                   {'payload':{'variant':'unreviewed'}},{'payload':{'variant':None}},{'payload':{'variant':[]}},{'payload':{}}, {'presentation':{'display_label':'INJECTED'}}]:
        with pytest.raises(ValidationError): EvidenceDraft(**{**data,**change})
    forged=EvidenceDraft(**data).model_copy(update={'source':'unreviewed'})
    with pytest.raises(ValidationError): ResultContract(qa_result='PASS',evidence=(forged,))


def test_generic_domain_repository_and_ui_have_no_synthetic_field_assumptions():
    root=Path(__file__).resolve().parents[2]
    domain=root/'src/qa_sentinel/domain/qa_run_evidence.py'
    tree=ast.parse(domain.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node,ast.Attribute): assert node.attr not in {'position','outcome','strategy'}
    repo=ast.parse((root/'src/qa_sentinel/persistence/qa_runs.py').read_text(encoding='utf-8'))
    complete=next(node for node in ast.walk(repo) if isinstance(node,ast.FunctionDef) and node.name=='complete_test')
    assert not any(isinstance(node,ast.Attribute) and node.attr in {'position','outcome','strategy'} for node in ast.walk(complete))
    for name in ['RunResultsTable.tsx','RunEvidenceRecord.tsx']:
        source=(root/'frontend/src/components'/name).read_text(encoding='utf-8')
        assert 'SYNTHETIC' not in source and '.payload' not in source


def test_presentation_projection_is_frozen_bounded_and_closed():
    policy=evidence_policy(SyntheticObservation(position=1,outcome='FAIL'))
    projection=policy.presentation(SyntheticObservation(position=1,outcome='FAIL'))
    with pytest.raises(ValidationError): projection.display_label='Changed'
    with pytest.raises(ValidationError): EvidencePresentation(**{**projection.model_dump(),'details':projection.details*(MAX_EVIDENCE_DETAILS+1)})
    with pytest.raises(ValidationError): EvidencePresentation(**{**projection.model_dump(),'authorization':'secret'})
