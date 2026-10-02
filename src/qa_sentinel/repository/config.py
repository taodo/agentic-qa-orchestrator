from dataclasses import dataclass
from pathlib import Path
from hashlib import sha256
import json


@dataclass(frozen=True)
class RepositoryReadConfig:
    repository_root: Path
    max_file_bytes: int = 128 * 1024
    max_total_bytes_per_invocation: int = 512 * 1024
    max_list_results: int = 200
    max_search_results: int = 50
    max_tool_calls_per_agent_invocation: int = 8
    max_depth: int = 5
    max_scanned_entries: int = 2000
    max_search_bytes: int = 2 * 1024 * 1024
    max_snippet_chars: int = 512
    allowed_extensions: tuple[str, ...] = (".py", ".md", ".txt", ".toml", ".json", ".yaml", ".yml", ".ini", ".cfg", ".rst")

    def __post_init__(self):
        root = Path(self.repository_root).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Repository root must be an existing directory")
        for name in ("max_file_bytes", "max_total_bytes_per_invocation", "max_list_results",
                     "max_search_results", "max_tool_calls_per_agent_invocation", "max_depth",
                     "max_scanned_entries", "max_search_bytes", "max_snippet_chars"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError("Repository limits must be positive integers")
        extensions = tuple(self.allowed_extensions)
        if not extensions or any(not isinstance(e, str) or not e.startswith(".") or
                                 len(e) > 16 or not e[1:].isalnum() for e in extensions):
            raise ValueError("Allowed extensions must be explicit suffixes")
        object.__setattr__(self, "repository_root", root)
        object.__setattr__(self, "allowed_extensions", tuple(sorted({e.casefold() for e in extensions})))

    @property
    def identity(self):
        # Configuration and canonical root identity must remain consistent on resume.
        values = {**vars(self), "repository_root": str(self.repository_root)}
        return sha256(json.dumps(values, sort_keys=True).encode("utf-8")).hexdigest()
