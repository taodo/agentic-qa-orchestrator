"""Explicit bounded SQL projections; no runtime resolution or physical evidence IO.

DB triage is a subset of Task 22's durable reservation rules, not its full safety
assessment. No absence of a signal proves workspace/canonical evidence safety.
"""
from datetime import datetime, timezone
from sqlalchemy import select, func, case, exists, and_, or_, literal, union_all
from sqlalchemy.orm import aliased
from . import models as m


def utc(column):
    return case((column.is_not(None), func.qa_utc_microseconds(column)), else_=None)


def db_attention():
    t, e = m.TaskRow, m.EventRow
    outcome = aliased(m.EventRow)
    provider_done = exists(select(outcome.id).where(outcome.task_id == e.task_id,
        outcome.event_type.in_(("MODEL_TURN_COMPLETED", "MODEL_TURN_FAILED")),
        outcome.correlation["invocation_id"].as_string() == e.correlation["invocation_id"].as_string(),
        outcome.payload["turn_index"].as_integer() == e.payload["turn_index"].as_integer()))
    mutation_done = exists(select(outcome.id).where(outcome.task_id == e.task_id,
        outcome.event_type.in_(("MUTATION_APPLIED", "MUTATION_FAILED")),
        outcome.correlation["invocation_id"].as_string() == e.correlation["invocation_id"].as_string()))
    test_done = exists(select(m.TestRunRow.id).where(m.TestRunRow.task_id == e.task_id,
        m.TestRunRow.id == e.correlation["test_run_id"].as_string(),
        m.TestRunRow.implementation_artifact_id == e.correlation["artifact_id"].as_string()))
    event_signal = exists(select(e.id).where(e.task_id == t.id, or_(
        and_(e.event_type == "MODEL_TURN_STARTED", ~provider_done),
        and_(e.event_type == "MUTATION_RESERVED", ~mutation_done),
        e.event_type == "MUTATION_RECONCILIATION_REQUIRED",
        and_(e.event_type.in_(("MUTATION_APPLIED", "MUTATION_FAILED")), e.payload["result"]["rollback"].as_string() == "FAILED"),
        and_(e.event_type == "TEST_EXECUTION_STARTED", ~test_done))))
    pending = exists(select(m.InvocationRow.id).where(m.InvocationRow.task_id == t.id, m.InvocationRow.status == "STARTED"))
    return or_(pending, event_signal)


def latest_job(field):
    j = m.ExecutionJobRow
    return select(field).where(j.task_id == m.TaskRow.id).order_by(j.sequence.desc()).limit(1).correlate(m.TaskRow).scalar_subquery()


def task_projection():
    t, j, err = m.TaskRow, m.ExecutionJobRow, m.ErrorRow
    signal = db_attention()
    active = select(j.status).where(j.task_id == t.id, j.status.in_(("QUEUED", "RUNNING"))).limit(1).correlate(t).scalar_subquery()
    latest = latest_job(j.status)
    attention = case((t.state == "BLOCKED", "BLOCKED"), (active.is_not(None), "ACTIVE"),
        (or_(signal, latest.in_(("FAILED", "STOPPED"))), "ATTENTION"), else_="NORMAL")
    # Unknown or arbitrary ErrorRecord.code never leaves storage as text.
    safe_code = case((err.code.in_(("OUTPUT_SCHEMA_INVALID", "MUTATION_RECONCILIATION_REQUIRED",
        "EXECUTION_FAILED", "EXECUTION_INTERRUPTED", "RUNTIME_STOPPED")), err.code), else_="ERROR_RECORDED")
    error = select(safe_code).where(err.task_id == t.id).order_by(utc(err.created_at).desc(), err.id.desc()).limit(1).correlate(t).scalar_subquery()
    return select(t.id.label("task_id"), t.project_id, m.ProjectRow.key.label("project_key"),
        func.substr(t.title, 1, 240).label("title"), t.state.label("task_state"),
        active.label("active_execution_status"), latest.label("latest_execution_status"),
        latest_job(j.safe_error_code).label("latest_execution_error_code"), signal.label("reconciliation_attention"),
        attention.label("attention"), error.label("latest_error_code"), t.updated_at).join(m.ProjectRow, m.ProjectRow.id == t.project_id)


