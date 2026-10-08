"""Model ranges select evidence; immutable LF source owns exact citation text."""
import json
from uuid import uuid4
import pytest
from pydantic import ValidationError
from qa_sentinel.agents.requirement_extraction import (
    RequirementExtractor, RequirementsOutput, validate_output, MAX_CONTEXT_CHARS, MAX_OUTPUT_BYTES)
from qa_sentinel.domain.campaign_content import SourceCitation, validate_citations
from qa_sentinel.models.base import ModelSettings, ModelError
from test_spec_ingestion import source, output


def select(value, ranges):
    result = output(value).model_dump(mode="json")
    result["requirements"][0]["source_references"] = [dict(source_id=str(value.id),
        source_hash=value.content_hash, start_line=start, end_line=end) for start,end in ranges]
    return RequirementsOutput.model_validate(result)


def test_numbered_context_complete_deterministic_and_honest_accounting():
    text = 'Heading\n\n0003 | embedded | text\n  bullet → 2026-10-12  \n"quoted"\n\tindented\n'
    value = source(text)
    extractor = RequirementExtractor(None, ModelSettings(model="test-model"))
    request = extractor.prepare(value)
    assert extractor.prepare(value) == request
    data = json.loads(request.user_input)
    assert data["line_numbered_text"] == "\n".join(f"{n:04d} | {line}" for n,line in enumerate(text.split("\n"),1))
    assert data["line_numbered_text"].endswith("0007 | ")
    # Recover each literal source line by removing exactly the backend prefix;
    # numbers/pipes inside the data cannot change position-based mapping.
    assert "\n".join(line[7:] for line in data["line_numbered_text"].split("\n")) == text
    assert "normalized_text" not in data  # No duplicate source payload.
    assert request.context_selection.original_chars == request.context_selection.selected_chars == len(request.user_input)
    assert request.context_selection.selected_bytes == len(request.user_input.encode("utf-8"))
    assert "UNTRUSTED DATA" in request.system_instructions
    assert "never excerpt text" in request.system_instructions


def test_number_width_supports_all_4096_lines():
    value = source("x\n" * 4095 + "last")
    request = RequirementExtractor(None, ModelSettings(model="test-model")).prepare(value)
    assert json.loads(request.user_input)["line_numbered_text"].endswith("4096 | last")


def test_numbering_overhead_can_exceed_bound_without_truncation():
    text = "\n".join(["x" * 55] * 1000)
    value = source(text)
    previous_context = dict(source_id=str(value.id), source_hash=value.content_hash,
        normalization_version=value.normalization_version, line_count=value.line_count,
        first_line=1, normalized_text=value.normalized_text)
    assert len(json.dumps(previous_context,ensure_ascii=False,sort_keys=True,separators=(",", ":"))) < MAX_CONTEXT_CHARS
    with pytest.raises(ModelError, match="MODEL_CONTEXT_LIMIT"):
        RequirementExtractor(None,ModelSettings(model="test-model")).prepare(value)
    assert value.normalized_text == text and value.line_count == 1000


def test_model_schema_has_ranges_without_excerpt_or_location_text():
    schema = RequirementsOutput.model_json_schema()
    fields = schema["$defs"]["CitationRange"]["properties"]
    assert set(fields) == {"source_id", "source_hash", "start_line", "end_line"}
    assert schema["$defs"]["CitationRange"]["additionalProperties"] is False
    value = source()
    result = output(value).model_dump(mode="json")
    result["requirements"][0]["source_references"][0]["excerpt"] = "Untrusted copied text"
    with pytest.raises(ValidationError):
        RequirementsOutput.model_validate(result)


