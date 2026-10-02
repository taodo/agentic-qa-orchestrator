"""Temporary preview Basic gate; no product auth, persistence or credential logs."""
import base64
import binascii
from dataclasses import dataclass, field
import hmac
import os
import secrets
from starlette.responses import JSONResponse
from .config import HostError


@dataclass(frozen=True, repr=False)
class PreviewCredentials:
    # Only process-random keyed digests survive preflight; never plaintext config/state.
    salt: bytes = field(repr=False)
    username_digest: bytes = field(repr=False)
    password_digest: bytes = field(repr=False)

    def matches(self, username: bytes, password: bytes) -> bool:
        user_ok = hmac.compare_digest(hmac.digest(self.salt, username, "sha256"), self.username_digest)
        password_ok = hmac.compare_digest(hmac.digest(self.salt, password, "sha256"), self.password_digest)
        return user_ok & password_ok


def preview_credentials() -> PreviewCredentials:
    # Reject even an empty inherited key: no provider credential belongs in preview.
    if "OPENAI_API_KEY" in os.environ:
        raise HostError("HOST_PREVIEW_MODEL_KEY_FORBIDDEN")
    username = os.environ.get("QA_SENTINEL_PREVIEW_USERNAME", "")
    password = os.environ.get("QA_SENTINEL_PREVIEW_PASSWORD", "")
    if not username.strip() or not password.strip() or ":" in username or any(
        ord(c) < 32 or ord(c) == 127 for c in username + password):
        raise HostError("HOST_PREVIEW_CREDENTIALS_REQUIRED")
    try:
        user, secret = username.encode("utf-8"), password.encode("utf-8")
        if len(user) + len(secret) > 2048:
            raise ValueError("Oversized credentials")
        salt = secrets.token_bytes(32)
        return PreviewCredentials(salt, hmac.digest(salt, user, "sha256"), hmac.digest(salt, secret, "sha256"))
    except (ValueError, UnicodeError):
        raise HostError("HOST_PREVIEW_CREDENTIALS_REQUIRED") from None


class PreviewAccess:
    def __init__(self, app, credentials: PreviewCredentials):
        self.app = app
        self.credentials = credentials

    def authorized(self, scope) -> bool:
        values = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
        if len(values) != 1 or len(values[0]) > 8192:
            return False
        try:
            scheme, token = values[0].split(b" ", 1)
            if scheme.lower() != b"basic":
                return False
            username, password = base64.b64decode(token, validate=True).split(b":", 1)
            return self.credentials.matches(username, password)
        except (ValueError, binascii.Error):
            return False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        async def safe_send(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []),
                    (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"), (b"cache-control", b"no-store")]}
            await send(message)
        health = scope["method"] == "GET" and scope["path"] == "/health" and scope.get("raw_path", b"/health") == b"/health"
        if not health and not self.authorized(scope):
            response = JSONResponse({"error": {"code": "PREVIEW_AUTH_REQUIRED", "message": "Preview access required"}},
                status_code=401, headers={"WWW-Authenticate": 'Basic realm="QA Sentinel Preview", charset="UTF-8"'})
            return await response(scope, receive, safe_send)
        await self.app(scope, receive, safe_send)