class OperationalQueries:
    def __init__(self, session):
        self.session = session

    def summary(self):
        tasks = task_projection().subquery()
        recent = select(m.ExecutionJobRow.status).order_by(m.ExecutionJobRow.sequence.desc()).limit(50).subquery()
        count = lambda table, condition=None: select(func.count()).select_from(table).where(condition if condition is not None else literal(True)).scalar_subquery()
        row = self.session.execute(select(
            count(m.ProjectRow).label("project_count"), count(m.TaskRow).label("task_count"),
            count(m.ExecutionJobRow, m.ExecutionJobRow.status == "RUNNING").label("running_jobs"),
            count(m.ExecutionJobRow, m.ExecutionJobRow.status == "QUEUED").label("queued_jobs"),
            count(m.TaskRow, m.TaskRow.state == "BLOCKED").label("blocked_tasks"),
            count(m.TaskRow, m.TaskRow.state.in_(("DONE", "FAILED"))).label("terminal_tasks"),
            count(tasks, tasks.c.reconciliation_attention).label("reconciliation_attention_tasks"),
            count(recent, recent.c.status == "FAILED").label("recent_failed_jobs"),
            count(recent, recent.c.status == "STOPPED").label("recent_stopped_jobs"))).mappings().one()
        return {**row, "generated_at": datetime.now(timezone.utc)}

    def tasks(self, limit, **filters):
        tasks = task_projection().subquery()
        statement = select(tasks)
        for field in ("project_id", "task_state", "attention"):
            if filters.get(field) is not None:
                statement = statement.where(tasks.c[field] == str(filters[field]))
        if filters.get("execution_status") is not None:
            statement = statement.where(tasks.c.latest_execution_status == str(filters["execution_status"]))
        if filters.get("reconciliation_attention") is not None:
            statement = statement.where(tasks.c.reconciliation_attention == filters["reconciliation_attention"])
        if filters.get("attention_only"):
            statement = statement.where(tasks.c.attention != "NORMAL")
        if filters.get("active_only"):
            statement = statement.where(tasks.c.active_execution_status.is_not(None))
        return list(self.session.execute(statement.order_by(utc(tasks.c.updated_at).desc(), tasks.c.task_id.desc()).limit(limit + 1)).mappings())

    def projects(self, limit):
        tasks = task_projection().subquery()
        p = m.ProjectRow
        counts = select(tasks.c.project_id, func.count().label("task_count"),
            func.sum(case((tasks.c.active_execution_status.is_not(None), 1), else_=0)).label("active_jobs"),
            func.sum(case((tasks.c.task_state == "BLOCKED", 1), else_=0)).label("blocked_tasks"),
            func.sum(case((tasks.c.reconciliation_attention, 1), else_=0)).label("reconciliation_attention_tasks"))
        counts = counts.group_by(tasks.c.project_id).subquery()
        # Actual activity timestamps, not just Task.updated_at (jobs/evidence may
        # be committed while Task state is unchanged). Keep native offset text.
        activity = self.activity_statement().subquery()
        latest_activity = select(activity.c.timestamp).where(activity.c.project_id == p.id).order_by(
            activity.c.instant.desc(), activity.c.rank.desc(), activity.c.record_id.desc()).limit(1).correlate(p).scalar_subquery()
        latest_task = select(m.TaskRow.updated_at).where(m.TaskRow.project_id == p.id).order_by(utc(m.TaskRow.updated_at).desc(), m.TaskRow.id.desc()).limit(1).correlate(p).scalar_subquery()
        latest = case(
            (and_(utc(latest_activity) >= utc(p.updated_at), or_(latest_task.is_(None), utc(latest_activity) >= utc(latest_task))), latest_activity),
            (utc(latest_task) >= utc(p.updated_at), latest_task), else_=p.updated_at)
        statement = select(p.id.label("project_id"), p.key.label("project_key"),
            *[func.coalesce(counts.c[name], 0).label(name) for name in ("task_count", "active_jobs", "blocked_tasks", "reconciliation_attention_tasks")],
            latest.label("latest_activity_at")).outerjoin(counts, counts.c.project_id == p.id).order_by(p.key, p.id).limit(limit + 1)
        return list(self.session.execute(statement).mappings())

    def activity_statement(self, project_id=None):
        t, j, e, err, run = m.TaskRow, m.ExecutionJobRow, m.EventRow, m.ErrorRow, m.TestRunRow
        def projection(table, timestamp, kind, rank, state=None):
            statement = select(table.id.label("record_id"), table.task_id, t.project_id,
                kind.label("kind"), timestamp.label("timestamp"), utc(timestamp).label("instant"),
                literal(rank).label("rank"), (literal(None) if state is None else state).label("task_state")).join(t, t.id == table.task_id)
            return statement.where(t.project_id == str(project_id)) if project_id else statement
        transition_state = e.payload["to_state"].as_string()
        allowed_states = ("CREATED", "RESEARCHING", "PLANNING", "IMPLEMENTING", "TESTING", "ANALYZING", "INVESTIGATING", "REVIEWING", "BLOCKED", "FAILED", "DONE")
        events = projection(e, e.timestamp, literal("TASK_STATE_CHANGED"), 1,
            case((transition_state.in_(allowed_states), transition_state), else_=None)).where(e.event_type == "STATE_TRANSITIONED")
        queued = projection(j, j.created_at, literal("EXECUTION_QUEUED"), 2)
        started = projection(j, j.started_at, literal("EXECUTION_STARTED"), 3).where(j.started_at.is_not(None))
        finished = projection(j, j.finished_at, case((j.status == "SUCCEEDED", "EXECUTION_SUCCEEDED"),
            (j.status == "STOPPED", "EXECUTION_STOPPED"), else_="EXECUTION_FAILED"), 4).where(j.finished_at.is_not(None))
        errors = projection(err, err.created_at, literal("BLOCKING_ERROR_RECORDED"), 5).where(err.blocking.is_(True))
        tests = projection(run, run.finished_at, case((run.outcome == "PASS", "TEST_PASS"),
            (run.outcome == "FAIL", "TEST_FAIL"), else_="TEST_UNKNOWN"), 6)
        return union_all(events, queued, started, finished, errors, tests)

    def activity(self, limit, project_id=None):
        # Each source is SQL-projected; only the globally newest limit+1 items
        # are materialized. Rank and UUID break timestamp ties, not QA causality.
        activity = self.activity_statement(project_id).subquery()
        rows = self.session.execute(select(activity.c.record_id, activity.c.task_id, activity.c.project_id,
            activity.c.kind, activity.c.timestamp, activity.c.task_state).order_by(
                activity.c.instant.desc(), activity.c.rank.desc(), activity.c.record_id.desc()).limit(limit + 1)).mappings()
        return list(rows)
