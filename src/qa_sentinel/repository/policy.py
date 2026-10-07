"""Read authorization independent of Task 9 mutation policy."""
from pathlib import PureWindowsPath
import stat
from qa_sentinel.domain.enums import AgentName

PROTECTED = {".git", ".github", ".env", ".ssh", ".aws", ".azure", ".codex", ".agents",
    ".venv", "venv", "env", "node_modules", "site-packages", "__pycache__", ".cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox", ".nox", "build", "dist",
    "task4-test-deps", "task7-sdk-deps", "codex-runtimes", "interpreter", "runtime",
    "id_rsa", "id_ed25519"}


class RepositoryReadFailure(Exception):
    def __init__(self, code, *, denied=False, bytes_read=0):
        super().__init__(code)
        self.code, self.denied = code, denied
        self.bytes_read = bytes_read


class RepositoryToolPolicy:
    def __init__(self, config):
        self.config = config

    @staticmethod
    def protected(part):
        lower = part.casefold()
        return (lower in PROTECTED or lower.startswith(".env.") or "credential" in lower or
                "secret" in lower or lower.endswith((".pem", ".key", ".p12", ".pfx")))

    def authorize(self, role, request, *, calls_used):
        if role not in {AgentName.RESEARCHER, AgentName.PLANNER}:
            raise RepositoryReadFailure("ROLE_NOT_AUTHORIZED", denied=True)
        if calls_used >= self.config.max_tool_calls_per_agent_invocation:
            raise RepositoryReadFailure("TOOL_CALL_BUDGET_EXHAUSTED", denied=True)
        args = request.arguments
        # Search limit is a requested output count, capped by the service's host limit.
        # It cannot authorize more reads/results or bypass the remaining policy checks.
        if args.tool == "LIST_FILES" and args.limit > self.config.max_list_results:
            raise RepositoryReadFailure("RESULT_LIMIT_EXCEEDED", denied=True)
        if getattr(args, "depth", 0) > self.config.max_depth:
            raise RepositoryReadFailure("DEPTH_LIMIT_EXCEEDED", denied=True)
        query = getattr(args, "query", None)
        if query is not None and (not query.strip() or any(ord(c) < 32 for c in query)):
            raise RepositoryReadFailure("INVALID_QUERY", denied=True)
        if query is not None and len(query) > self.config.max_snippet_chars:
            raise RepositoryReadFailure("INVALID_QUERY", denied=True)
        return self.target(args.path, allow_root=args.tool != "READ_FILE")

    def target(self, value, *, allow_root=False):
        if value == "." and allow_root:
            parts = ()
        else:
            if (not isinstance(value, str) or not value or len(value) > 1024 or "\\" in value or
                ":" in value or value.startswith("/") or PureWindowsPath(value).drive or
                any(ord(c) < 32 for c in value)):
                raise RepositoryReadFailure("WORKSPACE_ESCAPE", denied=True)
            parts = value.split("/")
            if any(p in {"", ".", ".."} or p != p.strip() or p.endswith(".") for p in parts):
                raise RepositoryReadFailure("WORKSPACE_ESCAPE", denied=True)
        for part in (*self.config.repository_root.parts, *parts):
            lower = part.casefold().split(".")[0]
            if self.protected(part):
                raise RepositoryReadFailure("PROTECTED_PATH", denied=True)
            if lower in {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}:
                raise RepositoryReadFailure("INVALID_PATH", denied=True)
        try:
            current = self.config.repository_root
            if current.resolve(strict=True) != current:
                raise RepositoryReadFailure("WORKSPACE_ESCAPE", denied=True)
            for part in parts:
                current = current / part
                if current.is_symlink() or current.is_junction():
                    raise RepositoryReadFailure("WORKSPACE_ESCAPE", denied=True)
            resolved = current.resolve(strict=False)
            if not resolved.is_relative_to(self.config.repository_root):
                raise RepositoryReadFailure("WORKSPACE_ESCAPE", denied=True)
            return resolved
        except (OSError, RuntimeError):
            raise RepositoryReadFailure("PATH_UNAVAILABLE") from None

    def read(self, path, *, byte_budget=None):
        consumed = 0
        limit = self.config.max_file_bytes if byte_budget is None else min(self.config.max_file_bytes, byte_budget)
        try:
            path = self.target(path.relative_to(self.config.repository_root).as_posix())
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise RepositoryReadFailure("INVALID_FILE_TYPE")
            if path.suffix.casefold() not in self.config.allowed_extensions:
                raise RepositoryReadFailure("EXTENSION_NOT_ALLOWED", denied=True)
            if info.st_size > self.config.max_file_bytes:
                raise RepositoryReadFailure("FILE_TOO_LARGE")
            if info.st_size > limit:
                raise RepositoryReadFailure("SEARCH_SCAN_LIMIT_EXCEEDED")
            with path.open("rb") as handle:
                data = handle.read(limit + 1)
            consumed = len(data)
            if consumed > limit:
                raise RepositoryReadFailure("FILE_TOO_LARGE" if byte_budget is None else "SEARCH_SCAN_LIMIT_EXCEEDED",
                                            bytes_read=consumed)
            text = data.decode("utf-8")
            if "\0" in text:
                raise RepositoryReadFailure("INVALID_ENCODING", bytes_read=consumed)
            return data, text
        except FileNotFoundError:
            raise RepositoryReadFailure("PATH_NOT_FOUND") from None
        except UnicodeError:
            raise RepositoryReadFailure("INVALID_ENCODING", bytes_read=consumed) from None
        except OSError:
            raise RepositoryReadFailure("READ_FAILED", bytes_read=limit) from None
