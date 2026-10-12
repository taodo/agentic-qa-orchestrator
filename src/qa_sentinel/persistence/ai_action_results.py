"""Bounded metadata projection of persisted outputs, including retired versions.

Never use current review status: approval is subsequent to the AI action. Immutable
markers reproduce canonical READY_FOR_REVIEW / NEEDS_CLARIFICATION at creation.
"""
from sqlalchemy import select, func, exists
from .models import CampaignRequirementRow as Requirement, RequirementRevisionRow as Revision
from .models import TestSpecificationRow as Test, TestRequirementLinkRow as Link


def action_outputs(session, records, *, generation=False):
    records = tuple(records)
    if not records:
        return {}
    if len(records) > 200:
        raise ValueError("Action summary bound")
    owner = (records[0].project_id, records[0].campaign_id)
    if any((r.project_id, r.campaign_id) != owner for r in records):
        raise ValueError("Action summary ownership")
    row = Test if generation else Requirement
    action_id = row.generation_id if generation else row.extraction_id
    columns = [action_id.label("action_id"), row.id, row.key, row.logical_key,
        (func.json_array_length(row.information_markers) > 0).label("needs_clarification")]
    if generation:
        inherited = exists(select(Link.test_spec_id).join(Requirement, Requirement.id == Link.requirement_id).where(
            Link.test_spec_id == Test.id, Requirement.project_id == str(owner[0]),
            Requirement.campaign_id == str(owner[1]), func.json_array_length(Requirement.information_markers) > 0))
        columns.append(inherited.label("inherited"))
    else:
        columns.append(func.coalesce(Revision.version, 1).label("version"))
    query = select(*columns).where(row.project_id == str(owner[0]), row.campaign_id == str(owner[1]),
        action_id.in_([str(r.id) for r in records])).order_by(action_id, row.id)
    if not generation:
        query = query.outerjoin(Revision, Revision.requirement_id == Requirement.id)
    # Existing finish contracts permit at most 100 outputs per action.
    rows = list(session.execute(query.limit(len(records) * 100 + 1)).mappings())
    grouped = {str(r.id): [] for r in records}
    for output in rows:
        grouped[output["action_id"]].append(output)
    if any(len(items) > 100 for items in grouped.values()):
        raise ValueError("Stored action output bound")
    result = {}
    for record in records:
        if record.status == "STARTED":
            result[record.id] = None
            continue
        items = grouped[str(record.id)]
        needs = sum(bool(item["needs_clarification"]) for item in items)
        revised = [item for item in items if not generation and item["version"] > 1]
        identity = revised[0] if len(revised) == 1 else None
        result[record.id] = dict(generated_count=len(items), ready_for_review_count=len(items)-needs,
            needs_clarification_count=needs,
            inherited_clarification_count=sum(bool(item["inherited"]) for item in items) if generation else None,
            revised_requirement=None if identity is None else dict(id=identity["id"], key=identity["key"],
                logical_key=identity["logical_key"], version=identity["version"],
                review_status="NEEDS_CLARIFICATION" if identity["needs_clarification"] else "READY_FOR_REVIEW"))
    return result
