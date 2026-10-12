"""Fixed trusted-checkout frontend build, then authoritative local preflight/serve."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from qa_sentinel.execution.process_tree import ProcessTree
from . import onboarding
from .config import HostError, canonical_path, load_local_config
from .database import SchemaNotReady

BUILD_TIMEOUT_SECONDS = 300


def frontend_directory(config):
    # Source/editable checkout only. Never execute package scripts in a target or
    # infer an executable directory from arbitrary operator/model request fields.
    try:
        root = canonical_path(Path(__file__).resolve().parents[3] / "frontend", exists=True)
        if (config.frontend_dist != root / "dist" or not (root / "package.json").is_file()
                or not (root / "vite.config.ts").is_file()):
            raise ValueError("Checkout frontend required")
        return root
    except (ValueError, OSError, RuntimeError):
        raise HostError("HOST_LOCAL_BUILD_CHECKOUT_REQUIRED") from None


def build_argv():
    if os.name == "nt":
        # npm.cmd is a batch wrapper. Invoke the installed npm CLI through Node
        # directly instead, avoiding Windows' implicit command-shell execution.
        node = shutil.which("node.exe")
        if node:
            npm_cli = Path(node).resolve().parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
            if npm_cli.is_file():
                return [node, str(npm_cli), "run", "build"]
    else:
        npm = shutil.which("npm")
        if npm:
            return [npm, "run", "build"]
    raise HostError("HOST_LOCAL_BUILD_TOOLING_MISSING")


def build_frontend(config):
    root = frontend_directory(config)
    argv = build_argv()
    # No credential/provider/Node-options/npm override inheritance. Do not print
    # arbitrary build output: it can contain source, paths, terminal escapes or
    # secrets. DEVNULL bounds memory/output to zero; retain the numeric exit code.
    allowed = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
               "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
    environment = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    process = None
    tree = None
    try:
        process = subprocess.Popen(argv, cwd=root, shell=False, env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        tree = ProcessTree(process)
        return process.wait(timeout=BUILD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise HostError("HOST_LOCAL_BUILD_TIMEOUT") from None
    except OSError:
        raise HostError("HOST_LOCAL_BUILD_START_FAILED") from None
    finally:
        if tree is not None:
            tree.close()  # Existing utility also removes orphan build descendants.
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)


REMEDIATION = {
    "HOST_CONFIG_INVALID": "Check the existing local JSON configuration, paths and loopback host.",
    "HOST_LOCAL_BUILD_CHECKOUT_REQUIRED": "Use a source/editable checkout and configure its frontend/dist directory.",
    "HOST_LOCAL_BUILD_TOOLING_MISSING": "Install Node/npm explicitly; Windows requires Node's bundled npm CLI. No dependency installation was attempted.",
    "HOST_LOCAL_BUILD_START_FAILED": "Check local Node/npm availability and filesystem permissions.",
    "HOST_LOCAL_BUILD_TIMEOUT": "Frontend build exceeded 300 seconds. Inspect npm run build manually in the checkout frontend directory.",
    "HOST_LOCAL_DATABASE_NOT_READY": "Select an existing database at the required schema; migrate explicitly while the host is stopped.",
    "HOST_PROJECT_NOT_FOUND": "Select an existing persisted Project key; startup does not create Projects.",
    "HOST_RUNTIME_POLICY_REJECTED": "Check the explicitly configured workspace and repository/mutation boundaries.",
    "HOST_TEST_POLICY_REJECTED": "Check configured relative test cwd and pytest targets; startup does not execute tests.",
    "HOST_FRONTEND_BUILD_MISSING": "Check configured frontend/dist and build permissions.",
}


def start_local(path):
    try:
        print("Preparing Agentic QA Orchestrator...", flush=True)
        config = load_local_config(path)
        print("Frontend: building (npm run build)...", flush=True)
        exit_code = build_frontend(config)
        if exit_code != 0:
            print(f"Overall: NOT READY (HOST_LOCAL_BUILD_FAILED; process exit status: {exit_code})", file=sys.stderr)
            print("Build diagnostics withheld to protect source/secrets. Inspect npm run build manually in frontend; install dependencies explicitly if missing. Validation/serve did not run.", file=sys.stderr)
            return exit_code if 1 <= exit_code <= 255 else 1
        print("Frontend: build completed.\nLocal environment:", flush=True)
        report = onboarding.validate_local(config)
        print(report.render(), flush=True)
        if not report.model_ready:
            print("Set OPENAI_API_KEY in the current process environment, then start again. The key is presence-checked only; never put it in JSON.", file=sys.stderr)
            return 1
        from .cli import serve_config
        return serve_config(config, existing_database=True)
    except KeyboardInterrupt:
        return 130  # Build/preflight interrupt; serve's cleanup still runs.
    except Exception as exc:
        code = str(exc) if isinstance(exc, HostError) else "HOST_LOCAL_START_FAILED"
        print(f"Overall: NOT READY ({code})", file=sys.stderr)
        if isinstance(exc, SchemaNotReady):
            print(f"Database schema is not ready.\nCurrent: {exc.current}\nRequired: {exc.required}", file=sys.stderr)
        print(REMEDIATION.get(code, "Check trusted local configuration and prerequisites; no automatic repair was attempted."), file=sys.stderr)
        print("No migration was run automatically.", file=sys.stderr)
        return 1
