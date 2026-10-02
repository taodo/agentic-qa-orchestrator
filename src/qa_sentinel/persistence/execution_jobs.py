"""Session-scoped job reads and compare-and-set lifecycle writes. No commits."""
from sqlalchemy import select, update
from qa_sentinel.domain.execution_job import ExecutionJob, ExecutionJobStatus as Status
from .models import ExecutionJobRow


def record(row):
    return ExecutionJob.model_validate({name: getattr(row, name) for name in ExecutionJob.model_fields})


def values(job):
    job = ExecutionJob.model_validate(job.model_dump())
    data = job.model_dump()
    for name in ("id", "task_id", "project_id"):
        data[name] = str(data[name])
    return data


class ExecutionJobRepository:
    def __init__(self, session):
        self.session = session

    def add(self, job):
        if job.status != Status.QUEUED:
            raise ValueError("New execution requests must be queued")
        self.session.add(ExecutionJobRow(**values(job)))
        self.session.flush()

    def get(self, job_id):
        row = self.session.scalar(select(ExecutionJobRow).where(ExecutionJobRow.id == str(job_id)))
        return None if row is None else record(row)

    def active(self, task_id):
        row = self.session.scalar(select(ExecutionJobRow).where(ExecutionJobRow.task_id == str(task_id),
            ExecutionJobRow.status.in_((Status.QUEUED, Status.RUNNING))))
        return None if row is None else record(row)

    def next_queued(self):
        row = self.session.scalar(select(ExecutionJobRow).where(ExecutionJobRow.status == Status.QUEUED)
            .order_by(ExecutionJobRow.sequence).limit(1))
        return None if row is None else record(row)

    def running(self):
        row = self.session.scalar(select(ExecutionJobRow).where(ExecutionJobRow.status == Status.RUNNING))
        return None if row is None else record(row)

    def list_by_task(self, task_id, limit):
        return [record(row) for row in self.session.scalars(select(ExecutionJobRow)
            .where(ExecutionJobRow.task_id == str(task_id)).order_by(ExecutionJobRow.sequence.desc()).limit(limit + 1))]

    def transition(self, job, expected):
        # Revalidation also prevents bypass via Pydantic model_copy/model_construct.
        data = values(job)
        changes = {name: data[name] for name in ("status", "started_at", "finished_at", "safe_error_code")}
        allowed = (expected == Status.QUEUED and job.status == Status.RUNNING) or (
            expected == Status.RUNNING and job.status in {Status.SUCCEEDED, Status.STOPPED, Status.FAILED})
        if not allowed:
            raise ValueError("Invalid execution lifecycle edge")
        statement = update(ExecutionJobRow).where(ExecutionJobRow.id == str(job.id),
            ExecutionJobRow.task_id == str(job.task_id), ExecutionJobRow.project_id == str(job.project_id),
            ExecutionJobRow.created_at == job.created_at, ExecutionJobRow.status == expected)
        if expected == Status.RUNNING:
            statement = statement.where(ExecutionJobRow.started_at == job.started_at)
        result = self.session.execute(statement.values(**changes))
        return result.rowcount == 1
