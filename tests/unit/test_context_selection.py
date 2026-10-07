"""Lossless, measured request-local selection and honest provider usage."""
import json
from hashlib import sha256
from uuid import uuid4
import pytest
from qa_sentinel.agents.base import ResearchContext, PlanContext
from qa_sentinel.agents.prompts import build_request
from qa_sentinel.domain.enums import AgentName as A
from qa_sentinel.models.base import ModelSettings, ModelError
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.schemas.research import ResearchOutput
from qa_sentinel.schemas.repository import RepositoryEvidence, RepositoryToolRequest, RepositoryToolResult, ReadFileData


def evidence(text, index, *, path="module.py", digest=None):
    request = RepositoryToolRequest(request_id=uuid4(), arguments=dict(tool="READ_FILE", path=path))
    raw = text.encode("utf-8")
    data = ReadFileData(path=path, sha256=digest or sha256(raw).hexdigest(), size_bytes=len(raw), content=text)
    return RepositoryEvidence(evidence_ref="artifact:" + str(uuid4()), call_index=index, request=request,
        result=RepositoryToolResult(request_id=request.request_id, tool=request.tool, status="SUCCESS",
            data=data, error_code=None, returned_bytes=len(data.model_dump_json().encode("utf-8"))))


@pytest.mark.parametrize("role", [A.RESEARCHER, A.PLANNER])
def test_reused_data_is_lossless_inline_and_measurably_smaller(role, workflow_outputs):
    text = "Important original UTF-8 source é with no omitted lines.\n" * 250
    reads = tuple(evidence(text, i) for i in range(1, 5))
    context = ResearchContext(task_id=uuid4(), attempt=1, requirement="Required text", repository_results=reads)
    if role == A.PLANNER:
        context = PlanContext(task_id=context.task_id, attempt=1, requirement=context.requirement,
            repository_results=reads, research=workflow_outputs["research"], research_artifact_id=uuid4())
    request = build_request(role, context, ModelSettings(model="test"), repository_tools=True)
    selected = json.loads(request.user_input)
    records = selected["repository_results"]
    assert selected["requirement"] == "Required text" and len(records) == len(reads)
    known = {}
    for original, record in zip(reads, records):
        result = record["result"]
        reconstructed = known[result["data_ref"]] if "data_ref" in result else result["data"]
        assert reconstructed == original.result.data.model_dump(mode="json")
        known[record["evidence_ref"]] = reconstructed
        assert record["request"] == original.request.model_dump(mode="json")
        assert record["evidence_ref"] == original.evidence_ref
        assert result["status"] == "SUCCESS" and result["returned_bytes"] == original.result.returned_bytes
    assert records[0]["result"]["data"]["content"] == text
    assert all(r["result"]["data_ref"] == reads[0].evidence_ref for r in records[1:])
    assert request.context_selection.reused_results == 3
    assert request.context_selection.selected_chars < request.context_selection.original_chars * 0.4
    assert request.context_selection.selected_chars == len(request.user_input)
    assert request.context_selection.selected_bytes == len(request.user_input.encode("utf-8"))
    assert "same input" in request.system_instructions and "No external lookup" in request.system_instructions
    if role == A.PLANNER:
        assert selected["accepted_research"]["findings"] == workflow_outputs["research"].model_dump(mode="json")["findings"]
        assert selected["research_artifact_ref"] == str(context.research_artifact_id)


@pytest.mark.parametrize("change", ["content", "hash", "path"])
def test_differing_required_source_is_never_replaced_by_a_reference(change):
    first = evidence("Required source body " * 500, 1)
    second = evidence(first.result.data.content, 2,
        path="other.py" if change == "path" else "module.py",
        digest="f" * 64 if change == "hash" else first.result.data.sha256)
    if change == "content":
        second = evidence("Different source body " * 500, 2, digest=first.result.data.sha256)
    context = ResearchContext(task_id=uuid4(), attempt=1, requirement="R", repository_results=(first, second))
    request = build_request(A.RESEARCHER, context, ModelSettings(model="test"), repository_tools=True)
    records = json.loads(request.user_input)["repository_results"]
    assert all("data" in record["result"] and "data_ref" not in record["result"] for record in records)
    assert request.context_selection.reused_results == 0
    assert request.context_selection.selected_chars == request.context_selection.original_chars


