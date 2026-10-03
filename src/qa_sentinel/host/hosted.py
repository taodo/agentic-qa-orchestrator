"""Provider-owned storage and fixed ephemeral fake identity; no target workspace."""
import hashlib
import tempfile
from pathlib import Path
from .config import HostError, canonical_path, overlaps


def hosted_data_dir(value, frontend):
    try:
        root = Path(value)
        if not value or not root.is_absolute():
            raise ValueError("Explicit absolute root required")
        root = canonical_path(root)
        # Package source, checkout source (editable installs), and built assets.
        protected = [Path(__file__).resolve().parents[1], Path(frontend)]
        checkout = Path(__file__).resolve().parents[3]
        if (checkout / "pyproject.toml").is_file():
            protected.append(checkout)
        if any(overlaps(root, canonical_path(path)) for path in protected):
            raise ValueError("Overlapping root")
        if root.exists() and not root.is_dir():
            raise ValueError("Not a directory")
        if not root.exists() and not root.parent.is_dir():
            raise ValueError("Provider parent must already exist")
        return root
    except (ValueError, OSError, RuntimeError, TypeError):
        raise HostError("HOST_HOSTED_DATA_INVALID") from None


def hosted_identity_root(config):
    # Stable across restarts/deploys with the same provider mount. This empty
    # directory only satisfies the accepted fake binding contract, never holds
    # source or durable state. No physical services are attached to it.
    digest = hashlib.sha256(str(config.data_dir).encode("utf-8")).hexdigest()
    root = canonical_path(Path(tempfile.gettempdir()) / "qa-sentinel-hosted-identity" / digest)
    if overlaps(root, config.data_dir) or overlaps(root, config.frontend_dist):
        raise HostError("HOST_HOSTED_DATA_INVALID")
    return root


def preflight_storage(config):
    root = hosted_data_dir(str(config.data_dir), config.frontend_dist)
    if root != config.data_dir or config.database != root / "state.sqlite3":
        raise HostError("HOST_HOSTED_DATA_INVALID")
    hosted_identity_root(config)
