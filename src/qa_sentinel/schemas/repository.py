"""Narrow read-only application protocol; no provider function/tool definitions."""
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from qa_sentinel.domain.types import Count, Attempt, NonBlank
from .research import ResearchOutput
from .plan import PlannerOutput


class Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
RelativePath = Annotated[str, Field(min_length=1, max_length=1024)]


class RepositoryToolName(StrEnum):
    LIST_FILES = "LIST_FILES"
    READ_FILE = "READ_FILE"
    SEARCH_TEXT = "SEARCH_TEXT"


class ListFilesArgs(Frozen):
    tool: Literal["LIST_FILES"]
    path: RelativePath
    depth: int = Field(ge=0, le=5, strict=True)
    limit: int = Field(ge=1, le=1000, strict=True)


class ReadFileArgs(Frozen):
    tool: Literal["READ_FILE"]
    path: RelativePath


class SearchTextArgs(Frozen):
    tool: Literal["SEARCH_TEXT"]
    query: str = Field(min_length=1, max_length=256)
    path: RelativePath
    limit: int = Field(ge=1, le=1000, strict=True, description=(
        "Requested maximum matches, capped by the host search-result ceiling. "
        "Use a narrower directory or literal query when returned matches are truncated."))


class RepositoryToolRequest(Frozen):
    request_id: UUID
    # Literal-tagged, extra-forbidden alternatives produce native supported anyOf.
    # No top-level union or unsupported JSON Schema oneOf/discriminator is needed.
    arguments: ListFilesArgs | ReadFileArgs | SearchTextArgs

    @property
    def tool(self):
        return RepositoryToolName(self.arguments.tool)


class FileEntry(Frozen):
    path: NonBlank
    entry_type: Literal["FILE", "DIRECTORY"]
    size_bytes: Count | None


class ListFilesData(Frozen):
    tool: Literal["LIST_FILES"] = "LIST_FILES"
    entries: tuple[FileEntry, ...]
    truncated: bool


class ReadFileData(Frozen):
    tool: Literal["READ_FILE"] = "READ_FILE"
    path: NonBlank
    sha256: Sha256
    size_bytes: Count
    content: str


class SearchMatch(Frozen):
    path: NonBlank
    line_number: Attempt
    snippet: str
    snippet_truncated: bool
    sha256: Sha256


class SearchTextData(Frozen):
    tool: Literal["SEARCH_TEXT"] = "SEARCH_TEXT"
    matches: tuple[SearchMatch, ...]
    truncated: bool
    skipped_files: Count
    # Missing metadata remains valid for immutable evidence recorded before Task 26.
    result_limit: int | None = Field(default=None, ge=1, le=1000, strict=True)
    limit_capped: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def bounded_matches(self):
        if self.result_limit is not None and len(self.matches) > self.result_limit:
            raise ValueError("Search matches cannot exceed the applied result limit")
        if self.limit_capped and self.result_limit is None:
            raise ValueError("Capped search results require an applied result limit")
        return self


class RepositoryToolResult(Frozen):
    request_id: UUID
    tool: RepositoryToolName
    status: Literal["SUCCESS", "DENIED", "ERROR"]
    data: ListFilesData | ReadFileData | SearchTextData | None
    error_code: NonBlank | None
    returned_bytes: Count = 0

    @model_validator(mode="after")
    def consistent(self):
        if self.status == "SUCCESS":
            if self.data is None or self.error_code is not None or self.data.tool != self.tool.value:
                raise ValueError("Successful results require matching typed data")
        elif self.data is not None or self.error_code is None or self.returned_bytes:
            raise ValueError("Failure results cannot expose partial content")
        return self


class RepositoryEvidence(Frozen):
    evidence_ref: NonBlank
    call_index: Attempt
    request: RepositoryToolRequest
    result: RepositoryToolResult

    @model_validator(mode="after")
    def matching(self):
        if self.request.request_id != self.result.request_id or self.request.tool != self.result.tool:
            raise ValueError("Evidence must match request and result")
        return self


class Turn(Frozen):
    kind: Literal["TOOL_REQUEST", "FINAL_OUTPUT"]
    tool_request: RepositoryToolRequest | None

    @model_validator(mode="after")
    def one_payload(self):
        if (self.kind == "TOOL_REQUEST") != (self.tool_request is not None):
            raise ValueError("Tool turn must have exactly one request")
        if (self.kind == "FINAL_OUTPUT") != (self.final_output is not None):
            raise ValueError("Final turn must have exactly one final output")
        return self


class ResearchTurn(Turn):
    final_output: ResearchOutput | None


class PlannerTurn(Turn):
    final_output: PlannerOutput | None
