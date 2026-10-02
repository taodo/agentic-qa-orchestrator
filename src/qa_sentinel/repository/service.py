"""Local read-only service: no models, subprocesses, mutation, DB or workflow."""
from hashlib import sha256
import os
import stat
from pydantic import ValidationError
from qa_sentinel.schemas.repository import (RepositoryToolRequest, RepositoryToolResult,
    ListFilesArgs, ReadFileArgs, SearchTextArgs, ListFilesData, ReadFileData,
    SearchTextData, FileEntry, SearchMatch)
from .policy import RepositoryToolPolicy, RepositoryReadFailure


class RepositoryReadService:
    def __init__(self, config):
        self.config, self.policy = config, RepositoryToolPolicy(config)

    def _entries(self, directory, depth):
        # Cap enumeration work before sorting; do not materialize arbitrary huge walks.
        entries, scanned = [], 0
        pending = [(directory, 0)]
        while pending:
            folder, level = pending.pop()
            folder = self.policy.target(folder.relative_to(self.config.repository_root).as_posix()
                                        if folder != self.config.repository_root else ".", allow_root=True)
            with os.scandir(folder) as iterator:
                for entry in iterator:
                    scanned += 1
                    if scanned > self.config.max_scanned_entries:
                        raise RepositoryReadFailure("SCAN_LIMIT_EXCEEDED")
                    relative = os.path.relpath(entry.path, self.config.repository_root).replace("\\", "/")
                    try:
                        target = self.policy.target(relative)
                        info = target.lstat()
                    except (RepositoryReadFailure, OSError):
                        continue
                    if stat.S_ISDIR(info.st_mode):
                        entries.append(FileEntry(path=relative, entry_type="DIRECTORY", size_bytes=None))
                        if level < depth:
                            pending.append((target, level + 1))
                    elif (stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and
                          target.suffix.casefold() in self.config.allowed_extensions):
                        entries.append(FileEntry(path=relative, entry_type="FILE", size_bytes=info.st_size))
        return tuple(sorted(entries, key=lambda e: e.path))

    def execute(self, role, request, *, calls_used=0, bytes_used=0):
        # Host-supplied usage is never obtained from model arguments.
        if type(calls_used) is not int or calls_used < 0 or type(bytes_used) is not int or bytes_used < 0:
            raise ValueError("Usage must be nonnegative host integers")
        try:
            request = RepositoryToolRequest.model_validate(request.model_dump(mode="json"))
            path = self.policy.authorize(role, request, calls_used=calls_used)
            args = request.arguments
            if isinstance(args, ReadFileArgs):
                data, text = self.policy.read(path)
                output = ReadFileData(path=args.path, sha256=sha256(data).hexdigest(), size_bytes=len(data), content=text)
            else:
                if not path.is_dir():
                    raise RepositoryReadFailure("DIRECTORY_EXPECTED")
                entries = self._entries(path, args.depth if isinstance(args, ListFilesArgs) else self.config.max_depth)
                if isinstance(args, ListFilesArgs):
                    output = ListFilesData(entries=entries[:args.limit], truncated=len(entries) > args.limit)
                elif isinstance(args, SearchTextArgs):
                    matches, skipped, scanned_bytes = [], 0, 0
                    for entry in entries:
                        if entry.entry_type != "FILE":
                            continue
                        # Bound all bytes examined, not only matching output.
                        try:
                            data, text = self.policy.read(self.policy.target(entry.path),
                                byte_budget=self.config.max_search_bytes - scanned_bytes)
                        except RepositoryReadFailure as failure:
                            scanned_bytes += failure.bytes_read
                            if failure.code == "SEARCH_SCAN_LIMIT_EXCEEDED" or scanned_bytes > self.config.max_search_bytes:
                                raise RepositoryReadFailure("SEARCH_SCAN_LIMIT_EXCEEDED") from None
                            skipped += 1
                            continue
                        scanned_bytes += len(data)
                        digest = sha256(data).hexdigest()
                        for number, line in enumerate(text.splitlines(), 1):
                            position = line.find(args.query)  # Literal; model input is never regex/code.
                            if position < 0:
                                continue
                            start = max(0, position - min(64, self.config.max_snippet_chars - len(args.query)))
                            snippet = line[start:start + self.config.max_snippet_chars]
                            matches.append(SearchMatch(path=entry.path, line_number=number,
                                snippet=snippet, snippet_truncated=start > 0 or len(snippet) < len(line), sha256=digest))
                            if len(matches) > args.limit:
                                break
                        if len(matches) > args.limit:
                            break
                    output = SearchTextData(matches=tuple(matches[:args.limit]), truncated=len(matches) > args.limit,
                                            skipped_files=skipped)
                else:
                    raise RepositoryReadFailure("UNSUPPORTED_OPERATION", denied=True)
            size = len(output.model_dump_json().encode("utf-8"))
            if bytes_used + size > self.config.max_total_bytes_per_invocation:
                raise RepositoryReadFailure("TOTAL_BYTES_EXCEEDED", denied=True)
            return RepositoryToolResult(request_id=request.request_id, tool=request.tool, status="SUCCESS",
                data=output, error_code=None, returned_bytes=size)
        except RepositoryReadFailure as failure:
            return RepositoryToolResult(request_id=request.request_id, tool=request.tool,
                status="DENIED" if failure.denied else "ERROR", data=None, error_code=failure.code)
        except OSError:
            return RepositoryToolResult(request_id=request.request_id, tool=request.tool,
                status="ERROR", data=None, error_code="READ_FAILED")
        except ValidationError:
            # Invalid structured turns are handled as schema errors before entering here.
            raise ValueError("Repository service requires a validated typed request") from None
