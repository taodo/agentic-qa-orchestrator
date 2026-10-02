"""One explicit local serving command; no import-time server or environment dump."""
import argparse
from pathlib import Path
import sys
import tempfile
from .config import HostConfig, HostError, load_local_config
from .web import create_host_app


def parser():
    value = argparse.ArgumentParser(prog="qa-sentinel", description="Local host or explicitly protected demo preview.")
    commands = value.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Serve locally or as an explicitly protected demo preview",
        description="Local modes are loopback-only; preview-demo requires environment Basic credentials.")
    mode = serve.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true", help="Offline synthetic calculator workflow; no API key or source writes")
    mode.add_argument("--config", type=Path, help="Explicit real local JSON configuration; OPENAI_API_KEY stays in environment")
    mode.add_argument("--preview-demo", action="store_true", help="Protected fake-only preview; environment Basic credentials required")
    serve.add_argument("--host", choices=("127.0.0.1", "::1", "0.0.0.0"), default=None,
        help="Default 127.0.0.1; 0.0.0.0 requires --preview-demo")
    serve.add_argument("--port", type=int, default=None, help="TCP port (default: 8000)")
    serve.add_argument("--database", type=Path, help="File-backed SQLite path")
    serve.add_argument("--frontend-dist", type=Path, help="Built Vite directory (demo default: frontend/dist)")
    return value


def configuration(args) -> HostConfig:
    overrides = {name: getattr(args, name) for name in ("host", "port", "database", "frontend_dist") if getattr(args, name) is not None}
    try:
        if args.demo or args.preview_demo:
            return HostConfig.model_validate({"mode": "preview-demo" if args.preview_demo else "demo",
                "database": Path(tempfile.gettempdir()) / "qa-sentinel" / "state.sqlite3" if args.preview_demo else Path.home() / ".qa-sentinel" / "demo" / "state.sqlite3",
                "frontend_dist": Path.cwd() / "frontend" / "dist", **overrides})
        config = load_local_config(args.config)
        return HostConfig.model_validate({**config.model_dump(), **overrides})
    except (ValueError, OSError, RuntimeError):
        raise HostError("HOST_CONFIG_INVALID") from None


def main(argv=None):
    command_parser = parser()
    args = command_parser.parse_args(argv)
    if args.host == "0.0.0.0" and not args.preview_demo:
        command_parser.error("External bind requires --preview-demo")
    app = None
    try:
        config = configuration(args)
        app = create_host_app(config)
        # Import/start only after explicit command and complete safe preflight.
        import uvicorn
        posture = "protected deterministic preview" if config.mode == "preview-demo" else "local, no auth"
        print(f"QA Sentinel {config.mode} mode: http://{config.host if ':' not in config.host else '[' + config.host + ']'}:{config.port} ({posture})")
        uvicorn.run(app, host=config.host, port=config.port, workers=1, reload=False,
            access_log=False, log_level="warning", proxy_headers=False, ws="none", loop="asyncio", http="h11")
        return 0
    except (Exception, SystemExit) as exc:
        code = str(exc) if isinstance(exc, HostError) else "HOST_STARTUP_FAILED"
        print(f"QA Sentinel startup failed: {code}", file=sys.stderr)
        return 1
    finally:
        if app is not None:
            app.state.host_composition.close()


if __name__ == "__main__":
    raise SystemExit(main())
