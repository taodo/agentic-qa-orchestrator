"""External system identity. A Target is neither a workspace nor an executor."""
from datetime import datetime, timezone
from ipaddress import ip_address
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4
from pydantic import Field, BeforeValidator, AwareDatetime, model_validator
from .campaign_content import Frozen
from .campaign import CampaignName


def web_base_url(value):
    # No network, DNS, filesystem or provider work; no exception contains input.
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ValueError("Invalid WEB base URL")
    if not value.isascii() or re.search(r"[\s\x00-\x1f\x7f\\]", value):
        raise ValueError("Invalid WEB base URL")
    try:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc or "@" in parts.netloc or "%" in parts.netloc:
            raise ValueError()
        # Base URLs deliberately exclude query/fragment, including empty delimiters.
        if "?" in value or "#" in value:
            raise ValueError()
        host = parts.hostname
        if not host or parts.port == 0:
            raise ValueError()
        if parts.netloc.startswith("["):
            ip_address(host)
            if "]" not in parts.netloc:
                raise ValueError()
            suffix = parts.netloc.split("]",1)[1]
        else:
            if len(host) > 253 or any(not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in host.rstrip(".").split(".")):
                raise ValueError()
            suffix = parts.netloc[len(host):]
        if suffix and (not re.fullmatch(r":[0-9]{1,5}", suffix) or not 1 <= parts.port <= 65535):
            raise ValueError()
        if re.search(r"%(?![0-9a-fA-F]{2})", parts.path):
            raise ValueError()
        # Only scheme/hostname case normalization. Explicit port/path are retained.
        authority = ("["+host.lower()+"]" if parts.netloc.startswith("[") else host.lower()) + suffix
        return urlunsplit((parts.scheme, authority, parts.path, "", ""))
    except (ValueError, TypeError):
        raise ValueError("Invalid WEB base URL") from None


BaseURL = Annotated[str, BeforeValidator(web_base_url)]
Environment = Literal["LOCAL", "DEVELOPMENT", "STAGING", "PRODUCTION", "OTHER"]


class WebConfiguration(Frozen):
    base_url: BaseURL


class CreateTarget(Frozen):
    name: CampaignName
    type: Literal["WEB"] = "WEB"
    environment: Environment
    configuration: WebConfiguration


class UpdateTarget(Frozen):
    name: CampaignName | None = None
    type: Literal["WEB"] | None = None
    environment: Environment | None = None
    configuration: WebConfiguration | None = None

    @model_validator(mode="after")
    def supplied_values(self):
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Target updates cannot be null")
        return self


class TargetUnderTest(CreateTarget):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    created_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def update(self, command):
        return TargetUnderTest.model_validate({**self.model_dump(), **command.model_dump(exclude_unset=True),
            "updated_at": datetime.now(timezone.utc)})


class TargetSnapshot(Frozen):
    schema_version: Literal["web-target-snapshot-v1"] = "web-target-snapshot-v1"
    target_id: UUID
    project_id: UUID
    type: Literal["WEB"]
    name: CampaignName
    environment: Environment
    base_url: BaseURL

    @classmethod
    def capture(cls, target):
        return cls(target_id=target.id, project_id=target.project_id, type=target.type,
                   name=target.name, environment=target.environment, base_url=target.configuration.base_url)
