"""Built SPA and accepted API on one origin, with narrow static fallback."""
from contextlib import asynccontextmanager
from pathlib import Path
import os
import re
import threading
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from qa_sentinel.api import create_api_app
from qa_sentinel.api.errors import application_error_handler
from qa_sentinel.application import ApplicationError, ApplicationErrorCode
from .config import HostConfig, HostError, canonical_path, overlaps
from .composition import compose
from .preview import PreviewAccess, preview_credentials


def validate_frontend(config: HostConfig):
    try:
        root = canonical_path(config.frontend_dist, exists=True)
        index = canonical_path(root / "index.html", exists=True)
        if not root.is_dir() or not index.is_file():
            raise ValueError("Missing frontend")
        if config.mode in {"demo", "preview-demo"} and overlaps(root, canonical_path(config.database.parent / "demo-workspace")):
            raise ValueError("Overlapping host directories")
        return root
    except (ValueError, OSError, RuntimeError):
        raise HostError("HOST_FRONTEND_BUILD_MISSING") from None


class FrontendFiles(StaticFiles):
    """StaticFiles owns containment/lookup. Only known browser routes get fallback."""
    UI_ROUTE = re.compile(r"/(?:projects(?:/[A-Za-z0-9_-]+)?|tasks/[A-Za-z0-9_-]+)/?$")
    ASSET_SUFFIXES = {".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".txt"}

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        parts = path.split("/")
        if "\\" in path or "%" in path or "\x00" in path or any(part.startswith(".") for part in parts if part):
            raise HTTPException(404)
        if parts[1:2] and parts[1] in {"api", "health", "openapi.json", "docs", "redoc"}:
            raise HTTPException(404)
        await super().__call__(scope, receive, send)

    async def get_response(self, path, scope):
        # StaticFiles returns native OS separators after its safe path normalization.
        path = path.replace(os.sep, "/")
        if scope["method"] not in {"GET", "HEAD"}:
            raise HTTPException(405)
        route = "/" + path.strip("/")
        if path in {".", "", "index.html"} or self.UI_ROUTE.fullmatch(route):
            return await super().get_response("index.html", scope)
        # Built assets only, never config/database/source or unknown UI routes.
        if not path.startswith("assets/") or Path(path).suffix.lower() not in self.ASSET_SUFFIXES:
            raise HTTPException(404)
        return await super().get_response(path, scope)


class ExclusiveExecution:
    """Single-process fail-fast admission; no workflow, queue or retry logic."""
    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        execution = scope["type"] == "http" and scope["method"] == "POST" and re.fullmatch(
            r"/api/v1/tasks/[^/]+/(run|resume)/?", scope["path"])
        if not execution:
            return await self.app(scope, receive, send)
        if not self.lock.acquire(blocking=False):
            response = await application_error_handler(None, ApplicationError(ApplicationErrorCode.RUNTIME_STOPPED))
            return await response(scope, receive, send)
        try:
            await self.app(scope, receive, send)
        finally:
            self.lock.release()


def create_host_app(config: HostConfig):
    credentials = preview_credentials() if config.mode == "preview-demo" else None
    root = validate_frontend(config)  # Full-stack readiness before migration/seed IO.
    composed = compose(config)
    try:
        app = create_api_app(composed.application)
        app.add_middleware(ExclusiveExecution)
        if credentials is not None:
            app.add_middleware(PreviewAccess, credentials=credentials)
        app.mount("/", FrontendFiles(directory=root, follow_symlink=False), name="frontend")
        app.state.host_composition = composed
        app.state.host_mode = config.mode

        @asynccontextmanager
        async def lifespan(app):
            try:
                yield
            finally:
                composed.close()
        app.router.lifespan_context = lifespan
        return app
    except Exception:
        composed.close()
        raise HostError("HOST_WEB_STARTUP_FAILED") from None
