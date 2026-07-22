from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


def compose(case_dir: Path, args: list[str], timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [
        "docker",
        "compose",
        "-p",
        os.environ["OPSBENCH_COMPOSE_PROJECT"],
        "-f",
        str(case_dir / "docker-compose.yaml"),
        *args,
    ]
    result = subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"command failed ({' '.join(command)}): {detail}")
    return result


def target(case_dir: Path, args: list[str], timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    return compose(case_dir, ["exec", "-T", "target", *args], timeout=timeout, check=check)


def shell(case_dir: Path, command: str, timeout: int = 30, check: bool = True) -> subprocess.CompletedProcess[str]:
    return target(case_dir, ["sh", "-lc", command], timeout=timeout, check=check)


def scenario(case_dir: Path) -> dict[str, Any]:
    return json.loads((case_dir / "hidden" / "scenario.json").read_text(encoding="utf-8"))


def set_json_value(case_dir: Path, path: str, key: str, value: Any) -> None:
    program = (
        "import json,sys; p=sys.argv[1]; d=json.load(open(p)); "
        "d[sys.argv[2]]=json.loads(sys.argv[3]); "
        "open(p,'w').write(json.dumps(d,indent=2,sort_keys=True)+'\\n')"
    )
    target(
        case_dir,
        ["python3", "-c", program, path, key, json.dumps(value)],
    )


def http_code(
    case_dir: Path,
    url: str,
    method: str = "GET",
    data: str = "",
    cacert: str = "",
) -> int:
    args = ["curl", "-sS", "--max-time", "4", "-o", "/tmp/opsbench-probe", "-w", "%{http_code}"]
    if method != "GET":
        args.extend(["-X", method])
    if data:
        args.extend(["--data-binary", data])
    if cacert:
        args.extend(["--cacert", cacert])
    args.append(url)
    result = target(case_dir, args, timeout=8, check=False)
    try:
        return int(result.stdout.strip()[-3:]) if result.returncode == 0 else 0
    except ValueError:
        return 0


def app_restart(case_dir: Path, check: bool = True) -> None:
    target(case_dir, ["/opt/opsbench/runtime/appctl.sh", "restart"], check=check)


def app_stop(case_dir: Path) -> None:
    target(case_dir, ["/opt/opsbench/runtime/appctl.sh", "stop"], check=False)


def app_start(case_dir: Path, check: bool = True) -> None:
    target(case_dir, ["/opt/opsbench/runtime/appctl.sh", "start"], check=check)


def wait_http(case_dir: Path, url: str, expected: int = 200, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if http_code(case_dir, url) == expected:
            return True
        time.sleep(0.25)
    return False


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True))