@pytest.mark.parametrize("text,ranges", [
    ("\n  Evidence with whitespace  \n\nMore evidence\n", [(1,3),(3,5)]),
    ("# Header\r\n\r\n- Check-in 2026-10-10 → 2026-10-12\r\n", [(1,3)]),
    ("a"*512, [(1,1)]),
])
def test_canonical_excerpts_preserve_whitespace_lf_and_exact_limit(text,ranges):
    value = source(text)
    grounded = validate_output(value, select(value,ranges))
    expected = ["\n".join(value.normalized_text.split("\n")[start-1:end]) for start,end in ranges]
    assert [ref.excerpt for ref in grounded.requirements[0].source_references] == expected
    assert all("\r" not in ref.excerpt for ref in grounded.requirements[0].source_references)
    validate_citations(value,grounded.requirements,canonical=True)
    assert SourceCitation.model_validate(grounded.requirements[0].source_references[0].model_dump()).excerpt == expected[0]


@pytest.mark.parametrize("change", ["id", "hash", "beyond", "coverage-id", "coverage-hash", "coverage-end"])
def test_identity_and_range_must_match_immutable_source(change):
    value = source("Evidence\nSecond line")
    result = select(value,[(1,1)]).model_dump(mode="json")
    ref = result["requirements"][0]["source_references"][0]
    if change == "id": ref["source_id"] = str(uuid4())
    elif change == "hash": ref["source_hash"] = "0"*64
    elif change == "beyond": ref["end_line"] = 3
    elif change == "coverage-id": result["source_id"] = str(uuid4())
    elif change == "coverage-hash": result["source_hash"] = "0"*64
    else: result["analyzed_end_line"] = 1
    with pytest.raises(ValueError,match="EXTRACTION_INVALID_CITATION"):
        validate_output(value,RequirementsOutput.model_validate(result))


@pytest.mark.parametrize("start,end", [(2,1),(0,1),(1,4097),(True,1),(1,1.0)])
def test_schema_rejects_reversed_noninteger_and_illegal_line_bounds(start,end):
    value = source()
    with pytest.raises(ValidationError):
        select(value,[(start,end)])


@pytest.mark.parametrize("text,ranges", [("a"*513,[(1,1)]),("a"*256+"\n"+"b"*256,[(1,2)]),("Evidence\n\n\n",[(2,3)])])
def test_oversized_or_blank_only_canonical_evidence_is_rejected(text,ranges):
    value = source(text)
    with pytest.raises(ValueError,match="EXTRACTION_INVALID_CITATION"):
        validate_output(value,select(value,ranges))


def test_multiple_requirements_and_ranges_are_grounded_independently():
    value = source("First evidence\n\nSecond evidence\nThird evidence")
    result = select(value,[(1,2)]).model_dump(mode="json")
    second = select(value,[(3,3),(4,4)]).model_dump(mode="json")["requirements"][0]
    second["key"] = "SECOND"
    result["requirements"].append(second)
    grounded = validate_output(value,RequirementsOutput.model_validate(result))
    assert [[ref.excerpt for ref in req.source_references] for req in grounded.requirements] == [["First evidence\n"],["Second evidence","Third evidence"]]


def test_legacy_substring_valid_but_new_canonical_contract_rejects_it():
    value = source("User must log in.")
    grounded = validate_output(value,output(value))
    legacy = grounded.requirements[0].model_copy(update={"source_references":(
        SourceCitation(source_id=value.id,source_hash=value.content_hash,start_line=1,end_line=1,excerpt="must log in"),)})
    validate_citations(value,[legacy])
    with pytest.raises(ValueError,match="EXTRACTION_INVALID_CITATION"):
        validate_citations(value,[legacy],canonical=True)


def test_canonicalization_does_not_bypass_total_output_bound():
    value = source("a"*512)
    result = select(value,[(1,1)]*8).model_dump(mode="json")
    requirement = result["requirements"][0]
    result["requirements"] = [{**requirement,"key":f"R{i}"} for i in range(40)]
    model_output = RequirementsOutput.model_validate(result)
    assert len(model_output.model_dump_json().encode("utf-8")) < MAX_OUTPUT_BYTES
    with pytest.raises(ValueError,match="EXTRACTION_INVALID_OUTPUT"):
        validate_output(value,model_output)
