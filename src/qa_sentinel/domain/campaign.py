"""Project-owned preparation identity, independent of execution and QA outcomes."""
from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated
from uuid import UUID, uuid4
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, AwareDatetime

CampaignName = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
CampaignObjective = Annotated[str, StringConstraints(strict=True, max_length=4000)]


class CampaignPreparationStatus(StrEnum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"


class InvalidCampaignTransition(ValueError):
    pass


def validate_campaign_transition(current, target):
    allowed = ((CampaignPreparationStatus.DRAFT, CampaignPreparationStatus.READY_FOR_REVIEW),
               (CampaignPreparationStatus.READY_FOR_REVIEW, CampaignPreparationStatus.APPROVED))
    if (current, target) not in allowed:
        raise InvalidCampaignTransition("CAMPAIGN_INVALID_TRANSITION")


class QACampaign(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    name: CampaignName
    objective: CampaignObjective | None = None
    status: CampaignPreparationStatus = CampaignPreparationStatus.DRAFT
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def update_metadata(self, **changes):
        if not set(changes) <= {"name", "objective"}:
            raise ValueError("Only campaign metadata can be updated")
        if not changes:
            return self
        return QACampaign.model_validate({**self.model_dump(), **changes,
            "updated_at": datetime.now(timezone.utc)})

    def transition(self, target: CampaignPreparationStatus):
        target = CampaignPreparationStatus(target)
        validate_campaign_transition(self.status, target)
        return QACampaign.model_validate({**self.model_dump(), "status": target,
            "updated_at": datetime.now(timezone.utc)})
