from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, scenario
from faults import fault_state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    case_dir = Path(args.case_dir).resolve()
    passed, details = fault_state(case_dir, scenario(case_dir)["implementation"], active=True)
    emit({"phase": "check_injected", "passed": passed, "checks": [{"name": "live_fault_active", "passed": passed, **details}]})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
