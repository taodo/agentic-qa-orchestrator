from copy import deepcopy
from uuid import UUID
import pytest
from pydantic import ValidationError
from qa_sentinel.persistence import mappers


@pytest.mark.parametrize("name", ["task","invocation","artifact","transition","gate_evaluation",
                                  "decision","error","event","audit","test_run","requirement",
                                  "acceptance_criterion","failure_fingerprint"])
def test_explicit_mapper_roundtrip(bundle,name):
    original = bundle[name]
    row = getattr(mappers,name+"_to_orm")(original)
    restored = getattr(mappers,name+"_from_orm")(row)
    assert restored == original
    for field,value in original.model_dump().items():
        if isinstance(value,UUID): assert isinstance(getattr(restored,field),UUID)


def test_json_mapping_detaches_both_directions(bundle):
    original=bundle["artifact"]
    snapshot=deepcopy(original.content)
    row=mappers.artifact_to_orm(original)
    original.content["nested"]["list"].append("input mutation")
    assert row.content==snapshot
    restored=mappers.artifact_from_orm(row)
    restored.content["nested"]["list"].append("output mutation")
    assert row.content==snapshot


def test_task_mapper_revalidates_mutable_snapshot(bundle):
    bundle["task"].defect_cycle=-1
    with pytest.raises(ValidationError): mappers.task_to_orm(bundle["task"])


def test_noncanonical_stored_enum_rejected(bundle):
    row=mappers.task_to_orm(bundle["task"]);row.state="made-up"
    with pytest.raises(ValidationError): mappers.task_from_orm(row)
