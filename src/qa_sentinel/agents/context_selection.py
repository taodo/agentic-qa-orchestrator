"""Lossless request-local evidence reuse; no external cache or artifact lookup."""
import json
from qa_sentinel.models.base import ContextSelection


def serialize(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def select_context(data):
    original = serialize(data)
    selected = dict(data)
    records = data.get("repository_results", ())
    references = [record["evidence_ref"] for record in records]
    unique_references = len(set(references)) == len(references)
    reused, seen, projected = 0, {}, []
    for record in records:
        item = dict(record)
        result = dict(record["result"])
        value = result.get("data")
        # Exact typed result data, not SHA alone: differing source/hash/metadata survives.
        if result["status"] == "SUCCESS" and value is not None and unique_references:
            identity = serialize(value)
            reference = seen.get(identity)
            if reference is None:
                seen[identity] = record["evidence_ref"]
            elif len(serialize({"data_ref": reference})) < len(serialize({"data": value})):
                result.pop("data")
                result["data_ref"] = reference
                reused += 1
        item["result"] = result
        projected.append(item)
    if records:
        selected["repository_results"] = projected
    serialized = serialize(selected)
    return serialized, ContextSelection(original_chars=len(original), selected_chars=len(serialized),
        selected_bytes=len(serialized.encode("utf-8")), reused_results=reused)
