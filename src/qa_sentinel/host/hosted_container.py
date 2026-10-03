"""Fixed hosted synthetic entrypoint. Provider port/data root and env secrets only."""
import os
from pathlib import Path
import re
import sys
from .cli import main as serve


def main():
    port = os.environ.get("PORT", "10000")
    if not re.fullmatch(r"[1-9][0-9]{0,4}", port) or int(port) > 65535:
        print("QA Sentinel startup failed: HOST_HOSTED_PORT_INVALID", file=sys.stderr)
        return 1
    # /tmp cannot provide hosted durability. Test compositions use prepared temp
    # directories, while this container command requires a provider mount.
    root = Path(os.environ.get("QA_SENTINEL_DATA_DIR", ""))
    if not root.is_absolute() or root == Path("/tmp") or root.is_relative_to(Path("/tmp")):
        print("QA Sentinel startup failed: HOST_HOSTED_DATA_INVALID", file=sys.stderr)
        return 1
    return serve(["serve", "--hosted-demo", "--host", "0.0.0.0", "--port", port,
        "--frontend-dist", "/app/frontend/dist"])


if __name__ == "__main__":
    raise SystemExit(main())
