from __future__ import annotations

import cdp_all_balances


def main() -> int:
    return cdp_all_balances.main(["--official"])


if __name__ == "__main__":
    raise SystemExit(main())
