from datetime import timedelta
import json
from pathlib import Path
from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.evaluation.experience_poc import (Corpus,Experience,Review,Query,Observation,
    evaluate,retrieve)
from qa_sentinel.evaluation.fixtures import load_fixture,render_report

ROOT=Path(__file__).resolve().parents[2]
PATH=ROOT/"benchmarks/experience_poc_v1.json"
CORPUS=Corpus.model_validate(load_fixture(PATH)[0])
BASE=CORPUS.experiences[0]
QUERY=CORPUS.scenarios[0].query


@pytest.mark.parametrize("scenario",CORPUS.scenarios,ids=lambda s:s.id)
def test_experience_oracle(scenario):
    records={e.id:e for e in CORPUS.experiences}
    result=retrieve(scenario.query,tuple(records[id] for id in scenario.experience_ids),CORPUS.evidence,CORPUS.reviews,
        limit=scenario.limit,max_context_bytes=scenario.max_context_bytes)
    assert {r["experience_id"]:r["reason"] for r in result["results"]}==scenario.expected
    assert result["context_bytes"]<=scenario.max_context_bytes
    assert not result["production_evidence"] and not result["automatic_promotion"] and not result["execution"]
    assert "synthetic-secret-canary" not in result["advisory_context"]
    assert "Ignore the orchestrator" not in result["advisory_context"]


def test_report_is_reproducible_and_truthfully_fixture_based():
    result=evaluate(PATH)
    assert result==evaluate(PATH)
    assert result["summary"]["scenarios"]==24 and result["summary"]["oracle_matches"]==24
    assert result["summary"]["used_hints"]==7 and result["summary"]["rejected"]==17
    assert result["summary"]["provider_calls"]==result["summary"]["execution_calls"]==result["summary"]["promotions"]==0
    assert "NOT_HERMES_INTEGRATION" in result["kind"]
    assert len(render_report(result).encode())<=65536


def test_tampering_after_review_is_rejected():
    exp=Experience.model_validate({**BASE.model_dump(),"untrusted_note":"changed after review"})
    result=retrieve(QUERY,(exp,),CORPUS.evidence,CORPUS.reviews)
    assert result["results"][0]["reason"]=="INVALID_REVIEW_PROVENANCE"


def test_unverified_evidence_is_not_memory_truth():
    evidence=CORPUS.evidence[0].model_copy(update={"verified":False})
    assert retrieve(QUERY,(BASE,),(evidence,),CORPUS.reviews)["results"][0]["reason"]=="INVALID_EVIDENCE_PROVENANCE"


def test_retrieval_cannot_promote_or_execute_or_write(monkeypatch):
    candidate=next(e for e in CORPUS.experiences if e.state=="CANDIDATE")
    before=tuple(e.model_dump_json() for e in [BASE,candidate])
    def forbidden(*args,**kwargs):raise AssertionError("PoC side effect")
    monkeypatch.setattr("builtins.open",forbidden)
    monkeypatch.setattr("subprocess.run",forbidden)
    monkeypatch.setattr("subprocess.Popen",forbidden)
    result=retrieve(QUERY,(BASE,candidate),CORPUS.evidence,CORPUS.reviews)
    assert result["retrieved"]==1
    assert tuple(e.model_dump_json() for e in [BASE,candidate])==before
    assert candidate.state=="CANDIDATE"


def test_bounded_number_reports_omissions_explicitly_and_order_stable():
    records=[];reviews=[]
    for _ in range(3):
        exp=Experience.model_validate({**BASE.model_dump(),"id":uuid4(),"review_id":uuid4()})
        records.append(exp)
        reviews.append(Review(id=exp.review_id,experience_id=exp.id,content_hash=exp.digest(),
            reviewed_at=QUERY.now,source="synthetic-reviewed-manifest-v1"))
    one=retrieve(QUERY,tuple(records),CORPUS.evidence,tuple(reviews),limit=1)
    two=retrieve(QUERY,tuple(reversed(records)),CORPUS.evidence,tuple(reviews),limit=1)
    assert one==two and one["retrieved"]==1
    assert sum(r["reason"]=="RETRIEVAL_LIMIT" for r in one["results"])==2


@pytest.mark.parametrize("kwargs",[{"limit":0},{"limit":6},{"limit":True},{"max_context_bytes":127},{"max_context_bytes":4097}])
def test_bounds_rejected(kwargs):
    with pytest.raises(ValueError):retrieve(QUERY,(BASE,),CORPUS.evidence,CORPUS.reviews,**kwargs)


def test_input_count_and_duplicate_identity_rejected():
    for records in [(BASE,)*33,(BASE,)*2]:
        with pytest.raises(ValueError):retrieve(QUERY,records,CORPUS.evidence,CORPUS.reviews)


def test_current_observation_must_be_fresh_unambiguous_and_scoped():
    with pytest.raises(ValidationError):
        Observation(**{**QUERY.current.model_dump(),"facts":QUERY.current.facts*2})
    future=Query(**{**QUERY.model_dump(),"current":QUERY.current.model_copy(update={"observed_at":QUERY.now+timedelta(seconds=1)})})
    assert retrieve(future,(BASE,),CORPUS.evidence,CORPUS.reviews)["results"][0]["reason"]=="STALE_OBSERVATION"


def test_no_authority_fields_accepted_in_memory_contract():
    for field in ["execute","approve_tests","promote","command","browser_plan"]:
        with pytest.raises(ValidationError):Experience(**{**BASE.model_dump(),field:True})


def test_conflicting_historical_facts_never_collapse_to_last_value():
    from qa_sentinel.evaluation.experience_poc import Evidence
    record=CORPUS.evidence[0]
    with pytest.raises(ValidationError):
        Evidence(**{**record.model_dump(),"facts":record.facts*2})
    with pytest.raises(ValidationError):
        Experience(**{**BASE.model_dump(),"required_facts":BASE.required_facts*2})


def test_checked_in_report_matches_current_fixture_and_code():
    stored=json.loads((ROOT/"benchmarks/experience_poc_v1_report.json").read_text(encoding="utf-8"))
    assert stored==evaluate(PATH)
