"""Run only offline synthetic provider replay. Never selects a live provider."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from qa_sentinel.evaluation.decision_safety import evaluate, readable
from qa_sentinel.evaluation.fixtures import render_report

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--corpus",default="benchmarks/decision_safety_v1.json")
    parser.add_argument("--format",choices=["json","text"],default="text")
    args=parser.parse_args()
    try:
        report=evaluate(args.corpus)
        print(render_report(report) if args.format=="json" else readable(report),end="")
    except (ValueError,TypeError,OSError,RecursionError):
        parser.exit(2,"INVALID_OFFLINE_EVALUATION_FIXTURE\n")
    raise SystemExit(0 if report["summary"]["pass"] else 1)
