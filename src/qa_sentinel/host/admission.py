"""One process-local workflow admission shared by legacy commands and worker."""
from contextlib import contextmanager
import threading
from qa_sentinel.application.errors import ApplicationError, ApplicationErrorCode as Code


class ExecutionAdmission:
    def __init__(self):
        # Worker holds this through claim/run/completion. Its own application call
        # reenters on the same thread; different request threads fail fast.
        self._workflow = threading.RLock()
        self._gate = threading.Lock()  # Short submission/lifecycle state only.
        self._local = threading.local()
        self._busy_task = None
        self._accepting = True

    @property
    def job_id(self):
        return getattr(self._local, "job_id", None)

    def stop_accepting(self):
        with self._gate:
            self._accepting = False

    def start_accepting(self):
        with self._gate:
            self._accepting = True

    @contextmanager
    def enter(self):
        if not self._workflow.acquire(blocking=False):
            raise ApplicationError(Code.RUNTIME_STOPPED)
        try:
            if not self._accepting:
                raise ApplicationError(Code.RUNTIME_STOPPED)
            yield
        finally:
            self._workflow.release()

    @contextmanager
    def task(self, task_id):
        with self.enter():
            with self._gate:
                if self._busy_task is not None:
                    raise ApplicationError(Code.RUNTIME_STOPPED)
                self._busy_task = task_id
            try:
                yield
            finally:
                with self._gate:
                    self._busy_task = None

    @contextmanager
    def submission(self, task_id):
        with self._gate:
            if not self._accepting:
                raise ApplicationError(Code.RUNTIME_STOPPED)
            if self._busy_task == task_id:
                raise ApplicationError(Code.TASK_EXECUTION_ALREADY_ACTIVE)
            yield

    @contextmanager
    def job(self, job_id):
        # Trusted worker context only. HTTP inputs never set this capability.
        self._local.job_id = job_id
        try:
            yield
        finally:
            self._local.job_id = None
