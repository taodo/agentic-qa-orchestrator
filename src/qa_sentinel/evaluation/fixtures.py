"""Bounded inert fixture IO shared by offline research runners."""
import json
from pathlib import Path


def load_fixture(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError("FIXTURE_LIMIT")
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("DUPLICATE_FIXTURE_KEY")
            obj[key] = value
        return obj
    data = json.loads(raw, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_FIXTURE")))
    return data, raw


def render_report(report):
    result = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True)
    if len(result.encode("utf-8")) > 65536:
        raise ValueError("REPORT_LIMIT")
    return result + "\n"
