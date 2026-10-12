"""Closed executor identities; naming a capability never enables a runtime."""
from enum import StrEnum


class ExecutorKind(StrEnum):
    SYNTHETIC = "SYNTHETIC"
    WEB_BROWSER = "WEB_BROWSER"
