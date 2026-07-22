from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, scenario
from faults import inject_fault


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    case_dir = Path(args.case_dir).resolve()
    data = scenario(case_dir)["implementation"]
    inject_fault(case_dir, data)
    emit({"phase": "inject", "passed": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
