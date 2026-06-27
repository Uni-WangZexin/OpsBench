from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, psql_with_retries, wait_for_db, wait_for_index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    case_dir = Path(args.case_dir)

    wait_for_db(case_dir)
    wait_for_index(case_dir, "idx_orders_customer_id")
    result = psql_with_retries(
        case_dir,
        "DROP INDEX IF EXISTS idx_orders_customer_id; ANALYZE orders;",
        attempts=5,
        timeout=120,
    )
    emit(
        {
            "passed": result.returncode == 0,
            "phase": "inject",
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
