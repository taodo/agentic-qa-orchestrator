"""WEB URL admission is purely structural; Target != Workspace != Executor."""
import pytest
from pydantic import ValidationError
from uuid import uuid4
from qa_sentinel.domain.target import CreateTarget, TargetUnderTest, TargetSnapshot, UpdateTarget


@pytest.mark.parametrize("url",["https://shopee.vn","http://127.0.0.1:8010/app","http://localhost:3000", "https://example.com/path%20space/", "http://[::1]:80/path"])
def test_valid_web(url):
    target=TargetUnderTest(project_id=uuid4(),name="Target",environment="STAGING",configuration={"base_url":url})
    assert target.type=="WEB" and target.configuration.base_url==url
    assert TargetSnapshot.capture(target).base_url==url
    assert not any(field in target.model_dump() for field in ("workspace_root","executor","pytest_targets"))


@pytest.mark.parametrize("url",["file:///tmp/file","ftp://example.com","javascript:alert(1)","data:text/plain,a","https://user:password@example.com","https://user%40host@example.com","https://example.com?token=secret","https://example.com#fragment","https://example.com?","https://example.com#","https://","example.com","https://bad host","https://example.com:65536","https://example.com:0","https://example.com:","https://example.com/\\path","https://example.com/%ZZ", "https://example.com/\nsecret","https://-bad.example", "https://example..com", "https://[broken]/", "https://example.com/"+"x"*2048])
def test_invalid_url(url):
    with pytest.raises(ValidationError):CreateTarget(name="Target",environment="LOCAL",configuration={"base_url":url})


def test_bounded_closed_type_environment_and_canonical_policy():
    target=TargetUnderTest(project_id=uuid4(),name="  Site  ",environment="PRODUCTION",configuration={"base_url":"HTTPS://Example.COM:443/CaseSensitive%2Fpath"})
    assert target.configuration.base_url=="https://example.com:443/CaseSensitive%2Fpath"
    changed=target.update(UpdateTarget(environment="STAGING"))
    assert changed.id==target.id and changed.project_id==target.project_id and changed.created_at==target.created_at
    assert changed.configuration==target.configuration and changed.updated_at>=target.updated_at
    for changes in [{"type":"API"},{"environment":"SECRET_ENV"},{"configuration":{"base_url":"https://example.com","token":"secret"}}]:
        with pytest.raises(ValidationError):CreateTarget.model_validate({"name":"Site","environment":"STAGING","configuration":{"base_url":"https://example.com"},**changes})
    with pytest.raises(ValidationError):UpdateTarget(name=None)
