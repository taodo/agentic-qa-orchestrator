"""Central explicit approval contract independent of providers or host auth."""
from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.domain.campaign_content import CampaignRequirement, RequirementReviewStatus
from qa_sentinel.domain.test_specification import TestReviewStatus as SpecReviewStatus
from qa_sentinel.domain.campaign_review import ApprovalCommand, approve, content_hash, ReviewError, coverage


def requirement(state='READY_FOR_REVIEW', markers=()):
    return CampaignRequirement(project_id=uuid4(), campaign_id=uuid4(), extraction_id=uuid4(), key='R1', logical_key='R1',
        title='Login', description='Sign in', acceptance_criteria=[dict(key='C1', text='Signed in')],
        source_references=[dict(source_id=uuid4(), source_hash='a'*64, start_line=1, end_line=1, excerpt='Sign in')],
        information_markers=markers, review_status=state)


def test_review_statuses_remain_separate_from_execution():
    assert set(RequirementReviewStatus) == set(SpecReviewStatus) == {'DRAFT', 'NEEDS_CLARIFICATION', 'READY_FOR_REVIEW', 'APPROVED'}


def test_approval_hash_keeps_all_facts_and_provenance_and_ignores_review_time():
    r = requirement();evidence = approve(r, 'REQUIREMENT', ApprovalCommand(reviewer_label='qa-human'))
    approved = CampaignRequirement.model_validate({**r.model_dump(), 'review_status': 'APPROVED', 'updated_at': evidence.approved_at})
    assert content_hash(approved) == evidence.content_hash == content_hash(r)
    assert content_hash(r.model_copy(update={'description': 'Changed'})) != evidence.content_hash


@pytest.mark.parametrize('status', ['DRAFT', 'NEEDS_CLARIFICATION', 'APPROVED'])
def test_only_ready_for_review_can_reach_approved(status):
    with pytest.raises(ReviewError, match='REVIEW_NOT_REVIEWABLE'):
        approve(requirement(status), 'REQUIREMENT', ApprovalCommand(reviewer_label='qa'))


@pytest.mark.parametrize('kind', ['AMBIGUITY', 'MISSING_INFORMATION'])
def test_unresolved_markers_cannot_claim_approved(kind):
    with pytest.raises(ValidationError): requirement('APPROVED', [dict(kind=kind, description='Unknown')])


@pytest.mark.parametrize('label', ['', 'unsafe label', 'x'*65, 'x\n', 'x\u202e', None, 123])
def test_trusted_actor_label_is_explicit_bounded_and_not_fabricated(label):
    with pytest.raises(ValidationError): ApprovalCommand(reviewer_label=label)


@pytest.mark.parametrize('linked,approved,expected', [(0,0,'NOT_COVERED'),(9,0,'PARTIAL'),(9,1,'COVERED')])
def test_traceability_quantity_is_not_execution_result(linked, approved, expected):
    assert coverage(linked, approved) == expected
