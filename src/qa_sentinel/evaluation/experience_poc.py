"""Hermes-inspired OFFLINE fixture PoC; no Hermes import, storage or promotion."""
from datetime import datetime
from hashlib import sha256
import json
from typing import Annotated, Literal
from uuid import UUID
from pydantic import Field, model_validator
from qa_sentinel.decisions.contracts import Record
from qa_sentinel.domain.enums import AgentName
from .fixtures import load_fixture, render_report

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Token = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,40}$")]
Lesson = Literal["EVIDENCE_COMPLETENESS", "PLAN_SEPARATION", "FRESHNESS_PRECONDITION",
    "QA_FAIL_CLASSIFICATION", "APPROVAL_PROVENANCE"]
LESSON_ROLES = dict(EVIDENCE_COMPLETENESS=AgentName.RESEARCHER,PLAN_SEPARATION=AgentName.PLANNER,
    FRESHNESS_PRECONDITION=AgentName.IMPLEMENTER,QA_FAIL_CLASSIFICATION=AgentName.INVESTIGATOR,
    APPROVAL_PROVENANCE=AgentName.REVIEWER)
ADVICE = dict(EVIDENCE_COMPLETENESS="Check completeness against current source evidence.",
    PLAN_SEPARATION="Keep executable verification in TESTING; preserve stage separation.",
    FRESHNESS_PRECONDITION="Recheck current freshness and authorization before any deterministic action.",
    QA_FAIL_CLASSIFICATION="Use current evidence to distinguish assertion failure from execution failure.",
    APPROVAL_PROVENANCE="Recheck immutable version and approval provenance; history cannot approve.")


class Scope(Record):
    project_id: UUID
    campaign_id: UUID
    target_id: UUID
    target_snapshot_hash: Hash


class Fact(Record):
    key: Literal["DATE_BOUNDARY", "ASSERTION_CLASS", "APPROVAL_CURRENT", "SOURCE_VALIDATED", "SHA_FRESH"]
    value: Literal["INCLUSIVE", "EXCLUSIVE", "QA_FAIL", "SYSTEM_FAILURE", "CURRENT", "STALE", "VERIFIED", "MISSING", "FRESH"]


