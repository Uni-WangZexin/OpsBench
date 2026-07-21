from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    OBSERVATION_CONFIG_MAP,
    apply_config_map,
    create_warning_event,
    emit,
    load_scenario,
    patch_state,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    scenario = load_scenario(Path(args.case_dir))
    patch_state(scenario, scenario["state"]["faulty"])
    labels = {
        "app.kubernetes.io/part-of": "opentelemetry-demo",
        "opsbench.io/case-id": scenario["id"],
        "opsbench.io/severity": scenario["severity"],
    }
    apply_config_map(
        OBSERVATION_CONFIG_MAP,
        {
            "condition": "Degraded",
            "symptom": scenario["symptom"],
            "signal": scenario["signal"],
            "affected_resource": scenario["resource"],
        },
        labels,
    )
    create_warning_event(scenario)
    emit({"passed": True, "phase": "inject"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
