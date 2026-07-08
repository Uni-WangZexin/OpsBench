from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, psql_with_retries, wait_for_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    case_dir = Path(args.case_dir)

    wait_for_db(case_dir)
    result = psql_with_retries(
        case_dir,
        (
            "SELECT count(*) FROM pg_indexes "
            "WHERE schemaname = 'public' "
            "AND tablename = 'orders' "
            "AND indexname = 'idx_orders_customer_id';"
        ),
    )
    index_count = int(result.stdout.strip() or "0") if result.returncode == 0 else -1
    passed = result.returncode == 0 and index_count == 0
    emit(
        {
            "passed": passed,
            "phase": "check_injected",
            "index_present": index_count > 0,
            "stderr": result.stderr.strip(),
        }
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
