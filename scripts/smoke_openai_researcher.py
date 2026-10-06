"""Explicit, optional network smoke: python scripts/smoke_openai_researcher.py --run."""
import argparse
import os
from uuid import uuid4
from qa_sentinel.agents.base import ResearchContext
from qa_sentinel.agents.real import RealAgentRuntime
from qa_sentinel.domain.enums import AgentName
from qa_sentinel.models.base import ModelError, ModelSettings
from qa_sentinel.models.config import RoleModelConfig
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter


def main():
    parser = argparse.ArgumentParser(description="Optional paid OpenAI Researcher smoke; no persistence.")
    parser.add_argument("--run", action="store_true", help="Explicitly authorize one real API call")
    parser.add_argument("--model", default="gpt-5.6-luna")
    args = parser.parse_args()
    if not args.run:
        parser.error("Pass --run to explicitly make a real API call")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        print("Missing local OPENAI_API_KEY; no request made.")
        return 2
    runtime = RealAgentRuntime(OpenAIModelAdapter(), RoleModelConfig(researcher=ModelSettings(
        model=args.model, reasoning_effort="low", max_output_tokens=2048, timeout_seconds=60)))
    try:
        response = runtime.run(AgentName.RESEARCHER, ResearchContext(task_id=uuid4(), attempt=1,
            requirement="Research requirements for a Python divide function that rejects a zero divisor."))
    except ModelError as failure:
        print("Smoke failed:", failure.code)
        return 1
    print("Structured ResearchOutput accepted; research_complete:", response.parsed_output.research_complete)
    print("Usage tokens:", response.metadata.total_tokens)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
