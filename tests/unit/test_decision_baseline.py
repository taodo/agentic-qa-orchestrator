from pathlib import Path
import importlib.util
import json

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("benchmark_decisions", ROOT / "scripts/benchmark_decisions.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_fixed_baseline_is_reproducible():
    one = benchmark.measure(ROOT / "benchmarks/decision_routing_v1.json")
    two = benchmark.measure(ROOT / "benchmarks/decision_routing_v1.json")
    for key in one:
        if not key.startswith("latency"):
            assert one[key] == two[key]
    assert one["samples"] == 20
    assert one["route_correct"] == 20
    assert one["missed_escalation"] == 6
    assert one["provider_requests"] == 0
    assert one["provider_cost_usd"] is None


def test_official_fixture_contract_feasibility():
    schema = json.loads((ROOT / "benchmarks/typesafe_openapi_0_2_0.json").read_text())
    assert schema["info"]["version"] == "0.2.0"
    definitions = schema["components"]["schemas"]
    assert set(definitions["SystemOneRequest"]["required"]) == {"state", "model", "questions"}
    assert set(definitions["ChoiceAnswer"]["required"]) == {"type", "choice", "confidence", "probabilities"}
    assert set(definitions["SystemOneResponse"]["required"]) == {"model", "answers", "usage"}
    assert definitions["ModelMetadata"]["properties"]["name"]["examples"] == ["jev-latest"]


def test_offline_poc_is_not_live_provider_improvement():
    result=benchmark.measure(ROOT / "benchmarks/decision_routing_v1.json", "offline-poc")
    assert result["route_correct"]==20 and result["missed_escalation"]==6
    assert result["fallback"]==8 and result["provider_requests"]==14
    assert result["external_requests"]==0
    assert result["live_provider"]=="LIVE NOT VERIFIED"
