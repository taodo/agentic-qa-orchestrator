"""HTTP hosts never compose or expose the local-real proving CLI capability."""
from uuid import UUID
import pytest
from fastapi.testclient import TestClient
from qa_sentinel.host import targets, composition
from qa_sentinel.host.config import HostConfig
from qa_sentinel.host.web import create_host_app
from qa_sentinel.agents.fake import FakeAgentRuntime
from qa_sentinel.execution.fake import FakeTestResultProvider
from test_host import offline, config
from test_preview import preview, header
from test_hosted import hosted, login, csrf, USER, PASSWORD, SECRET


@pytest.mark.parametrize("mode", ["demo", "preview-demo", "hosted-demo"])
def test_synthetic_hosts_never_construct_target_or_offer_http_trigger(config, monkeypatch, tmp_path, mode):
    for key, value in (("QA_SENTINEL_OPERATOR_USERNAME", USER), ("QA_SENTINEL_OPERATOR_PASSWORD", PASSWORD),
        ("QA_SENTINEL_SESSION_SECRET", SECRET), ("QA_SENTINEL_PREVIEW_USERNAME", "synthetic-preview-user"),
        ("QA_SENTINEL_PREVIEW_PASSWORD", "synthetic-preview-password-π"),
        ("QA_SENTINEL_TARGET_WORKSPACE", str(tmp_path / "untrusted-input"))): monkeypatch.setenv(key, value)
    monkeypatch.setattr("qa_sentinel.host.hosted.tempfile.gettempdir", lambda: str(tmp_path))
    def forbidden(*args, **kwargs): pytest.fail("Synthetic HTTP host reached real target composition")
    for name in ("TargetProfile", "prepare_target", "prove_target", "check_target"):
        monkeypatch.setattr(targets, name, forbidden)
    monkeypatch.setattr(composition, "real_components", forbidden)
    value = preview(config) if mode == "preview-demo" else hosted(config) if mode == "hosted-demo" else config
    app = create_host_app(value)
    with TestClient(app, base_url="https://testserver") as client:
        headers = header() if mode == "preview-demo" else {}
        if mode == "hosted-demo":
            assert login(client).status_code == 303
            headers = csrf(client)
        projects = client.get("/api/v1/projects", headers=headers).json()["items"]
        bundle = app.state.host_composition.resolver.resolve(UUID(projects[0]["id"]))
        assert isinstance(bundle.runtime, FakeAgentRuntime)
        assert isinstance(bundle.test_provider, FakeTestResultProvider)
        for path in ("/host/target-test", "/host/target-check", "/api/v1/target-test"):
            assert client.post(path, headers=headers, json={"workspace_root": str(tmp_path), "mode": "local"}).status_code == 404
        schema = client.get("/openapi.json", headers=headers).json()
        assert not any("target-test" in path or "target-check" in path for path in schema["paths"])
