"""Built SPA and accepted API on one origin, with narrow static fallback."""
from contextlib import asynccontextmanager
from pathlib import Path
import os
import re
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from qa_sentinel.api import create_api_app
from .config import HostConfig, HostError
from .composition import compose
from .preview import PreviewAccess, preview_credentials
from .access import HostedAccess, hosted_credentials
from .hosted import preflight_storage
from .preflight import validate_frontend
from .status import add_runtime_status


class FrontendFiles(StaticFiles):
    """StaticFiles owns containment/lookup. Only known browser routes get fallback."""
    UI_ROUTE = re.compile(r"/(?:operations|projects(?:/[A-Za-z0-9_-]+)?|tasks/[A-Za-z0-9_-]+)/?$")
    ASSET_SUFFIXES = {".js", ".css", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".woff", ".woff2", ".txt"}

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        parts = path.split("/")
        if "\\" in path or "%" in path or "\x00" in path or any(part.startswith(".") for part in parts if part):
            raise HTTPException(404)
        if parts[1:2] and parts[1] in {"api", "host", "health", "openapi.json", "docs", "redoc"}:
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


def create_host_app(config: HostConfig, *, existing_database=False):
    credentials = preview_credentials() if config.mode == "preview-demo" else None
    operator = hosted_credentials() if config.mode == "hosted-demo" else None
    if operator is not None:
        preflight_storage(config)
    root = validate_frontend(config)  # Full-stack readiness before migration/seed IO.
    composed = compose(config, existing_database=True) if existing_database else compose(config)
    try:
        app = create_api_app(composed.application)
        if credentials is not None:
            app.add_middleware(PreviewAccess, credentials=credentials)
        if operator is not None:
            app.add_middleware(HostedAccess, credentials=operator)
        else:
            @app.get("/auth/session")
            def access_mode():
                return {"mode": config.mode}
        add_runtime_status(app, composed, config.mode)
        app.mount("/", FrontendFiles(directory=root, follow_symlink=False), name="frontend")
        app.state.host_composition = composed
        app.state.host_mode = config.mode

        @asynccontextmanager
        async def lifespan(app):
            try:
                composed.worker.start()
                yield
            finally:
                composed.close()
        app.router.lifespan_context = lifespan
        return app
    except Exception:
        composed.close()
        raise HostError("HOST_WEB_STARTUP_FAILED") from None