def test_dedup_is_not_persistent_memory_and_cannot_drop_oversized_required_content():
    text = "x" * 30000
    first, second, third = (evidence(text, i) for i in (1, 2, 3))
    context = ResearchContext(task_id=uuid4(), attempt=1, requirement="R", repository_results=(first, second, third))
    request = build_request(A.RESEARCHER, context, ModelSettings(model="test"), repository_tools=True)
    assert request.context_selection.original_chars > 60000 and request.context_selection.selected_chars < 60000
    solo = build_request(A.RESEARCHER, context.model_copy(update={"repository_results": (third,)}),
                         ModelSettings(model="test"), repository_tools=True)
    assert json.loads(solo.user_input)["repository_results"][0]["result"]["data"]["content"] == text
    oversized = context.model_copy(update={"repository_results": (evidence("x" * 60001, 1),)})
    with pytest.raises(ModelError, match="CONTEXT_LIMIT"):
        build_request(A.RESEARCHER, oversized, ModelSettings(model="test"), repository_tools=True)


@pytest.mark.parametrize("usage,expected", [(None, (None,None,None,None)),
    ({"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, (0,0,None,0)),
    ({"input_tokens": 75, "output_tokens": 1186, "total_tokens": 1261,
      "output_tokens_details": {"reasoning_tokens": 1024}}, (75,1186,1024,1261))])
def test_official_sdk_usage_is_authoritative_and_missing_is_not_zero(mock_openai, workflow_outputs, usage, expected):
    mock = mock_openai([workflow_outputs["research"]], usage_override=usage)
    context = ResearchContext(task_id=uuid4(), attempt=1, requirement="Required context")
    request = build_request(A.RESEARCHER, context, ModelSettings(model="test"))
    result = OpenAIModelAdapter(client=mock.client).generate(request, ResearchOutput)
    meta = result.metadata
    assert (meta.input_tokens, meta.output_tokens, meta.reasoning_tokens, meta.total_tokens) == expected
    assert meta.context_selection == request.context_selection
    assert len(mock.calls) == 1 and mock.calls[0]["tools"] == []
    assert "context_selection" not in mock.calls[0]


@pytest.mark.parametrize("item,status", [("refusal", "completed"), (None,"incomplete")])
def test_failed_response_retains_only_safe_authoritative_usage(mock_openai, workflow_outputs, item, status):
    mock = mock_openai([workflow_outputs["research"] if item is None else item], response_status=status)
    request = build_request(A.RESEARCHER, ResearchContext(task_id=uuid4(), attempt=1, requirement="R"), ModelSettings(model="test"))
    with pytest.raises(ModelError) as caught:
        OpenAIModelAdapter(client=mock.client).generate(request, ResearchOutput)
    assert caught.value.metadata.total_tokens == 30 and caught.value.metadata.status == status
    assert "synthetic-sensitive-refusal" not in repr(vars(caught.value))



def test_runtime_revalidation_preserves_available_provider_usage(workflow_outputs):
    from types import SimpleNamespace
    from qa_sentinel.agents.real import RealAgentRuntime
    from qa_sentinel.models.base import ModelMetadata, ModelResponse
    meta = ModelMetadata(model="provider-version", input_tokens=10, output_tokens=20, total_tokens=30, latency_ms=1)
    adapter = SimpleNamespace(generate=lambda *a: ModelResponse(parsed_output=workflow_outputs["plan"], metadata=meta))
    context = ResearchContext(task_id=uuid4(), attempt=1, requirement="Required")
    with pytest.raises(ModelError, match="MALFORMED_RESPONSE") as caught:
        RealAgentRuntime(adapter).run(A.RESEARCHER, context)
    assert caught.value.metadata == meta and caught.value.changed_input
