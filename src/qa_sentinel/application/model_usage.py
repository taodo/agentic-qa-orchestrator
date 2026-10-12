"""Bounded derived token visibility. Never workflow truth or estimated billing."""
from collections import defaultdict
from typing import Literal
from uuid import UUID
from pydantic import ValidationError
from qa_sentinel.models.base import ModelMetadata
from qa_sentinel.agents.base import STATE_AGENTS
from .models import View

FIELDS = ("input_tokens", "output_tokens", "reasoning_tokens", "total_tokens")
STAGES = {agent: state for state, agent in STATE_AGENTS.items()}
MAX_USAGE_EVENTS = 6000


class TokenMetric(View):
    known_sum: int | None
    missing_records: int
    total: int | None


class UsageTotals(View):
    records: int
    input_tokens: TokenMetric
    output_tokens: TokenMetric
    reasoning_tokens: TokenMetric
    total_tokens: TokenMetric


class InvocationUsage(View):
    invocation_id: UUID
    agent: str
    configured_model: str
    provider_models: tuple[str, ...]
    stage: str
    applicable: bool
    unresolved_records: int
    inconsistent_history: bool
    usage: UsageTotals
    original_context_chars: int | None
    selected_context_chars: int | None
    reused_results: int | None


class UsageGroup(View):
    identity: str
    usage: UsageTotals


class TaskModelUsage(View):
    task_id: UUID
    execution_job_id: UUID | None = None
    scope: Literal["TASK", "EXECUTION_JOB_WINDOW"]
    invocations: tuple[InvocationUsage, ...]
    usage: UsageTotals
    by_agent: tuple[UsageGroup, ...]
    by_model: tuple[UsageGroup, ...]
    by_stage: tuple[UsageGroup, ...]
    top_invocations: tuple[UUID, ...]
    truncated: bool
    model_groups_truncated: bool
    cost_status: Literal["NOT_CONFIGURED"] = "NOT_CONFIGURED"
    estimated_cost: None = None


def totals(records, *, incomplete=False):
    metrics = {}
    for field in FIELDS:
        values = [r.get(field) if r is not None else None for r in records]
        known = [v for v in values if type(v) is int and v >= 0]
        missing = len(values) - len(known)
        value = sum(known) if known else None
        metrics[field] = TokenMetric(known_sum=value, missing_records=missing,
            total=value if not missing and not incomplete else None)
    return UsageTotals(records=len(records), **metrics)


def safe_metadata(value):
    try:
        if not isinstance(value, dict):
            return None
        parsed = ModelMetadata.model_validate(value).model_dump(mode="json")
        # Stored invalid coercible numbers must not become provider-authoritative usage.
        for field in FIELDS:
            if type(value.get(field)) is not int:
                parsed[field] = None
        return parsed
    except (ValidationError, TypeError, ValueError):
        return None


def assess_usage(task_id, invocations, events, *, truncated=False, job=None):
    grouped = defaultdict(list)
    for event in events:
        grouped[event["invocation_id"]].append(event)
    rows, agent_records, model_records, stage_records, all_records = [], defaultdict(list), defaultdict(list), defaultdict(list), []
    for invocation in invocations:
        history = grouped[str(invocation.id)]
        repository = any(e["event_type"].startswith("MODEL_TURN_") or
                         e["event_type"] == "REPOSITORY_SESSION_STARTED" for e in history)
        slots, inconsistent = [], False
        if repository:
            turns = defaultdict(list)
            for event in history:
                if event["event_type"].startswith("MODEL_TURN_"):
                    index = event["turn_index"]
                    if type(index) is not int or index < 1:
                        inconsistent = True
                        continue
                    turns[index].append(event)
            for index in sorted(turns):
                inconsistent |= sum(e["event_type"] == "MODEL_TURN_STARTED" for e in turns[index]) > 1
                candidates = [e for e in turns[index] if e["event_type"] != "MODEL_TURN_STARTED"]
                if len(candidates) > 1:
                    inconsistent = True
                selected = candidates[0] if len(candidates) == 1 else turns[index][0]
                slots.append((selected["timestamp"], safe_metadata(selected["metadata"]) if len(candidates) == 1 else None,
                              not candidates))
            if not slots and invocation.model != "fake":
                slots.append((invocation.started_at, None, True))
        else:
            terminal = [e for e in history if e["event_type"] in {"AGENT_COMPLETED", "AGENT_FAILED"}]
            inconsistent = len(terminal) > 1
            if terminal:
                slots.append((terminal[0]["timestamp"], safe_metadata(terminal[0]["metadata"]) if not inconsistent else None, False))
            elif invocation.model != "fake":
                slots.append((invocation.started_at, None, True))
        # Existing ExecutionJob has no invocation FK: report an explicit evidence-time
        # window, never pretend it is a new QA Run or exact billing attribution.
        if job is not None:
            slots = [(instant, metadata, unresolved) for instant, metadata, unresolved in slots
                     if job.started_at is not None and instant >= job.started_at and
                     (job.finished_at is None or instant <= job.finished_at)]
            if not slots:
                continue
        applicable = invocation.model != "fake" or any(metadata is not None for _, metadata, _ in slots)
        records = [metadata for _, metadata, _ in slots] if applicable else []
        selection = [record["context_selection"] for record in records
                     if record is not None and record.get("context_selection") is not None]
        complete_selection = bool(records) and len(selection) == len(records)
        provider_models = tuple(sorted({r["model"] for r in records if r is not None}))
        stage = STAGES[invocation.agent].value
        row = InvocationUsage(invocation_id=invocation.id, agent=invocation.agent.value,
            configured_model=invocation.model, provider_models=provider_models, stage=stage,
            applicable=applicable, unresolved_records=sum(unresolved for _, _, unresolved in slots),
            inconsistent_history=inconsistent, usage=totals(records, incomplete=truncated or inconsistent),
            original_context_chars=sum(s["original_chars"] for s in selection) if complete_selection else None,
            selected_context_chars=sum(s["selected_chars"] for s in selection) if complete_selection else None,
            reused_results=sum(s["reused_results"] for s in selection) if complete_selection else None)
        rows.append(row)
        for record in records:
            all_records.append(record)
            agent_records[row.agent].append(record)
            model_records[invocation.model if record is None else record["model"]].append(record)
            stage_records[stage].append(record)
    incomplete = truncated or any(row.inconsistent_history for row in rows)
    def groups(mapping):
        return tuple(sorted((UsageGroup(identity=identity, usage=totals(records, incomplete=incomplete))
            for identity, records in mapping.items()), key=lambda group: (-(group.usage.total_tokens.known_sum or 0), group.identity)))
    models = groups(model_records)
    return TaskModelUsage(task_id=task_id, execution_job_id=None if job is None else job.id,
        scope="TASK" if job is None else "EXECUTION_JOB_WINDOW", invocations=tuple(rows),
        usage=totals(all_records, incomplete=incomplete), by_agent=groups(agent_records),
        by_model=models[:20], by_stage=groups(stage_records),
        top_invocations=tuple(row.invocation_id for row in sorted((r for r in rows if r.usage.total_tokens.known_sum is not None),
            key=lambda row: (-(row.usage.total_tokens.known_sum or 0), str(row.invocation_id)))[:10]),
        truncated=truncated, model_groups_truncated=len(models) > 20)
