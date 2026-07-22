from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, load_scenario
from faults import fault_is_active


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    scenario = load_scenario(Path(args.case_dir))
    passed, details = fault_is_active(scenario)
    emit({"passed": passed, "phase": "check_injected", "details": details})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
