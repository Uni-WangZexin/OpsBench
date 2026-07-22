from __future__ import annotations

import argparse
from pathlib import Path

from common import (
    OBSERVATION_CONFIG_MAP,
    apply_config_map,
    create_warning_event,
    emit,
    load_scenario,
)
from faults import inject_real_fault, wait_for_fault


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    scenario = load_scenario(Path(args.case_dir))
    inject_real_fault(scenario)
    active, details = wait_for_fault(scenario, expected_active=True)
    if not active:
        raise RuntimeError(f"real fault did not become active: {details}")
    labels = {
        "app.kubernetes.io/part-of": "opentelemetry-demo",
        "app.kubernetes.io/component": "monitoring",
        "observability.open-telemetry.io/severity": scenario["severity"],
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
    emit({"passed": True, "phase": "inject", "details": details})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
