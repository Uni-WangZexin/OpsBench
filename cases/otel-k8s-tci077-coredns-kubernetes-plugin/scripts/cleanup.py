from __future__ import annotations

import argparse
import os
from pathlib import Path

from common import RELEASE_NAME, emit, helm, kubectl, namespace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", required=True)
    parser.parse_args()
    ns = namespace()
    if os.environ.get("OPSBENCH_OTEL_SKIP_INSTALL") != "1":
        helm(["uninstall", RELEASE_NAME, "--namespace", ns], timeout=300)
    result = kubectl(["delete", "namespace", ns, "--ignore-not-found=true"], timeout=300)
    passed = result.returncode == 0
    emit({"passed": passed, "phase": "cleanup", "namespace": ns})
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
