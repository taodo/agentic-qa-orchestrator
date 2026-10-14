"""Same production CLI path, different disposable Targets, real Chromium, fake provider."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from qa_sentinel.application import QASentinelApplication, ProjectExecutionResolver
from qa_sentinel.projects import ProjectRuntimeRegistry
from qa_sentinel.host import browser, cli
from qa_sentinel.models.openai_adapter import OpenAIModelAdapter
from qa_sentinel.execution.playwright_browser import PlaywrightBrowserExecutor
from test_campaign_test_specifications import seed_requirement, case, csv_text


@pytest.fixture
def web_setup(migrated_factory, mock_openai, monkeypatch):
    factory, engine, config = migrated_factory
    database = Path(make_url(config.get_main_option("sqlalchemy.url")).database)
    app = QASentinelApplication(factory, ProjectExecutionResolver(ProjectRuntimeRegistry([]), []))
    mock = mock_openai([])
    from test_browser_plan_generation import Executor
    from qa_sentinel.execution.browser_policy import BrowserExecutionPolicy
    class NonExecutingFixtureExecutor(Executor):
        def __init__(self, **kwargs): super().__init__()
        def policy_for(self, target): return BrowserExecutionPolicy(allow_private_destinations=True)
        def execute(self, *args): pytest.fail("No browser on non-execution operations")
    monkeypatch.setattr(browser, "PlaywrightBrowserExecutor", NonExecutingFixtureExecutor)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-do-not-render")
    monkeypatch.setattr(browser, "OpenAIModelAdapter", lambda: OpenAIModelAdapter(client=mock.client))
    # Source/legacy pytest composition must never be required by this path.
    import qa_sentinel.host.preflight as preflight
    monkeypatch.setattr(preflight, "real_components", lambda *a: pytest.fail("No source workspace"))
    return app, factory, engine, database, mock


@pytest.fixture
def sites():
    servers = []
    def create(path, heading):
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                seen.append(self.path)
                body = ("<html><h1>" + heading + "</h1></html>").encode()
                self.send_response(200 if self.path == path else 404)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))
        return f"http://127.0.0.1:{server.server_port}", seen, server
    yield create
    for server, thread in servers:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def seed(setup, *, key, url, path, expected, locator):
    app, factory, _, database, mock = setup
    project = app.create_project(key=key, name="Configured " + key)
    campaign = app.create_campaign(project.id, name="Controlled WEB")
    requirement = seed_requirement(factory, project, campaign)
    app.review_campaign_requirement(project.id, campaign.id, requirement.id, reviewer_label="operator")
    facts = dict(contract_version="browser-facts-v1", required_actions=[["NAVIGATE"]],
        locators=[locator], paths=[path], input_values=[])
    imported = case(refs=[str(requirement.id)])
    imported.update(preconditions=[json.dumps(facts)], steps=[dict(index=1, action="Navigate and verify heading", expected=expected)],
        overall_expected_result=expected)
    app.import_campaign_tests(project.id, campaign.id, name="Operator supplied", format="CSV", content=csv_text([imported]))
    spec = app.list_campaign_test_specifications(project.id, campaign.id).items[0]
    app.review_campaign_test_specification(project.id, campaign.id, spec.id, reviewer_label="operator")
    target = app.create_target(project.id, name="Configured target", environment="LOCAL", configuration={"base_url": url})
    app.associate_campaign_target(project.id, campaign.id, target_id=target.id)
    output = dict(disposition="CANDIDATE", plan=dict(steps=[dict(action="NAVIGATE", path=path),
        dict(action="ASSERT_TEXT", locator=locator, text=expected, timeout_ms=300)], redirect_limit=0),
        step_bindings=[1, 1], unable_reason=None)
    mock.queue.append(output)
    return project, campaign, spec, target


def invoke(setup, scope, operation, capsys, **options):
    _, _, _, database, _ = setup
    p, c, *_ = scope
    args = ["local", "web", operation, "--database", str(database), "--project-id", str(p.id), "--campaign-id", str(c.id)]
    for key, value in options.items():
        args += ["--" + key.replace("_", "-"), str(value)]
    status = cli.main(args)
    output = capsys.readouterr().out
    assert "synthetic-do-not-render" not in output
    return status, json.loads(output) if output.startswith("{") else output


def available_chromium():
    pytest.importorskip("playwright.async_api")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        if not Path(runtime.chromium.executable_path).is_file():
            pytest.skip("Chromium unavailable; explicit installation required")


@pytest.mark.parametrize("key,path,expected,actual,locator,outcome", [
    ("catalog", "/catalog", "Catalog ready", "Catalog ready", {"strategy":"ROLE","role":"heading","name":"Catalog ready","exact":True}, "PASS"),
    ("inventory", "/inventory", "Inventory available", "Inventory available", {"strategy":"CSS","value":"h1"}, "PASS"),
    ("mismatch", "/status", "Expected status", "Different status", {"strategy":"CSS","value":"h1"}, "FAIL"),
])
def test_generic_cli_generate_accept_start_results(web_setup, sites, capsys, monkeypatch, key, path, expected, actual, locator, outcome):
    available_chromium()
    monkeypatch.setattr(browser, "PlaywrightBrowserExecutor", PlaywrightBrowserExecutor)
    url, seen, _ = sites(path, actual)
    scope = seed(web_setup, key=key, url=url, path=path, expected=expected, locator=locator)
    app, _, engine, _, mock = web_setup
    executed = []
    original = PlaywrightBrowserExecutor.execute
    def execute(self, envelope, run, test):
        executed.append(envelope)
        assert run.execution_status == "RUNNING" and test.execution_status == "RUNNING"
        assert len(mock.calls) == 1
        return original(self, envelope, run, test)
    monkeypatch.setattr(PlaywrightBrowserExecutor, "execute", execute)
    import socket
    with monkeypatch.context() as guard:
        guard.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("No Target DNS before Start"))
        status, candidate = invoke(web_setup, scope, "generate", capsys, test_id=scope[2].id, trusted_local_origin=url)
        assert status == 0 and candidate["status"] == "SUCCEEDED" and not seen and not executed
        assert candidate["settings"]["model"] == mock.calls[0]["model"]
        assert mock.calls[0]["tools"] == [] and mock.calls[0]["tool_choice"] == "none"
        status, loaded = invoke(web_setup, scope, "candidate", capsys, generation_id=candidate["id"])
        assert status == 0 and loaded == candidate
        status, run = invoke(web_setup, scope, "accept", capsys, generation_id=candidate["id"], idempotency_key="explicit-accept", trusted_local_origin=url)
        assert status == 0 and run["execution_status"] == "CREATED" and not seen and not executed and len(mock.calls) == 1
    # Change live Target AFTER sealing: Start must use the captured URL unchanged.
    app.update_target(scope[0].id, scope[3].id, configuration={"base_url":"https://example.invalid"})
    def forbidden_provider(): pytest.fail("Only explicit Generate may configure the provider")
    monkeypatch.setattr(browser, "OpenAIModelAdapter", forbidden_provider)
    monkeypatch.delenv("OPENAI_API_KEY")
    status, final = invoke(web_setup, scope, "start", capsys, run_id=run["id"], trusted_local_origin=url)
    assert status == 0 and (final["execution_status"], final["qa_outcome"]) == ("COMPLETED", outcome)
    assert final["target_snapshot"]["base_url"] == url and final["executor_kind"] == "WEB_BROWSER"
    assert final["runtime_identity"]["engine"] == "CHROMIUM" and path in seen
    assert len(executed) == 1 and executed[0].origin == "AI" and executed[0].plan_hash == candidate["plan_hash"]
    assert executed[0].plan.model_dump(mode="json") == candidate["output"]["plan"]
    engine.dispose()  # Reopen: Results is authoritative persisted evidence, not a local return value.
    previous_hits = list(seen)
    status, results = invoke(web_setup, scope, "results", capsys, run_id=run["id"])
    assert status == 0 and seen == previous_hits and len(mock.calls) == 1
    result = results["tests"]["items"][0]
    assert result["qa_result"] == outcome and result["evidence_count"] == 2
    for evidence in result["evidence"]["items"]:
        assert evidence["executor_kind"] == "WEB_BROWSER"
        assert evidence["payload"]["plan_hash"] == candidate["plan_hash"]
        assert evidence["payload"]["run_test_id"] == result["id"]
        assert evidence["payload"]["browser_version"] == final["runtime_identity"]["browser_version"]
    assert result["evidence"]["items"][-1]["payload"]["matched"] is (outcome == "PASS")
    with engine.connect() as db:
        assert db.scalar(text("SELECT count(*) FROM tasks")) == db.scalar(text("SELECT count(*) FROM execution_jobs")) == 0


def test_real_system_failure_does_not_fallback(web_setup, sites, capsys, monkeypatch):
    available_chromium()
    monkeypatch.setattr(browser, "PlaywrightBrowserExecutor", PlaywrightBrowserExecutor)
    url, seen, server = sites("/status", "Status")
    scope = seed(web_setup, key="offline", url=url, path="/status", expected="Status", locator={"strategy":"CSS","value":"h1"})
    _, candidate = invoke(web_setup, scope, "generate", capsys, test_id=scope[2].id, trusted_local_origin=url)
    _, run = invoke(web_setup, scope, "accept", capsys, generation_id=candidate["id"], idempotency_key="accept", trusted_local_origin=url)
    assert seen == []
    server.shutdown(); server.server_close()
    monkeypatch.setattr(browser, "OpenAIModelAdapter", lambda: pytest.fail("No model at Start"))
    status, final = invoke(web_setup, scope, "start", capsys, run_id=run["id"], trusted_local_origin=url)
    assert status == 1 and (final["execution_status"], final["qa_outcome"]) == ("FAILED", "NOT_EVALUATED")
    assert final["browser_error_code"] == "BROWSER_TARGET_UNREACHABLE"
    _, results = invoke(web_setup, scope, "results", capsys, run_id=run["id"])
    assert results["tests"]["items"][0]["evidence_count"] == 0 and results["summary"]["completed"] == 0
    assert len(web_setup[4].calls) == 1


@pytest.mark.parametrize("change", ["target", "test", "approval", "plan"])
def test_cli_stale_or_tampered_provenance_refuses_acceptance(web_setup, sites, capsys, change):
    url, seen, _ = sites("/", "Heading")
    scope = seed(web_setup, key="stale", url=url, path="/", expected="Heading", locator={"strategy":"CSS","value":"h1"})
    app, _, engine, _, mock = web_setup
    _, candidate = invoke(web_setup, scope, "generate", capsys, test_id=scope[2].id, trusted_local_origin=url)
    if change == "target": app.update_target(scope[0].id, scope[3].id, name="Changed identity")
    else:
        # Corruption/stale-write simulation only in the disposable DB, never operator data.
        with engine.begin() as db:
            if change == "test": db.execute(text("UPDATE campaign_test_specifications SET title='Changed'"))
            elif change == "approval": db.execute(text("UPDATE campaign_test_reviews SET content_hash=:hash"), {"hash":"0"*64})
            else:
                db.execute(text("DROP TRIGGER browser_generation_seal"))
                db.execute(text("UPDATE browser_plan_generations SET payload=json_set(payload, '$.plan_hash', :hash)"), {"hash":"0"*64})
    status, error = invoke(web_setup, scope, "accept", capsys, generation_id=candidate["id"], idempotency_key="stale", trusted_local_origin=url)
    assert status == 1 and error.startswith("Safe error:") and seen == [] and len(mock.calls) == 1
    with engine.connect() as db: assert db.scalar(text("SELECT count(*) FROM qa_runs")) == 0


def test_failed_generation_is_not_an_executable_run(web_setup, sites, capsys):
    url, seen, _ = sites("/", "Heading")
    scope = seed(web_setup, key="cannot", url=url, path="/", expected="Heading", locator={"strategy":"CSS","value":"h1"})
    mock = web_setup[4]
    mock.queue.clear(); mock.queue.append({"disposition":"CANNOT_PLAN","plan":None,"step_bindings":[],"unable_reason":"MISSING_LOCATOR"})
    status, candidate = invoke(web_setup, scope, "generate", capsys, test_id=scope[2].id, trusted_local_origin=url)
    assert status == 1 and candidate["error_code"] == "BROWSER_PLAN_INSUFFICIENT_INFORMATION"
    status, _ = invoke(web_setup, scope, "accept", capsys, generation_id=candidate["id"], idempotency_key="bad", trusted_local_origin=url)
    assert status == 1 and seen == [] and len(mock.calls) == 1
    with web_setup[2].connect() as db:
        assert db.scalar(text("SELECT count(*) FROM qa_runs")) == db.scalar(text("SELECT count(*) FROM qa_run_evidence")) == 0


def test_cli_errors_are_bounded_and_safe(web_setup, capsys, monkeypatch, tmp_path):
    with pytest.raises(SystemExit) as error:
        cli.main(["local", "web", "start", "--run-id", "synthetic-secret"])
    assert error.value.code == 2
    assert "synthetic-secret" not in capsys.readouterr().err
    def failure(*args, **kwargs): raise RuntimeError("raw SQL / path / synthetic-secret")
    monkeypatch.setattr(browser, "compose_browser", failure)
    args = ["local", "web", "results", "--database", str(tmp_path/"missing"), "--project-id", str(uuid4()), "--campaign-id", str(uuid4()), "--run-id", str(uuid4())]
    assert cli.main(args) == 1 and capsys.readouterr().out == "Safe error: HOST_BROWSER_OPERATION_FAILED\n"
    class Oversized:
        def model_dump(self, **kwargs): return {"text":"x"*browser.MAX_OUTPUT_BYTES}
    with pytest.raises(browser.HostError, match="HOST_BROWSER_OUTPUT_LIMIT"): browser.emit(Oversized())


def test_browser_composition_missing_key_and_stale_schema_do_not_migrate(web_setup, monkeypatch):
    _, _, engine, database, _ = web_setup
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.setattr(browser, "OpenAIModelAdapter", lambda: pytest.fail("No provider without credentials"))
    from alembic import command
    monkeypatch.setattr(command, "upgrade", lambda *a: pytest.fail("No auto migration"))
    with pytest.raises(browser.HostError, match="HOST_MODEL_KEY_REQUIRED"): browser.compose_browser(database, generate=True)
    with engine.begin() as db: db.execute(text("UPDATE alembic_version SET version_num='0014'"))
    with pytest.raises(browser.SchemaNotReady) as error: browser.compose_browser(database)
    assert (error.value.current, error.value.required) == ("0014", "0018")


def test_production_composition_has_no_fixture_specific_strings():
    source = Path(browser.__file__).read_text() + Path(cli.__file__).read_text()
    for forbidden in ("data-qa-lab", "Data QA Lab", "/catalog", "/inventory", "Catalog ready", "Inventory available"):
        assert forbidden not in source


@pytest.mark.parametrize("operation", ["generate", "candidate", "accept", "start", "results"])
def test_cli_operations_remain_project_campaign_scoped(web_setup, capsys, operation):
    app = web_setup[0]
    owner = app.create_project(key="owner", name="Owner")
    foreign = app.create_project(key="foreign", name="Foreign")
    campaign = app.create_campaign(owner.id, name="Owned")
    options = {"generate":{"test_id":uuid4()}, "candidate":{"generation_id":uuid4()},
        "accept":{"generation_id":uuid4(),"idempotency_key":"intent"}, "start":{"run_id":uuid4()}, "results":{"run_id":uuid4()}}
    status, output = invoke(web_setup, (foreign, campaign), operation, capsys, **options[operation])
    assert status == 1 and output.startswith("Safe error:") and len(web_setup[4].calls) == 0


def test_explicit_model_and_unknown_usage_are_exposed_without_inference(web_setup, sites, capsys):
    url, _, _ = sites("/", "Heading")
    scope = seed(web_setup, key="model", url=url, path="/", expected="Heading", locator={"strategy":"CSS","value":"h1"})
    status, result = invoke(web_setup, scope, "generate", capsys, test_id=scope[2].id, model="operator-model", trusted_local_origin=url)
    assert status == 0 and result["settings"]["model"] == "operator-model" and result["metadata"]["model"] == "operator-model"
    assert result["metadata"]["reasoning_tokens"] is None and result["metadata"]["total_tokens"] == 30


def test_read_composition_never_constructs_model_or_browser(web_setup, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY")
    def forbidden(*args, **kwargs): pytest.fail("No runtime construction for stored reads")
    monkeypatch.setattr(browser, "OpenAIModelAdapter", forbidden)
    monkeypatch.setattr(browser, "PlaywrightBrowserExecutor", forbidden)
    composition = browser.compose_browser(web_setup[3])
    try:
        assert composition.application._browser_executor is None and composition.application._browser_plan_generator is None
    finally: composition.close()



def test_browser_command_does_not_create_missing_database(tmp_path, capsys):
    missing = tmp_path / "absent.sqlite3"
    result = cli.main(["local", "web", "results", "--database", str(missing),
        "--project-id", str(uuid4()), "--campaign-id", str(uuid4()), "--run-id", str(uuid4())])
    assert result == 1 and not missing.exists()
    assert capsys.readouterr().out == "Safe error: HOST_LOCAL_DATABASE_NOT_READY\n"



def test_cleanup_failure_is_safe_and_does_not_emit_success(monkeypatch, capsys, tmp_path):
    from types import SimpleNamespace
    def close(): raise RuntimeError("internal path / synthetic-secret")
    composition = SimpleNamespace(application=SimpleNamespace(get_qa_run_results=lambda *a, **k: None), close=close)
    monkeypatch.setattr(browser, "compose_browser", lambda *a, **k: composition)
    result = cli.main(["local", "web", "results", "--database", str(tmp_path/"state.sqlite3"),
        "--project-id", str(uuid4()), "--campaign-id", str(uuid4()), "--run-id", str(uuid4())])
    assert result == 1 and capsys.readouterr().out == "Safe error: HOST_BROWSER_OPERATION_FAILED\n"
