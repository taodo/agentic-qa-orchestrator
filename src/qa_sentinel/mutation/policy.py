"""Whole-set validation and canonical plan authorization; no writing or execution."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path, PureWindowsPath
import os
import stat
from pydantic import ValidationError
from qa_sentinel.schemas.mutation import ImplementationProposal, MutationOperation as Op
from .contracts import MutationConfig, PolicyDecision, MutationFailure

PROTECTED = {".git", ".github", ".env", ".aws", ".ssh", ".azure", ".codex", ".agents", ".venv",
             "venv", "env", "node_modules", "__pycache__", "site-packages", "task4-test-deps", "task7-sdk-deps",
             "codex-runtimes", "interpreter", "runtime", ".cache", "credentials", "credentials.json",
             "credentials.ini", "secrets", "secrets.json", "id_rsa", "id_ed25519"}


@dataclass(frozen=True)
class PreparedFile:
    mutation: object
    target: Path
    original: bytes | None
    mode: int | None
    replacement: bytes


class MutationPolicy:
    def __init__(self, config: MutationConfig):
        self.config = config

    def target(self, value: str) -> Path:
        if (not isinstance(value, str) or not value or len(value) > 1024 or "\\" in value or
            ":" in value or value.startswith("/") or PureWindowsPath(value).drive or
            any(ord(c) < 32 for c in value)):
            raise MutationFailure("WORKSPACE_ESCAPE")
        parts = value.split("/")
        if any(p in {"", ".", ".."} or p != p.strip() or p.endswith(".") for p in parts):
            raise MutationFailure("WORKSPACE_ESCAPE")
        for part in (*self.config.workspace_root.parts, *parts):
            lower = part.casefold()
            device = lower.split(".")[0]
            if (lower in PROTECTED or lower.startswith(".env.") or lower.endswith((".pem", ".key", ".p12", ".pfx")) or
                "credential" in lower or "secret" in lower or device in {"con", "prn", "aux", "nul"} or
                device in {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}):
                raise MutationFailure("PROTECTED_PATH")
        try:
            current = self.config.workspace_root
            if current.resolve(strict=True) != current:
                raise MutationFailure("WORKSPACE_ESCAPE")
            for part in parts:
                current = current / part
                if current.is_symlink() or current.is_junction():
                    raise MutationFailure("WORKSPACE_ESCAPE")
            resolved = current.resolve(strict=False)
            parent_exists = resolved.parent.is_dir()
        except (OSError, RuntimeError):
            raise MutationFailure("WORKSPACE_ESCAPE") from None
        if not resolved.is_relative_to(self.config.workspace_root):
            raise MutationFailure("WORKSPACE_ESCAPE")
        if not parent_exists:
            raise MutationFailure("PARENT_DIRECTORY_MISSING")
        return resolved

    def authorization(self, plan):
        creates = set(plan.files_to_create)
        modifies = set(plan.files_to_modify) | {f for step in plan.implementation_steps for f in step.files}
        paths = creates | modifies
        if len(paths) > self.config.max_source_files:
            raise MutationFailure("SOURCE_LIMIT")
        if len({p.casefold() for p in paths}) != len(paths):
            raise MutationFailure("INVALID_PLAN_AUTHORIZATION")
        for path in sorted(paths):
            self.target(path)
        return creates, modifies

    @staticmethod
    def read_text(path, limit, *, allow_links=False):
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or (info.st_nlink > 1 and not allow_links):
                raise MutationFailure("INVALID_FILE_TYPE")
            if info.st_size > limit:
                raise MutationFailure("SOURCE_LIMIT")
            with path.open("rb") as handle:
                data = handle.read(limit + 1)
            if len(data) > limit:
                raise MutationFailure("SOURCE_LIMIT")
            text = data.decode("utf-8")
            if "\0" in text:
                raise MutationFailure("INVALID_ENCODING")
            return data, text, stat.S_IMODE(info.st_mode)
        except FileNotFoundError:
            raise MutationFailure("MODIFY_TARGET_MISSING") from None
        except UnicodeError:
            raise MutationFailure("INVALID_ENCODING") from None
        except OSError:
            raise MutationFailure("SOURCE_READ_FAILED") from None

    def prepare(self, plan, snapshots, proposal):
        try:
            if any(str(m.operation) == "DELETE" for m in proposal.mutations):
                raise MutationFailure("DELETE_NOT_ALLOWED")
            proposal = ImplementationProposal.model_validate(proposal.model_dump(mode="json"))
            creates, modifies = self.authorization(plan)
            if len(proposal.mutations) > self.config.max_mutations:
                raise MutationFailure("MUTATION_COUNT_LIMIT")
            names = [m.path.casefold() for m in proposal.mutations]
            if len(set(names)) != len(names):
                raise MutationFailure("DUPLICATE_TARGET")
            sources = {s.path: s for s in snapshots}
            prepared = []
            total = 0
            for mutation in proposal.mutations:
                target = self.target(mutation.path)
                if mutation.path not in (creates if mutation.operation == Op.CREATE else modifies):
                    raise MutationFailure("PATH_NOT_AUTHORIZED")
                replacement = mutation.content.encode("utf-8")
                if b"\0" in replacement:
                    raise MutationFailure("INVALID_ENCODING")
                if len(replacement) > self.config.max_result_file_bytes:
                    raise MutationFailure("FILE_TOO_LARGE")
                total += len(replacement)
                if total > self.config.max_total_change_bytes:
                    raise MutationFailure("TOTAL_CHANGE_LIMIT_EXCEEDED")
                if mutation.operation == Op.CREATE:
                    if os.path.lexists(target):
                        raise MutationFailure("CREATE_TARGET_EXISTS")
                    before, mode = None, None
                else:
                    source = sources.get(mutation.path)
                    before, _, mode = self.read_text(target, self.config.max_source_file_bytes)
                    if (source is None or source.sha256 != mutation.expected_sha256 or
                        sha256(before).hexdigest() != source.sha256 or
                        sha256(source.content.encode("utf-8")).hexdigest() != source.sha256 or
                        len(before) != source.size_bytes):
                        raise MutationFailure("STALE_SOURCE")
                prepared.append(PreparedFile(mutation, target, before, mode, replacement))
            return PolicyDecision(allowed=True, reason_code="MUTATION_ALLOWED", reason="Complete mutation set validated."), tuple(prepared)
        except MutationFailure as failure:
            return PolicyDecision(allowed=False, reason_code=failure.code, reason="Deterministic mutation policy rejected the set."), ()
        except (ValidationError, UnicodeError, AttributeError, TypeError):
            return PolicyDecision(allowed=False, reason_code="INVALID_MUTATION", reason="Mutation contract is invalid."), ()

    def evaluate(self, plan, snapshots, proposal):
        return self.prepare(plan, snapshots, proposal)[0]
