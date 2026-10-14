"""Durable operator submission and machine plan receipts; not QA outcomes."""
from uuid import UUID,uuid4
from typing import Literal
from pydantic import Field,AwareDatetime,model_validator
from .campaign_content import Frozen,Hash
from .browser_preparation import BrowserMode,now
from .browser_grounding import GroundingScope,digest
from .browser_execution import BrowserExecutionPlan,BrowserRuntimeIdentity
from .qa_run import canonical_json,validate_approval
from .campaign_content import CampaignRequirement
from .campaign_review import ApprovalEvidence


class BrowserBatchSubmission(Frozen):
    contract_version: Literal["browser-batch-submit-v1"]="browser-batch-submit-v1"
    preparation_id: UUID
    project_id: UUID
    campaign_id: UUID
    selection_hash: Hash
    browser_mode: BrowserMode
    created_at: AwareDatetime=Field(default_factory=now)
    interruption_acknowledged_at: AwareDatetime | None=None

    @model_validator(mode="after")
    def timestamps(self):
        if self.interruption_acknowledged_at is not None and self.interruption_acknowledged_at<self.created_at:raise ValueError("Interruption acknowledgement timestamp")
        return self


class BatchRequirement(Frozen):
    content: CampaignRequirement
    approval: ApprovalEvidence

    @model_validator(mode="after")
    def approved(self):
        validate_approval(self.content,self.approval,"REQUIREMENT")
        return self


class BrowserBatchPlan(Frozen):
    contract_version: Literal["browser-batch-plan-v1"]="browser-batch-plan-v1"
    id: UUID=Field(default_factory=uuid4)
    scope: GroundingScope
    selection_hash: Hash
    browser_mode: BrowserMode
    grounding_id: UUID
    observation_id: UUID
    observation_hash: Hash
    plan: BrowserExecutionPlan
    plan_hash: Hash
    runtime_identity: BrowserRuntimeIdentity
    requirements: tuple[BatchRequirement,...]=Field(default=(),max_length=20)
    created_at: AwareDatetime=Field(default_factory=now)

    @model_validator(mode="after")
    def seal(self):
        if digest(self.plan)!=self.plan_hash:raise ValueError("Batch plan hash mismatch")
        self.scope.policy.validate(self.plan,self.scope.target)
        if len(canonical_json(self.model_dump(mode="json")))>1048576:raise ValueError("Batch plan receipt bound")
        return self
