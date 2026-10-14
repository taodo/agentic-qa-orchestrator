"""A local human action is provenance, never an authenticated personal identity."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator
from qa_sentinel.domain.campaign_review import ReviewerLabel, ReviewNote

LOCAL_OPERATOR_LABEL = "local-operator-v1"
LOCAL_OPERATOR_NOTE = "Explicit local-operator approval declaration received by the trusted local host; no authenticated personal identity is asserted."

class LocalApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer_label: ReviewerLabel | None = None
    note: ReviewNote | None = None
    approval_provenance: Literal["LOCAL_OPERATOR"] | None = None

    @model_validator(mode="after")
    def explicit_provenance(self):
        if self.approval_provenance is not None:
            if self.reviewer_label is not None or self.note is not None:
                raise ValueError("Local provenance cannot assert a personal reviewer or custom note")
        elif self.reviewer_label is None or self.reviewer_label == LOCAL_OPERATOR_LABEL:
            raise ValueError("An operator assertion or explicit local provenance is required")
        return self

    def command(self):
        return dict(reviewer_label=LOCAL_OPERATOR_LABEL,note=LOCAL_OPERATOR_NOTE) if self.approval_provenance else dict(reviewer_label=self.reviewer_label,note=self.note)