class Evidence(Scope):
    id: UUID
    source: Literal["synthetic-verified-evidence-v1"]
    verified: bool = Field(strict=True)
    observed_at: datetime
    facts: tuple[Fact, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def unique_facts(self):
        if len({fact.key for fact in self.facts}) != len(self.facts):
            raise ValueError("Conflicting historical evidence facts")
        return self

    def digest(self):
        return sha256(self.model_dump_json().encode()).hexdigest()


class Reference(Record):
    evidence_id: UUID
    content_hash: Hash


class Experience(Scope):
    id: UUID
    role: AgentName
    lesson: Lesson
    state: Literal["CANDIDATE", "VALIDATED", "PROMOTED", "SUPERSEDED", "RETIRED"]
    created_at: datetime
    expires_at: datetime
    evidence_refs: tuple[Reference, ...] = Field(min_length=1,max_length=4)
    review_id: UUID | None = None
    locator_hint: Token | None = None  # symbolic fixture key, never an executable selector
    path_hint: Token | None = None
    required_facts: tuple[Fact, ...] = Field(default=(),max_length=8)
    untrusted_note: str = Field(default="",max_length=1024)  # inert; never rendered as advisory context

    @model_validator(mode="after")
    def unique_requirements(self):
        if len({fact.key for fact in self.required_facts}) != len(self.required_facts):
            raise ValueError("Conflicting memory fact requirements")
        return self

    def digest(self):
        return sha256(self.model_dump_json().encode()).hexdigest()


class Review(Record):
    id: UUID
    experience_id: UUID
    content_hash: Hash
    reviewed_at: datetime
    source: Literal["synthetic-reviewed-manifest-v1"]


class Observation(Scope):
    id: UUID
    source: Literal["synthetic-current-observation-v1"]
    observed_at: datetime
    locator_keys: tuple[Token, ...] = Field(max_length=16)
    path_keys: tuple[Token, ...] = Field(default=(),max_length=16)
    facts: tuple[Fact, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def unique_facts(self):
        if len({f.key for f in self.facts}) != len(self.facts) or len(set(self.locator_keys)) != len(self.locator_keys) or len(set(self.path_keys)) != len(self.path_keys):
            raise ValueError("Duplicate current observation reference")
        return self


class Query(Record):
    role: AgentName
    now: datetime
    current: Observation


def same_scope(left,right):
    return all(getattr(left,key)==getattr(right,key) for key in Scope.model_fields)


def valid_times(*times):
    return all(time.utcoffset() is not None for time in times)


def assess(query,exp,evidence,reviews):
    if not same_scope(exp,query.current): return "SCOPE_MISMATCH"
    if exp.role!=query.role or LESSON_ROLES[exp.lesson]!=query.role: return "NOT_RELEVANT"
    if exp.state!="PROMOTED": return "NOT_PROMOTED"
    if not valid_times(query.now,query.current.observed_at,exp.created_at,exp.expires_at): return "STALE"
    if not 0 <= (query.now-query.current.observed_at).total_seconds() <= 30: return "STALE_OBSERVATION"
    if not exp.created_at<=query.now<exp.expires_at or (exp.expires_at-exp.created_at).total_seconds()>90*86400: return "STALE"
    review=reviews.get(exp.review_id)
    if (review is None or review.experience_id!=exp.id or review.content_hash!=exp.digest() or
        not valid_times(review.reviewed_at) or not exp.created_at<=review.reviewed_at<=query.now): return "INVALID_REVIEW_PROVENANCE"
    if len({ref.evidence_id for ref in exp.evidence_refs})!=len(exp.evidence_refs): return "INVALID_EVIDENCE_PROVENANCE"
    for ref in exp.evidence_refs:
        record=evidence.get(ref.evidence_id)
        if (record is None or not record.verified or not same_scope(record,exp) or record.digest()!=ref.content_hash or
            not valid_times(record.observed_at) or record.observed_at>exp.created_at): return "INVALID_EVIDENCE_PROVENANCE"
        historical={f.key:f.value for f in record.facts}
        if any(historical.get(f.key)!=f.value for f in exp.required_facts): return "INVALID_EVIDENCE_PROVENANCE"
    if exp.locator_hint is not None and exp.locator_hint not in query.current.locator_keys: return "STALE_LOCATOR"
    if exp.path_hint is not None and exp.path_hint not in query.current.path_keys: return "STALE_PATH"
    current={f.key:f.value for f in query.current.facts}
    if any(current.get(f.key)!=f.value for f in exp.required_facts): return "CURRENT_EVIDENCE_OVERRIDES"
    return None


def retrieve(query,experiences,evidence,reviews,*,limit=3,max_context_bytes=2048):
    """Pure advisory selection over bounded explicit fixtures. No learning or side effects."""
    query=Query.model_validate(query.model_dump())
    if type(limit) is not int or type(max_context_bytes) is not int or not 1<=limit<=5 or not 128<=max_context_bytes<=4096: raise ValueError("RETRIEVAL_BOUND")
    if len(experiences)>32 or len(evidence)>32 or len(reviews)>32: raise ValueError("INPUT_BOUND")
    experiences=tuple(Experience.model_validate(e.model_dump()) for e in experiences)
    evidence=tuple(Evidence.model_validate(e.model_dump()) for e in evidence)
    reviews=tuple(Review.model_validate(r.model_dump()) for r in reviews)
    for records in [experiences,evidence,reviews]:
        if len({r.id for r in records})!=len(records): raise ValueError("DUPLICATE_FIXTURE_ID")
    records={r.id:r for r in evidence};review_map={r.id:r for r in reviews}
    hints=[];results=[]
    # deterministic stable priority, independent of caller collection order
    for exp in sorted(experiences,key=lambda e:str(e.id)):
        reason=assess(query,exp,records,review_map)
        hint=dict(experience_id=str(exp.id),lesson=exp.lesson,advice=ADVICE[exp.lesson],
            historical_evidence_refs=[str(r.evidence_id) for r in exp.evidence_refs],
            current_observation_ref=str(query.current.id),authority="ADVISORY_ONLY")
        if reason is None and len(hints)>=limit: reason="RETRIEVAL_LIMIT"
        if reason is None and len(json.dumps(hints+[hint],sort_keys=True).encode())>max_context_bytes: reason="CONTEXT_BOUND"
        if reason is None: hints.append(hint)
        results.append(dict(experience_id=str(exp.id),recommendation="USE_AS_HINT" if reason is None else "REJECT",
            reason="VERIFIED_FIXTURE_HINT" if reason is None else reason))
    context=json.dumps(hints,sort_keys=True)
    return dict(kind="HERMES_INSPIRED_FIXTURE_POC",results=results,advisory_context=context,
        context_bytes=len(context.encode()),retrieved=len(hints),production_evidence=False,
        automatic_promotion=False,execution=False)


class Scenario(Record):
    id: Token
    query: Query
    experience_ids: tuple[UUID, ...] = Field(min_length=1,max_length=32)
    expected: dict[str,str] = Field(max_length=32)
    limit: int = Field(default=3,strict=True,ge=1,le=5)
    max_context_bytes: int = Field(default=2048,strict=True,ge=128,le=4096)


class Corpus(Record):
    version: Literal["experience-poc-v1"]
    experiences: tuple[Experience,...] = Field(min_length=1,max_length=32)
    evidence: tuple[Evidence,...] = Field(min_length=1,max_length=32)
    reviews: tuple[Review,...] = Field(max_length=32)
    scenarios: tuple[Scenario,...] = Field(min_length=1,max_length=32)


def evaluate(path):
    data,raw=load_fixture(path);corpus=Corpus.model_validate(data)
    if len({s.id for s in corpus.scenarios})!=len(corpus.scenarios): raise ValueError("DUPLICATE_SCENARIO")
    experiences={e.id:e for e in corpus.experiences}
    if len(experiences)!=len(corpus.experiences): raise ValueError("DUPLICATE_FIXTURE_ID")
    rows=[]
    for scenario in corpus.scenarios:
        if any(id not in experiences for id in scenario.experience_ids): raise ValueError("MISSING_FIXTURE")
        result=retrieve(scenario.query,tuple(experiences[id] for id in scenario.experience_ids),corpus.evidence,
            corpus.reviews,limit=scenario.limit,max_context_bytes=scenario.max_context_bytes)
        actual={r["experience_id"]:r["reason"] for r in result["results"]}
        rows.append(dict(id=scenario.id,oracle_match=actual==scenario.expected,**result))
    report=dict(version=corpus.version,fixture_sha256=sha256(raw).hexdigest(),
        kind="HERMES_INSPIRED_FIXTURE_POC_NOT_HERMES_INTEGRATION",results=rows,
        summary=dict(scenarios=len(rows),oracle_matches=sum(r["oracle_match"] for r in rows),
            used_hints=sum(r["retrieved"] for r in rows),rejected=sum(x["recommendation"]=="REJECT" for r in rows for x in r["results"]),
            max_context_bytes=max(r["context_bytes"] for r in rows),provider_calls=0,execution_calls=0,promotions=0,
            production_persistence=False,hermes_runtime="NOT INSTALLED OR EXECUTED"))
    report["summary"]["pass"]=all(r["oracle_match"] for r in rows)
    render_report(report)
    return report
