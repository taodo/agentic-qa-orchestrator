"""Fixed preview-only container command; reads only the provider's port."""
import os
import re
import sys
from .cli import main as serve


def main():
    port = os.environ.get("PORT", "10000")
    if not re.fullmatch(r"[1-9][0-9]{0,4}", port) or int(port) > 65535:
        print("QA Sentinel startup failed: HOST_PREVIEW_PORT_INVALID", file=sys.stderr)
        return 1
    return serve(["serve", "--preview-demo", "--host", "0.0.0.0", "--port", port,
        "--database", "/tmp/qa-sentinel/state.sqlite3", "--frontend-dist", "/app/frontend/dist"])


if __name__ == "__main__":
    raise SystemExit(main())
