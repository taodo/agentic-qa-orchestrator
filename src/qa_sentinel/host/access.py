"""Stateless single-operator hosted access. No workflow or persisted auth state."""
import base64
import binascii
from dataclasses import dataclass, field
import hmac
import json
import os
import re
import secrets
import threading
import time
import unicodedata
from urllib.parse import parse_qs, urlsplit
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from .config import HostError
from .preview import PreviewCredentials

COOKIE = "__Host-qa-sentinel-session"
LOGIN_COOKIE = "__Host-qa-sentinel-login"
CSRF_HEADER = "x-qa-sentinel-csrf"
SESSION_SECONDS = 8 * 60 * 60
NONCE = re.compile(r"[a-f0-9]{64}\Z")


def has_controls(value):
    return any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in value)


@dataclass(frozen=True, repr=False)
class HostedCredentials:
    verifier: PreviewCredentials = field(repr=False)
    signing_key: bytes = field(repr=False)


def hosted_credentials():
    if "OPENAI_API_KEY" in os.environ:
        raise HostError("HOST_HOSTED_MODEL_KEY_FORBIDDEN")
    user = os.environ.get("QA_SENTINEL_OPERATOR_USERNAME", "")
    password = os.environ.get("QA_SENTINEL_OPERATOR_PASSWORD", "")
    secret = os.environ.get("QA_SENTINEL_SESSION_SECRET", "")
    try:
        if any(not v.strip() or len(v.encode("utf-8")) > 1024 or has_controls(v) for v in (user, password)):
            raise ValueError("Credentials required")
        if any(c in user for c in ":;=,\\\"'"):
            raise ValueError("Ambiguous username")
        if not secret.strip() or not 32 <= len(secret.encode("utf-8")) <= 1024 or has_controls(secret):
            raise HostError("HOST_SESSION_SECRET_REQUIRED")
        if secret in {user, password}:
            raise HostError("HOST_SESSION_SECRET_REQUIRED")
        salt = secrets.token_bytes(32)
        verifier = PreviewCredentials(salt, hmac.digest(salt, user.encode("utf-8"), "sha256"),
            hmac.digest(salt, password.encode("utf-8"), "sha256"))
        return HostedCredentials(verifier, secret.encode("utf-8"))
    except (ValueError, UnicodeError):
        raise HostError("HOST_OPERATOR_CREDENTIALS_REQUIRED") from None


class SessionSigner:
    def __init__(self, key):
        self.key = key

    def issue(self, purpose="session", *, now=None):
        issued = int(time.time() if now is None else now)
        payload = dict(v=1, p=purpose, i=issued, e=issued + (SESSION_SECONDS if purpose == "session" else 600),
            n=secrets.token_hex(32), c=secrets.token_hex(32))
        encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
        mac = hmac.digest(self.key, encoded, "sha256").hex().encode()
        return (encoded + b"." + mac).decode(), payload["c"]

    def verify(self, token, purpose="session"):
        try:
            if not isinstance(token, str) or len(token) > 1024:
                return None
            encoded, mac = token.encode("ascii").split(b".")
            if not hmac.compare_digest(hmac.digest(self.key, encoded, "sha256").hex().encode(), mac):
                return None
            data = json.loads(base64.b64decode(encoded + b"=" * (-len(encoded) % 4), altchars=b"-_", validate=True))
            now = int(time.time())
            lifetime = SESSION_SECONDS if purpose == "session" else 600
            if not isinstance(data, dict) or set(data) != {"v", "p", "i", "e", "n", "c"}:
                return None
            if type(data["v"]) is not int or data["v"] != 1 or data["p"] != purpose:
                return None
            if type(data["i"]) is not int or type(data["e"]) is not int or not data["i"] <= now < data["e"] or data["e"] - data["i"] != lifetime:
                return None
            if any(not isinstance(data[k], str) or not NONCE.fullmatch(data[k]) for k in ("n", "c")):
                return None
            return data
        except (ValueError, UnicodeError, binascii.Error, TypeError):
            return None


def cookie_value(scope, name):
    # Bound parsing and reject duplicates, including multiple Cookie headers.
    headers = [v for k, v in scope["headers"] if k.lower() == b"cookie"]
    if sum(map(len, headers)) > 8192:
        return None
    values = []
    for header in headers:
        for item in header.split(b";"):
            key, sep, value = item.strip().partition(b"=")
            if sep and key == name.encode():
                try:
                    values.append(value.decode("ascii"))
                except UnicodeError:
                    return None
    return values[0] if len(values) == 1 else None


def set_cookie(response, name, value, max_age):
    response.set_cookie(name, value, max_age=max_age, secure=True, httponly=True, samesite="strict", path="/")


