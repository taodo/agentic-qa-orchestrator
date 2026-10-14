"""Offline synthetic experience evaluation, without Hermes or provider access."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from qa_sentinel.evaluation.experience_poc import evaluate
from qa_sentinel.evaluation.fixtures import render_report

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--corpus",default="benchmarks/experience_poc_v1.json")
    parser.add_argument("--format",choices=["json","text"],default="text")
    args=parser.parse_args()
    try:
        report=evaluate(args.corpus)
        if args.format=="json": print(render_report(report),end="")
        else:
            s=report["summary"]
            print(f"Hermes-inspired fixture PoC: {'PASS' if s['pass'] else 'FAIL'}")
            print(f"Scenarios: {s['scenarios']}; matches: {s['oracle_matches']}; hints: {s['used_hints']}; rejected: {s['rejected']}")
            print("Actual Hermes integration: NOT RUN. No execution, promotion or production persistence.")
    except (ValueError,TypeError,OSError,RecursionError): parser.exit(2,"INVALID_OFFLINE_EXPERIENCE_FIXTURE\n")
    raise SystemExit(0 if report["summary"]["pass"] else 1)
