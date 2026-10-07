"""Campaign preparation contracts and independent persistence boundaries."""
from datetime import datetime, timezone, timedelta
from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.domain.campaign import QACampaign, CampaignPreparationStatus as Status, InvalidCampaignTransition
from qa_sentinel.domain.project import Project
from qa_sentinel.persistence.unit_of_work import UnitOfWork


@pytest.mark.parametrize("current", list(Status))
@pytest.mark.parametrize("target", list(Status))
def test_all_preparation_edges_are_explicit_forward_only(current, target):
    campaign = QACampaign(project_id=uuid4(), name="Smoke", status=current)
    if (current, target) in {(Status.DRAFT, Status.READY_FOR_REVIEW), (Status.READY_FOR_REVIEW, Status.APPROVED)}:
        changed = campaign.transition(target)
        assert changed.status == target and campaign.status == current
        assert changed.id == campaign.id and changed.project_id == campaign.project_id
        assert changed.created_at == campaign.created_at and changed.updated_at >= campaign.updated_at
    else:
        with pytest.raises(InvalidCampaignTransition, match="CAMPAIGN_INVALID_TRANSITION"):
            campaign.transition(target)


@pytest.mark.parametrize("changes", [dict(name=""), dict(name=" "), dict(name="x"*201), dict(name=1),
    dict(objective="x"*4001), dict(objective=1), dict(project_id=None), dict(status="RUNNING"),
    dict(status="PASS"), dict(status="FAIL"), dict(status="DONE"), dict(status="BLOCKED"), dict(workspace_root="forbidden")])
def test_campaign_contract_rejects_invalid_or_unbounded_inputs(changes):
    with pytest.raises(ValidationError):
        QACampaign.model_validate({"project_id": uuid4(), "name": "Campaign", **changes})


def test_campaign_frozen_identity_metadata_and_status_are_separate():
    campaign = QACampaign(project_id=uuid4(), name="  Smoke  ", objective="x"*4000)
    assert campaign.name == "Smoke" and campaign.status == Status.DRAFT
    assert campaign.created_at.utcoffset() == timedelta(0)
    for field, value in (("id", uuid4()), ("project_id", uuid4()), ("status", Status.APPROVED)):
        with pytest.raises(ValidationError):
            setattr(campaign, field, value)
    for status in Status:
        original = campaign.model_copy(update={"status": status})
        updated = original.update_metadata(name="Updated", objective=None)
        assert updated.status == status and updated.objective is None
        assert updated.id == campaign.id and updated.created_at == campaign.created_at
        assert updated.updated_at >= original.updated_at
        assert original.update_metadata() == original
    with pytest.raises(ValueError):
        campaign.update_metadata(status=Status.APPROVED)


def test_campaign_uow_rollback_identity_and_status_write_boundaries(factory):
    owner, other = Project(key="owner", name="Owner"), Project(key="other", name="Other")
    campaign = QACampaign(project_id=owner.id, name="Campaign")
    with UnitOfWork(factory) as uow:
        uow.projects.add(owner); uow.projects.add(other); uow.commit()
    with UnitOfWork(factory) as uow:
        uow.campaigns.add(campaign)
    with UnitOfWork(factory) as uow:
        assert uow.campaigns.get(campaign.id) is None
        uow.campaigns.add(campaign); uow.commit()
    with UnitOfWork(factory) as uow:
        for changes in ({"project_id": other.id}, {"created_at": campaign.created_at+timedelta(seconds=1)}):
            with pytest.raises(ValueError, match="immutable"):
                uow.campaigns.save_metadata(campaign.model_copy(update=changes))
        with pytest.raises(ValueError, match="Metadata"):
            uow.campaigns.save_metadata(campaign.transition(Status.READY_FOR_REVIEW))
        with pytest.raises(InvalidCampaignTransition):
            uow.campaigns.save_transition(campaign.model_copy(update={"status": Status.APPROVED}))
        with pytest.raises(ValueError, match="metadata"):
            uow.campaigns.save_transition(campaign.transition(Status.READY_FOR_REVIEW).update_metadata(name="Hidden"))
        with pytest.raises(ValueError, match="DRAFT"):
            uow.campaigns.add(QACampaign(project_id=owner.id, name="Skip preparation", status=Status.APPROVED))
        assert uow.campaigns.get(campaign.id) == campaign


@pytest.mark.parametrize("limit", [0, 201, True, "1"])
def test_repository_listing_is_bounded_even_outside_application(factory, limit):
    with UnitOfWork(factory) as uow:
        with pytest.raises(ValueError):
            uow.campaigns.list_for_project(uuid4(), limit=limit)
