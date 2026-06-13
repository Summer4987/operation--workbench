from __future__ import annotations

import errno
import os
import tempfile
import time
from pathlib import Path


RETRY_ERRNOS = {
    errno.EAGAIN,
    errno.EACCES,
    errno.EBUSY,
    errno.EDEADLK,
    errno.EPERM,
}


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8", mode: int | None = 0o644, attempts: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    last_error: OSError | None = None
    for attempt in range(attempts):
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile("w", encoding=encoding, dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
                temp_path = handle.name
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            if mode is not None:
                os.chmod(temp_path, mode)
            os.replace(temp_path, path)
            return
        except OSError as exc:
            last_error = exc
            if temp_path:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            if exc.errno not in RETRY_ERRNOS or attempt == attempts - 1:
                raise
            time.sleep(0.25 * (2**attempt))
    if last_error:
        raise last_error
