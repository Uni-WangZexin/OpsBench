from __future__ import annotations

import argparse
from pathlib import Path

from common import emit, load_scenario, state_value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    scenario = load_scenario(Path(args.case_dir))
    observed = state_value(scenario)
    expected = scenario["state"]["faulty"]
    passed = observed == expected
    emit({"passed": passed, "phase": "check_injected", "observed": observed})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
