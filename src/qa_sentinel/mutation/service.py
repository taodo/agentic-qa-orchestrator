"""Bounded UTF-8 snapshots and reversible local file application; no DB/model/tools."""
from hashlib import sha256
from pathlib import Path
import os
import tempfile
from qa_sentinel.schemas.mutation import SourceFileSnapshot, MutationOperation as Op
from .contracts import MutationConfig, AppliedFile, ApplicationResult, PolicyDecision, MutationFailure
from .policy import MutationPolicy


class MutationService:
    def __init__(self, config: MutationConfig):
        self.config = config
        self.policy = MutationPolicy(config)

    @property
    def workspace_identity(self):
        return sha256(str(self.config.workspace_root).encode("utf-8")).hexdigest()

    def build_snapshots(self, plan):
        creates, sources = self.policy.snapshot_scope(plan)
        snapshots = []
        total = 0
        for name in sorted(sources):
            if name in creates and not os.path.lexists(self.policy.target(name)):
                continue
            data, text, _ = self.policy.read_text(self.policy.target(name), self.config.max_source_file_bytes)
            total += len(data)
            if total > self.config.max_source_total_bytes:
                raise MutationFailure("SOURCE_LIMIT")
            snapshots.append(SourceFileSnapshot(path=name, sha256=sha256(data).hexdigest(), content=text, size_bytes=len(data)))
        return tuple(snapshots)

    @staticmethod
    def _stage(target, content, mode):
        fd, name = tempfile.mkstemp(prefix=".qa-mutation-", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None:
                os.chmod(name, mode)
            return Path(name)
        except BaseException:
            try:
                os.unlink(name)
            except OSError:
                pass
            raise

    @staticmethod
    def _apply_file(item, staged):
        if item.mutation.operation == Op.CREATE:
            # Atomic exclusive publication of prepared bytes; never replaces an existing name.
            try:
                os.link(staged, item.target)
            except FileExistsError:
                raise MutationFailure("CREATE_TARGET_EXISTS") from None
        else:
            os.replace(staged, item.target)

    def _check_current(self, item):
        if self.policy.target(item.mutation.path) != item.target:
            raise MutationFailure("WORKSPACE_ESCAPE")
        if item.mutation.operation == Op.CREATE:
            if os.path.lexists(item.target):
                raise MutationFailure("CREATE_TARGET_EXISTS")
        else:
            data, _, _ = self.policy.read_text(item.target, self.config.max_source_file_bytes)
            if sha256(data).hexdigest() != item.mutation.expected_sha256:
                raise MutationFailure("STALE_SOURCE")

    def _rollback_file(self, item):
        # Do not clobber unrelated edits if a concurrent writer changed an applied file.
        if self.policy.target(item.mutation.path) != item.target:
            raise MutationFailure("WORKSPACE_ESCAPE")
        data, _, _ = self.policy.read_text(item.target, self.config.max_result_file_bytes, allow_links=item.original is None)
        if sha256(data).hexdigest() != sha256(item.replacement).hexdigest():
            raise MutationFailure("STALE_SOURCE")
        if item.original is None:
            item.target.unlink()
        else:
            restore = self._stage(item.target, item.original, item.mode)
            try:
                os.replace(restore, item.target)
            finally:
                self._remove_temp(restore)

    @staticmethod
    def _remove_temp(path):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # Cleanup may leave a staging file; it never changes an authorized target.

    def apply(self, plan, snapshots, proposal):
        decision, prepared = self.policy.prepare(plan, snapshots, proposal)
        if not decision.allowed:
            return ApplicationResult(success=False, decision=decision)
        staged = []
        applied = []
        publication_uncertain = False
        try:
            for item in prepared:
                staged.append(self._stage(item.target, item.replacement, item.mode))
            # Revalidate the complete set after preparation, before the first target write.
            for item in prepared:
                self._check_current(item)
            for item, temporary in zip(prepared, staged):
                self._check_current(item)
                try:
                    self._apply_file(item, temporary)
                except OSError:
                    # A wrapper/filesystem may report failure after publication. Track our
                    # published inode so that this file participates in rollback as well.
                    try:
                        published = (os.path.samefile(temporary, item.target)
                                     if temporary.exists() and item.target.exists() else
                                     not temporary.exists() and item.target.exists())
                    except OSError:
                        publication_uncertain = True
                        raise
                    if published:
                        applied.append(item)
                    raise
                applied.append(item)
                if item.mutation.operation == Op.CREATE:
                    temporary.unlink()  # Drop staging link before ordinary file validation/rollback.
            facts = tuple(AppliedFile(path=item.mutation.path, operation=item.mutation.operation,
                before_sha256=None if item.original is None else sha256(item.original).hexdigest(),
                after_sha256=sha256(item.replacement).hexdigest(), size_bytes=len(item.replacement)) for item in applied)
            return ApplicationResult(success=True, decision=decision, applied=facts)
        except (OSError, MutationFailure) as failure:
            code = failure.code if isinstance(failure, MutationFailure) else "MUTATION_APPLY_FAILED"
            rollback = "FAILED" if publication_uncertain else "NOT_NEEDED"
            if applied:
                rollback = "FAILED" if publication_uncertain else "SUCCEEDED"
                for item in reversed(applied):
                    try:
                        self._rollback_file(item)
                    except (OSError, MutationFailure):
                        rollback = "FAILED"
            return ApplicationResult(success=False,
                decision=PolicyDecision(allowed=False, reason_code=code, reason="File application did not complete."),
                rollback=rollback)
        finally:
            for path in staged:
                self._remove_temp(path)

    def verify_applied(self, facts, workspace_identity):
        if workspace_identity != self.workspace_identity:
            raise MutationFailure("APPLIED_EVIDENCE_MISMATCH")
        for raw in facts:
            fact = AppliedFile.model_validate(raw)
            data, _, _ = self.policy.read_text(self.policy.target(fact.path), self.config.max_result_file_bytes)
            if len(data) != fact.size_bytes or sha256(data).hexdigest() != fact.after_sha256:
                raise MutationFailure("APPLIED_EVIDENCE_MISMATCH")