def same_origin(scope):
    headers = {}
    for key, value in scope["headers"]:
        key = key.lower()
        if key in {b"origin", b"host", b"sec-fetch-site"}:
            if key in headers:
                return False
            headers[key] = value
    if headers.get(b"sec-fetch-site") not in {None, b"same-origin", b"none"}:
        return False
    origin = headers.get(b"origin")
    if origin is None:
        return True  # A session-bound proof is still mandatory for unsafe requests.
    try:
        parsed = urlsplit(origin.decode("ascii"))
        host = headers.get(b"host", b"").decode("ascii")
        # Render terminates TLS; use no forwarded headers and accept HTTPS origin
        # only. Host alone never substitutes for the independent CSRF proof.
        return parsed.scheme == "https" and parsed.netloc == host and not parsed.path and not parsed.query and not parsed.fragment and parsed.username is None
    except (ValueError, UnicodeError):
        return False


class HostedAccess:
    def __init__(self, app, credentials):
        self.app, self.credentials = app, credentials
        self.signer = SessionSigner(credentials.signing_key)
        self.lock = threading.Lock()
        self.attempts = []  # At most ten global attempts per rolling minute, no IP/username storage.

    def allow_login(self):
        now = time.monotonic()
        with self.lock:
            self.attempts = [t for t in self.attempts if now - t < 60]
            if len(self.attempts) >= 10:
                return False
            self.attempts.append(now)
            return True

    def failure(self, code="HOST_AUTH_REQUIRED", status=401):
        return JSONResponse({"error": {"code": code, "message": "Hosted access required."}}, status_code=status)

    async def login(self, scope, receive):
        generic = HTMLResponse('<!doctype html><title>Access required</title><h1>Unable to sign in</h1><p>Check access details or try again later.</p><a href="/login">Return to login</a>', status_code=401)
        if not self.allow_login() or not same_origin(scope):
            return generic
        request = Request(scope, receive)
        if request.headers.get("content-type", "") != "application/x-www-form-urlencoded":
            return generic
        size, chunks = 0, []
        async for chunk in request.stream():
            size += len(chunk)
            if size > 8192:
                return generic
            chunks.append(chunk)
        try:
            fields = parse_qs(b"".join(chunks).decode("ascii"), strict_parsing=True, max_num_fields=3, encoding="utf-8", errors="strict")
            if set(fields) != {"username", "password", "csrf"} or any(len(v) != 1 for v in fields.values()):
                return generic
            proof = self.signer.verify(cookie_value(scope, LOGIN_COOKIE), "login")
            if proof is None or not hmac.compare_digest(fields["csrf"][0].encode(), proof["c"].encode()):
                return generic
            if not self.credentials.verifier.matches(fields["username"][0].encode(), fields["password"][0].encode()):
                return generic
        except (ValueError, UnicodeError):
            return generic
        token, _ = self.signer.issue()
        response = RedirectResponse("/", status_code=303)
        set_cookie(response, COOKIE, token, SESSION_SECONDS)
        set_cookie(response, LOGIN_COOKIE, "", 0)
        return response

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        async def safe_send(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []),
                    (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                    (b"x-frame-options", b"DENY"), (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")]}
            await send(message)
        method, path = scope["method"], scope["path"]
        exact = scope.get("raw_path", path.encode()) == path.encode()
        if exact and method == "GET" and path == "/health":
            return await self.app(scope, receive, safe_send)
        if exact and method == "GET" and path == "/login":
            token, csrf = self.signer.issue("login")
            response = HTMLResponse('<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1"><title>QA Sentinel login</title><h1>QA Sentinel</h1><p>Single-operator hosted demo. Synthetic evidence only.</p><form method="post" action="/auth/login"><p><label>Username <input name="username" autocomplete="username" required maxlength="1024"></label></p><p><label>Password <input name="password" type="password" autocomplete="current-password" required maxlength="1024"></label></p><input type="hidden" name="csrf" value="' + csrf + '"><button>Sign in</button></form></html>')
            set_cookie(response, LOGIN_COOKIE, token, 600)
            return await response(scope, receive, safe_send)
        if exact and method == "POST" and path == "/auth/login":
            return await (await self.login(scope, receive))(scope, receive, safe_send)
        session = self.signer.verify(cookie_value(scope, COOKIE))
        if session is None:
            # Navigation recovery is explicit; API calls remain safe 401, never replayed.
            navigation = method == "GET" and any(k.lower() == b"accept" and b"text/html" in v for k, v in scope["headers"])
            response = RedirectResponse("/login", status_code=303) if navigation else self.failure()
            return await response(scope, receive, safe_send)
        if method not in {"GET", "HEAD", "OPTIONS"}:
            tokens = [v for k, v in scope["headers"] if k.lower() == CSRF_HEADER.encode()]
            if not same_origin(scope) or len(tokens) != 1 or not hmac.compare_digest(tokens[0], session["c"].encode()):
                return await self.failure("HOST_CSRF_REQUIRED", 403)(scope, receive, safe_send)
        if exact and method == "GET" and path == "/auth/session":
            return await JSONResponse({"mode": "hosted-demo", "csrf": session["c"]})(scope, receive, safe_send)
        if exact and method == "POST" and path == "/auth/logout":
            response = RedirectResponse("/login", status_code=303)
            set_cookie(response, COOKIE, "", 0)
            set_cookie(response, LOGIN_COOKIE, "", 0)
            return await response(scope, receive, safe_send)
        await self.app(scope, receive, safe_send)
