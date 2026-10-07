"""Inert validation of an operator-owned native Python path; never execution."""
import os
from pathlib import Path
import re
import stat


def target_python(value: Path) -> Path:
    """Reject wrappers/links; native binary identity remains the operator's trust.

    No interpreter probe, dependency discovery, installation or subprocess.
    POSIX venvs using symlinks must be prepared with copies by the operator.
    """
    try:
        path = Path(value)
        raw = str(path)
        if (not path.is_absolute() or '..' in path.parts or path.drive.startswith('\\') or len(raw) > 2048 or
            any(ord(c) < 32 or ord(c) == 127 for c in raw) or
            any(c in raw for c in (';', '|', '&', '`', '$', '<', '>')) or
            ':' in raw[2:] or not re.fullmatch(r'python(?:[0-9]+(?:\.[0-9]+)*)?(?:\.exe)?', path.name, re.IGNORECASE)):
            raise ValueError
        if os.name == 'nt' and path.suffix.casefold() != '.exe':
            raise ValueError
        for component in (path, *path.parents):
            if component.is_symlink() or component.is_junction():
                raise ValueError
        path = path.resolve(strict=True)
        if not stat.S_ISREG(path.stat().st_mode) or not os.access(path, os.X_OK):
            raise ValueError
        with path.open('rb') as stream:
            header = stream.read(64)
            magic = header[:4]
            if os.name == 'nt':
                offset = int.from_bytes(header[60:64], 'little')
                native = len(header) == 64 and header[:2] == b'MZ' and 64 <= offset <= 65532
                if native:
                    stream.seek(offset)
                    native = stream.read(4) == b'PE\0\0'
            else:
                native = magic in {
                    b'\x7fELF', b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe',
                    b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe',
                    b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'}
        if not native:
            raise ValueError
        return path
    except (OSError, ValueError, RuntimeError, TypeError):
        raise ValueError('Target Python interpreter is invalid') from None
