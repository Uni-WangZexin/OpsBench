from __future__ import annotations

import argparse
import os
from pathlib import Path

from common import (
    RELEASE_NAME,
    agent_cluster_role_binding,
    emit,
    helm,
    kubectl,
    load_scenario,
    namespace,
)
from faults import cleanup_real_fault


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    args = parser.parse_args()
    scenario = load_scenario(Path(args.case_dir))
    ns = namespace()
    cleanup_real_fault(scenario)
    if os.environ.get("OPSBENCH_OTEL_SKIP_INSTALL") != "1":
        helm(["uninstall", RELEASE_NAME, "--namespace", ns], timeout=300)
    result = kubectl(["delete", "namespace", ns, "--ignore-not-found=true"], timeout=300)
    binding_result = kubectl(
        [
            "delete",
            "clusterrolebinding",
            agent_cluster_role_binding(ns),
            "--ignore-not-found=true",
        ]
    )
    passed = result.returncode == 0 and binding_result.returncode == 0
    emit({"passed": passed, "phase": "cleanup", "namespace": ns})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
