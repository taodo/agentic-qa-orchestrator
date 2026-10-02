"""One durable-queue worker. No workflow routing, retries or Task state writes."""
import threading
from qa_sentinel.application import ApplicationError, ApplicationErrorCode as Code
from qa_sentinel.domain.execution_job import ExecutionJobStatus as Status, ExecutionJobError as Error
from .config import HostError


class ExecutionWorker:
    def __init__(self, application, admission, wake, *, on_exit=None):
        self.application, self.admission, self.wake = application, admission, wake
        self._stop = threading.Event()
        self._claim_gate = threading.Lock()  # Stop/claim atomicity, never workflow work.
        self._thread = None
        self._closed = False
        self._on_exit = on_exit
        self.failed = False

    def start(self):
        with self._claim_gate:
            if self._thread is not None or self._stop.is_set():
                raise HostError("HOST_EXECUTION_WORKER_INVALID_STATE")
            try:
                # ASGI lifespan awaits this before yielding/accepting requests.
                self.admission.stop_accepting()
                self.application.reconcile_execution_jobs()
                self._thread = threading.Thread(target=self._loop, name="qa-sentinel-execution", daemon=True)
                self.wake.set()  # Durable QUEUED work is read from SQLite, not memory.
                self.admission.start_accepting()
                self._thread.start()
            except BaseException:
                self._fail_closed()
                raise HostError("HOST_EXECUTION_WORKER_START_FAILED") from None

    def stop(self, timeout=5.0):
        with self._claim_gate:
            self._stop.set()
            self.admission.stop_accepting()
        self.wake.set()
        if self._thread is not None and self._thread.ident is not None:
            self._thread.join(timeout)
        return self._thread is None or not self._thread.is_alive()

    def close(self):
        # ASGI lifespan and CLI finally both close composition. Join only once.
        with self._claim_gate:
            if self._closed:
                return self._thread is None or not self._thread.is_alive()
            self._closed = True
        return self.stop()

    def execute_one(self):
        """Deterministic single-step entry point for tests and the one host thread."""
        try:
            with self.admission.enter():
                with self._claim_gate:
                    if self._stop.is_set():
                        return False
                    job = self.application.claim_next_execution_job()
                if job is None:
                    return False
                status, error = Status.SUCCEEDED, None
                with self.admission.job(job.id):
                    try:
                        self.application.run_task(job.task_id, project_id=job.project_id)
                    except ApplicationError as exc:
                        if exc.code == Code.RUNTIME_STOPPED:
                            status, error = Status.STOPPED, Error.RUNTIME_STOPPED
                        else:
                            status, error = Status.FAILED, Error.EXECUTION_FAILED
                    except Exception:
                        status, error = Status.FAILED, Error.EXECUTION_FAILED
                self.application.finish_execution_job(job.id, status=status, safe_error_code=error)
                return True
        except ApplicationError as exc:
            if exc.code == Code.RUNTIME_STOPPED:
                return False  # Another synchronous command owns admission; no claim.
            self._fail_closed()
            raise HostError("HOST_EXECUTION_PERSISTENCE_UNCERTAIN") from None
        except Exception:
            # Failed claim/completion: no blind retry, even if commit was uncertain.
            self._fail_closed()
            raise HostError("HOST_EXECUTION_PERSISTENCE_UNCERTAIN") from None

    def _fail_closed(self):
        self.failed = True
        self._stop.set()
        self.admission.stop_accepting()

    def _loop(self):
        try:
            while not self._stop.is_set():
                # Bounded idle recheck recovers a lost wakeup; it never retries work.
                self.wake.wait(0.5)
                self.wake.clear()
                while not self._stop.is_set() and self.execute_one():
                    pass
        except BaseException:
            # No raw exception/traceback reaches logs or persistence. An uncertain
            # RUNNING reservation remains for explicit startup reconciliation.
            self._fail_closed()
        finally:
            if self._on_exit is not None:
                try:
                    self._on_exit()
                except BaseException:
                    self._fail_closed()
