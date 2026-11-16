"""Exit zero only for a fresh, explicitly non-retryable collection result."""
import json
import sys
from pathlib import Path


def stop_retry(path: Path, since: float) -> bool:
    try:
        return path.stat().st_mtime >= since and json.loads(path.read_text()).get('retryable') is False
    except (OSError, ValueError, TypeError):
        return False


if __name__ == '__main__':
    raise SystemExit(0 if stop_retry(Path(sys.argv[1]), float(sys.argv[2])) else 1)
