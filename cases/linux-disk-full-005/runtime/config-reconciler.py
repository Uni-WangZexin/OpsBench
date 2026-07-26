#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path


POLICY = Path("/var/lib/opsbench/control/current")
APP_CONFIG = Path("/etc/opsbench/app.json")
LOG = Path("/var/log/demo/config-reconciler.log")


def log(message: str) -> None:
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


while True:
    try:
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        config = json.loads(APP_CONFIG.read_text(encoding="utf-8"))
        desired = {
            "port": int(policy["listener_port"]),
            "feature_checkout_v2": bool(policy["feature_checkout_v2"]),
        }
        changed = any(config.get(key) != value for key, value in desired.items())
        if changed:
            config.update(desired)
            temporary = APP_CONFIG.with_suffix(".json.next")
            temporary.write_text(
                json.dumps(config, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(APP_CONFIG)
            result = subprocess.run(
                ["/opt/opsbench/runtime/appctl.sh", "restart"],
                text=True,
                capture_output=True,
                check=False,
            )
            log(
                f"applied control-plane revision={policy.get('revision', 'unknown')} "
                f"restart_status={result.returncode}"
            )
    except Exception as exc:  # noqa: BLE001 - a reconciler must survive bad state.
        log(f"reconciliation deferred: {type(exc).__name__}: {exc}")
    time.sleep(0.4)
