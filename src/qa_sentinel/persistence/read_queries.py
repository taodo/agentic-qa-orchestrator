"""Bounded storage projections. No application contracts or workflow behavior."""
from sqlalchemy import select, func, literal_column
from . import models as m, mappers


class ReadQueries:
    def __init__(self, session):
        self.session = session

    def projects(self, limit):
        rows = self.session.scalars(select(m.ProjectRow).order_by(m.ProjectRow.key, m.ProjectRow.id).limit(limit + 1))
        return [mappers.project_from_orm(row) for row in rows]

    def tasks(self, project_id, limit):
        rows = self.session.scalars(select(m.TaskRow).where(m.TaskRow.project_id == str(project_id))
            .order_by(func.qa_utc_microseconds(m.TaskRow.created_at).desc(), m.TaskRow.id).limit(limit + 1))
        return [mappers.task_from_orm(row) for row in rows]

    def _records(self, row_type, mapper, timestamp, task_id, limit):
        rows = self.session.scalars(select(row_type).where(row_type.task_id == str(task_id))
            .order_by(func.qa_utc_microseconds(timestamp), literal_column(row_type.__tablename__ + ".rowid"))
            .limit(limit + 1))
        return [mapper(row) for row in rows]

    def artifacts(self, task_id, limit):
        return self._records(m.ArtifactRow, mappers.artifact_from_orm, m.ArtifactRow.created_at, task_id, limit)

    def invocations(self, task_id, limit):
        return self._records(m.InvocationRow, mappers.invocation_from_orm, m.InvocationRow.started_at, task_id, limit)

    def test_runs(self, task_id, limit):
        return self._records(m.TestRunRow, mappers.test_run_from_orm, m.TestRunRow.started_at, task_id, limit)

    def errors(self, task_id, limit):
        return self._records(m.ErrorRow, mappers.error_from_orm, m.ErrorRow.created_at, task_id, limit)

    def decisions(self, task_id, limit):
        return self._records(m.DecisionRow, mappers.decision_from_orm, m.DecisionRow.created_at, task_id, limit)

    def gate_evaluations(self, task_id, limit):
        return self._records(m.GateEvaluationRow, mappers.gate_evaluation_from_orm, m.GateEvaluationRow.evaluated_at, task_id, limit)

    def timeline(self, task_id, limit):
        insertion = literal_column("events.rowid")
        instant = func.qa_utc_microseconds(m.EventRow.timestamp)
        rows = self.session.execute(select(m.EventRow, insertion, instant).where(m.EventRow.task_id == str(task_id))
            .order_by(instant, insertion).limit(limit + 1))
        return [(mappers.event_from_orm(row), sequence, microseconds) for row, sequence, microseconds in rows]


    def model_usage_events(self, task_id, invocation_ids, maximum=6000):
        # Project only safe metadata, never turn outputs, repository/source bodies or history.
        if not invocation_ids:
            return []
        invocation = m.EventRow.correlation["invocation_id"].as_string()
        query = select(m.EventRow.id, invocation.label("invocation_id"), m.EventRow.event_type,
            m.EventRow.timestamp, m.EventRow.payload["turn_index"].label("turn_index"),
            m.EventRow.payload["model_metadata"].label("metadata")).where(
            m.EventRow.task_id == str(task_id), invocation.in_([str(i) for i in invocation_ids]),
            m.EventRow.event_type.in_(("REPOSITORY_SESSION_STARTED", "MODEL_TURN_STARTED",
                "MODEL_TURN_COMPLETED", "MODEL_TURN_FAILED", "AGENT_COMPLETED", "AGENT_FAILED")))
        return [dict(row) for row in self.session.execute(query.order_by(
            literal_column("events.rowid")).limit(maximum + 1)).mappings()]
