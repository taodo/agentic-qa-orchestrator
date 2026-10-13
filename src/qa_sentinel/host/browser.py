"""Explicit trusted local CLI composition; demo hosts never configure browser services.

Only generate configures a provider. Only Start invokes the browser. Existing
application methods own scoping, lifecycle, provenance and durable evidence.
"""
from contextlib import closing
from dataclasses import dataclass
import json
import os
from sqlalchemy import Engine
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver, ApplicationError
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.models.base import ModelSettings, ModelError
from qa_sentinel.models.config import RoleModelConfig
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.agents.browser_plan_generation import BrowserPlanGenerator
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from qa_sentinel.execution.browser_network import BrowserExecutionError
from .config import HostError
from .database import open_existing_database, SchemaNotReady

MAX_OUTPUT_BYTES = 1024 * 1024


@dataclass(frozen=True)
class LocalBrowserComposition:
    application: QASentinelApplication
    engine: Engine

    def close(self):
        self.engine.dispose()


def compose_browser(database, *, generate=False, configure_executor=False, settings=None, trusted_local_origin=None):
    """No bootstrap/migration, workspace, worker, browser launch or provider call.

    Caller is trusted local operator code, not public request configuration.
    Adapter construction reads SDK identity only, never launches a browser.
    """
    engine, factory = open_existing_database(database)
    try:
        generator = None
        executor = PlaywrightBrowserExecutor(trusted_local_origin=trusted_local_origin) if generate or configure_executor else None
        if generate:
            if not os.environ.get("OPENAI_API_KEY", "").strip():
                raise HostError("HOST_MODEL_KEY_REQUIRED")
            generator = BrowserPlanGenerator(OpenAIModelAdapter(), settings or RoleModelConfig().planner)
        application = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []),
            browser_executor=executor, browser_plan_generator=generator)
        return LocalBrowserComposition(application, engine)
    except Exception:
        engine.dispose()
        raise


def emit(value):
    # JSON escapes embedded controls; refuse overflow honestly, never truncate.
    rendered = json.dumps(value.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"))
    if len(rendered.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise HostError("HOST_BROWSER_OUTPUT_LIMIT")
    print(rendered)


def browser_command(args):
    try:
        settings = None
        if args.web_command == "generate" and args.model is not None:
            settings = ModelSettings.model_validate({**RoleModelConfig().planner.model_dump(), "model": args.model})
        with closing(compose_browser(args.database, generate=args.web_command == "generate",
            configure_executor=args.web_command in {"accept", "start"}, settings=settings,
            trusted_local_origin=getattr(args, "trusted_local_origin", None))) as composition:
            app = composition.application
            scope = (args.project_id, args.campaign_id)
            if args.web_command == "generate":
                value = app.generate_browser_plan(*scope, args.test_id)
            elif args.web_command == "candidate":
                value = app.get_browser_plan_generation(*scope, args.generation_id)
            elif args.web_command == "accept":
                value = app.accept_browser_plan_generation(*scope, args.generation_id, idempotency_key=args.idempotency_key)
            elif args.web_command == "start":
                value = app.start_browser_qa_run(*scope, args.run_id)
            else:
                value = app.get_qa_run_results(*scope, args.run_id, limit=10, after_position=args.after_position)
        emit(value)
        # QA FAIL is a completed execution, not a CLI/system error.
        return 1 if getattr(value, "status", None) == "FAILED" or getattr(value, "execution_status", None) == "FAILED" else 0
    except SchemaNotReady as error:
        print(f"Safe error: HOST_LOCAL_DATABASE_NOT_READY; current={error.current}; required={error.required}")
        return 1
    except Exception as error:
        if isinstance(error, ApplicationError):
            code = error.code.value
        elif isinstance(error, (BrowserExecutionError, ModelError)):
            code = str(error.code)
        elif isinstance(error, HostError) and str(error) in {"HOST_MODEL_KEY_REQUIRED", "HOST_LOCAL_DATABASE_NOT_READY", "HOST_BROWSER_OUTPUT_LIMIT"}:
            code = str(error)
        else:
            code = "HOST_BROWSER_OPERATION_FAILED"
        print(f"Safe error: {code}")
        return 1
