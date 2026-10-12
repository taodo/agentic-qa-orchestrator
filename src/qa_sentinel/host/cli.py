"""Explicit serving and inert local onboarding; no import-time server or env dump."""
import argparse
from pathlib import Path
import sys
import tempfile
from uuid import UUID
from .config import HostConfig, HostError, load_local_config
from .web import create_host_app


class TargetArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # No invalid argv/value or raw argparse diagnostic reaches proving output.
        self.exit(2, "Target status: TARGET_NOT_READY\nSafe error: TARGET_ARGUMENTS_INVALID\n")


def parser(*, target_errors=False):
    kind = TargetArgumentParser if target_errors else argparse.ArgumentParser
    value = kind(prog="qa-sentinel", description="Local host or explicitly protected demo preview.")
    commands = value.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Serve locally or as an explicitly protected demo preview",
        description="Local modes are loopback-only; preview-demo requires environment Basic credentials.")
    mode = serve.add_mutually_exclusive_group(required=True)
    mode.add_argument("--demo", action="store_true", help="Offline synthetic calculator workflow; no API key or source writes")
    mode.add_argument("--config", type=Path, help="Explicit real local JSON configuration; OPENAI_API_KEY stays in environment")
    mode.add_argument("--preview-demo", action="store_true", help="Protected fake-only preview; environment Basic credentials required")
    mode.add_argument("--hosted-demo", action="store_true", help="Persistent-capable synthetic demo; environment session secrets and data root required")
    serve.add_argument("--host", choices=("127.0.0.1", "::1", "0.0.0.0"), default=None,
        help="Default 127.0.0.1; 0.0.0.0 requires --preview-demo or --hosted-demo")
    serve.add_argument("--port", type=int, default=None, help="TCP port (default: 8000)")
    serve.add_argument("--database", type=Path, help="File-backed SQLite path")
    serve.add_argument("--frontend-dist", type=Path, help="Built Vite directory (demo default: frontend/dist)")
    local = commands.add_parser("local", help="Initialize, validate or start explicit trusted local configuration")
    setup = local.add_subparsers(dest="local_command", required=True)
    init = setup.add_parser("init", help="Write one Project binding; no model calls or execution",
        description="Requires existing Project identity and absolute database/frontend/workspace paths. No API key needed.")
    init.add_argument("--database", type=Path, required=True)
    init.add_argument("--frontend-dist", type=Path, required=True)
    init.add_argument("--project-key", required=True)
    init.add_argument("--workspace", type=Path, required=True)
    init.add_argument("--pytest-target", action="append", required=True)
    init.add_argument("--test-cwd", default=".", help="Relative test directory inside the full workspace root (default: .)")
    init.add_argument("--config", type=Path, required=True)
    init.add_argument("--host", choices=("127.0.0.1", "::1"), default="127.0.0.1")
    init.add_argument("--port", type=int, default=8000)
    init.add_argument("--overwrite", action="store_true", help="Explicitly replace an entire valid local config with this one Project binding")
    init.add_argument("--create-parent", action="store_true", help="Explicitly create the selected safe config parent")
    validate = setup.add_parser("validate", help="Read-only readiness; no server, provider, pytest or source writes")
    validate.add_argument("--config", type=Path, required=True)
    start = setup.add_parser("start", help="Build frontend, validate, then serve locally; no migration or tests")
    start.add_argument("--config", type=Path, required=True)
    reconcile = setup.add_parser("reconcile", help="Read-only crash safety; no provider, pytest, source writes or evidence repair")
    reconcile.add_argument("--config", type=Path, required=True)
    reconcile.add_argument("--task", type=UUID, required=True)
    for name in ("target-check", "target-test"):
        target = setup.add_parser(name, help="Check an external real target without execution" if name == "target-check" else "Run one approved local pytest proving execution; no workflow",
            description="Trusted local-real CLI only. Requires an existing Project and external repository; no API key needed.")
        target.add_argument("--database", type=Path, required=True)
        owner = target.add_mutually_exclusive_group(required=True)
        owner.add_argument("--project-key")
        owner.add_argument("--project-id", type=UUID)
        target.add_argument("--workspace", type=Path, required=True)
        target.add_argument("--test-cwd", default=".")
        target.add_argument("--pytest-target", action="append", required=True)
        target.add_argument("--timeout-seconds", type=float, default=120)
    return value


def configuration(args) -> HostConfig:
    overrides = {name: getattr(args, name) for name in ("host", "port", "database", "frontend_dist") if getattr(args, name) is not None}
    try:
        if args.hosted_demo:
            import os
            from .hosted import hosted_data_dir
            from .access import hosted_credentials
            hosted_credentials()  # Secrets before any storage IO.
            if args.database is not None:
                raise HostError("HOST_HOSTED_DATA_INVALID")
            frontend = args.frontend_dist or Path.cwd() / "frontend" / "dist"
            root = hosted_data_dir(os.environ.get("QA_SENTINEL_DATA_DIR", ""), frontend)
            return HostConfig(mode="hosted-demo", database=root / "state.sqlite3", data_dir=root,
                frontend_dist=frontend, **{k: v for k, v in overrides.items() if k != "frontend_dist"})
        if args.demo or args.preview_demo:
            return HostConfig.model_validate({"mode": "preview-demo" if args.preview_demo else "demo",
                "database": Path(tempfile.gettempdir()) / "qa-sentinel" / "state.sqlite3" if args.preview_demo else Path.home() / ".qa-sentinel" / "demo" / "state.sqlite3",
                "frontend_dist": Path.cwd() / "frontend" / "dist", **overrides})
        config = load_local_config(args.config)
        return HostConfig.model_validate({**config.model_dump(), **overrides})
    except (ValueError, OSError, RuntimeError):
        raise HostError("HOST_CONFIG_INVALID") from None


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    command_parser = parser(target_errors=arguments[:2] in (["local", "target-check"], ["local", "target-test"]))
    args = command_parser.parse_args(arguments)
    if args.command == "local":
        if args.local_command == "start":
            from .start import start_local
            return start_local(args.config)
        if args.local_command in {"target-check", "target-test"}:
            from .targets import target_command
            return target_command(args)
        if args.local_command == "reconcile":
            from .reconciliation import reconcile_command
            return reconcile_command(args)
        from .onboarding import local_command
        return local_command(args)
    if args.host == "0.0.0.0" and not (args.preview_demo or args.hosted_demo):
        command_parser.error("External bind requires --preview-demo or --hosted-demo")
    try:
        config = configuration(args)
    except HostError as exc:
        print(f"QA Sentinel startup failed: {exc}", file=sys.stderr)
        return 1
    return serve_config(config)


def serve_config(config: HostConfig, *, existing_database=False):
    """Shared foreground server lifetime; local start opts out of migration."""
    app = None
    try:
        app = create_host_app(config, existing_database=True) if existing_database else create_host_app(config)
        # Import/start only after explicit command and complete safe preflight.
        import uvicorn
        posture = "protected deterministic demo" if config.mode in {"preview-demo", "hosted-demo"} else "local, no auth"
        print(f"QA Sentinel {config.mode} mode: http://{config.host if ':' not in config.host else '[' + config.host + ']'}:{config.port} ({posture})")
        print("Press Ctrl+C to stop.")
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
