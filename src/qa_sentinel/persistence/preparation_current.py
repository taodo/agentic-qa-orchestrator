"""Derived current preparation eligibility; historical content/receipts stay immutable."""
from sqlalchemy import select
from .models import RequirementRevisionRow, TestRequirementLinkRow, CampaignRequirementRow, TestSpecificationRow, TestEditRow


def current_requirement(table=CampaignRequirementRow):
    return ~select(RequirementRevisionRow.requirement_id).where(
        RequirementRevisionRow.supersedes_id == table.id).correlate(table).exists()


def current_test(table=TestSpecificationRow):
    return (~select(TestEditRow.id).where(TestEditRow.previous_id == table.id).correlate(table).exists()) & ~select(TestRequirementLinkRow.test_spec_id).join(RequirementRevisionRow,
        RequirementRevisionRow.supersedes_id == TestRequirementLinkRow.requirement_id).where(
        TestRequirementLinkRow.test_spec_id == table.id).correlate(table).exists()
