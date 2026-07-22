from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from common import (
    app_restart,
    app_start,
    app_stop,
    http_code,
    set_json_value,
    shell,
    target,
    wait_http,
)


APP_CONFIG = "/etc/opsbench/app.json"
DEPENDENCY_CONFIG = "/etc/opsbench/dependency.json"


def inject_fault(case_dir: Path, data: dict[str, Any]) -> None:
    strategy = data["strategy"]
    if strategy in {"cpu_runaway", "memory_growth"}:
        mode = "compute" if strategy == "cpu_runaway" else "retention"
        command = (
            f"REPORT_PROFILE={mode} nohup python3 /opt/opsbench/runtime/workload.pyc "
            ">/var/log/demo/system-report.log 2>&1 </dev/null & "
            "echo $! >/run/system-report.pid"
        )
        shell(case_dir, command)
        if strategy == "memory_growth":
            time.sleep(2.0)
    elif strategy == "fd_leak":
        set_json_value(case_dir, APP_CONFIG, "fd_leak", True)
        app_restart(case_dir)
        for _ in range(48):
            http_code(case_dir, "http://127.0.0.1:8080/fd-test")
    elif strategy == "disk_full":
        shell(case_dir, "REPORT_PROFILE=storage nohup python3 /opt/opsbench/runtime/workload.pyc >/var/log/demo/storage-index.log 2>&1 </dev/null & echo $! >/run/storage-index.pid")
        time.sleep(1.0)
    elif strategy == "inode_full":
        shell(case_dir, "mkdir -p /data/cache; i=0; while touch /data/cache/item-$i 2>/dev/null; do i=$((i+1)); done; true")
    elif strategy == "upload_permission":
        shell(case_dir, "chown root:root /data/uploads; chmod 0500 /data/uploads")
    elif strategy == "wrong_port":
        set_json_value(case_dir, APP_CONFIG, "port", 8081)
        app_restart(case_dir)
    elif strategy == "loopback_bind":
        set_json_value(case_dir, APP_CONFIG, "bind", "127.0.0.1")
        app_restart(case_dir)
    elif strategy == "malformed_config":
        app_stop(case_dir)
        shell(case_dir, "sed -i '$s/}/,}/' /etc/opsbench/app.json")
        app_start(case_dir, check=False)
    elif strategy == "stale_pid":
        app_stop(case_dir)
        shell(case_dir, "printf '999999\\n' >/run/demo-app.pid")
    elif strategy == "dependency_dns":
        set_json_value(case_dir, APP_CONFIG, "dependency_host", "catalog.invalid")
        app_restart(case_dir)
    elif strategy == "dependency_port":
        set_json_value(case_dir, APP_CONFIG, "dependency_port", 9002)
        app_restart(case_dir)
    elif strategy == "dependency_status":
        shell(case_dir, "chown root:root /var/lib/catalog/catalog.json; chmod 0000 /var/lib/catalog/catalog.json")
    elif strategy == "dependency_payload":
        shell(case_dir, "printf '%s' '{not-json' >/var/lib/catalog/catalog.json; chown demo:demo /var/lib/catalog/catalog.json")
    elif strategy == "dependency_timeout":
        set_json_value(case_dir, DEPENDENCY_CONFIG, "delay_ms", 900)
        set_json_value(case_dir, APP_CONFIG, "dependency_timeout_ms", 150)
        app_restart(case_dir)
    elif strategy == "feature_flag":
        set_json_value(case_dir, APP_CONFIG, "feature_checkout_v2", True)
    elif strategy == "file_lock":
        shell(case_dir, "touch /run/report.lock; chown demo:demo /run/report.lock; nohup flock /run/report.lock sleep 3600 >/var/log/demo/report-worker.log 2>&1 </dev/null & echo $! >/run/report-holder.pid")
    elif strategy == "temp_permission":
        shell(case_dir, "chown root:root /tmp/app-cache; chmod 0500 /tmp/app-cache")
    elif strategy == "tls_hostname":
        shell(case_dir, "cp /opt/opsbench/certs/legacy.crt /etc/opsbench/tls/server.crt; cp /opt/opsbench/certs/legacy.key /etc/opsbench/tls/server.key; chown demo:demo /etc/opsbench/tls/server.*; rm -f /opt/opsbench/certs/target.crt /opt/opsbench/certs/target.key /opt/opsbench/certs/legacy.crt /opt/opsbench/certs/legacy.key")
        app_restart(case_dir)
    elif strategy == "environment_override":
        shell(case_dir, "printf 'APP_PORT=8082\\n' >/etc/opsbench/app.env")
        app_restart(case_dir)
    else:
        raise RuntimeError(f"unsupported strategy: {strategy}")


def fault_state(case_dir: Path, data: dict[str, Any], active: bool) -> tuple[bool, dict[str, Any]]:
    strategy = data["strategy"]
    details: dict[str, Any] = {"strategy": strategy}
    if strategy == "cpu_runaway":
        value = _cpu_cores(case_dir)
        details["cpu_cores"] = value
        return ((value >= 0.20) if active else (value < 0.08)), details
    if strategy == "memory_growth":
        rss = _worker_rss_kib(case_dir)
        details["rss_kib"] = rss
        return ((rss >= 60000) if active else (rss == 0)), details
    if strategy == "fd_leak":
        count = _app_fd_count(case_dir)
        code = http_code(case_dir, "http://127.0.0.1:8080/fd-test")
        details.update(fd_count=count, http_status=code)
        return ((count >= 40) if active else (count < 25 and code == 200)), details
    if strategy == "disk_full":
        available = _integer_output(case_dir, "df -Pk /data | awk 'NR==2 {print $4}'")
        code = _large_upload_code(case_dir)
        details.update(available_kib=available, upload_status=code)
        return ((available <= 1024 and code != 201) if active else (available >= 4096 and code == 201)), details
    if strategy == "inode_full":
        free = _integer_output(case_dir, "df -Pi /data | awk 'NR==2 {print $4}'")
        result = shell(case_dir, "p=/data/inode-probe-$$; touch $p 2>/dev/null && rm -f $p", check=False)
        details.update(free_inodes=free, create_succeeded=result.returncode == 0)
        return ((result.returncode != 0) if active else (result.returncode == 0 and free >= 8)), details
    if strategy == "upload_permission":
        code = http_code(case_dir, "http://127.0.0.1:8080/upload", "POST", "probe")
        details["upload_status"] = code
        return ((code != 201) if active else (code == 201)), details
    if strategy == "wrong_port":
        expected = http_code(case_dir, "http://127.0.0.1:8080/health")
        alternate = http_code(case_dir, "http://127.0.0.1:8081/health")
        details.update(expected_port=expected, alternate_port=alternate)
        return ((expected == 0 and alternate == 200) if active else (expected == 200)), details
    if strategy == "loopback_bind":
        local = http_code(case_dir, "http://127.0.0.1:8080/health")
        network = http_code(case_dir, "http://target:8080/health")
        details.update(loopback_status=local, network_status=network)
        return ((local == 200 and network == 0) if active else (network == 200)), details
    if strategy == "malformed_config":
        valid = target(case_dir, ["python3", "-m", "json.tool", APP_CONFIG], check=False).returncode == 0
        running = target(case_dir, ["/opt/opsbench/runtime/appctl.sh", "status"], check=False).returncode == 0
        details.update(config_valid=valid, app_running=running)
        return ((not valid and not running) if active else (valid and running and wait_http(case_dir, "http://127.0.0.1:8080/health"))), details
    if strategy == "stale_pid":
        running = target(case_dir, ["/opt/opsbench/runtime/appctl.sh", "status"], check=False).returncode == 0
        pid_file = shell(case_dir, "test -e /run/demo-app.pid", check=False).returncode == 0
        details.update(app_running=running, pid_file=pid_file)
        return ((not running and pid_file) if active else (running and http_code(case_dir, "http://127.0.0.1:8080/health") == 200)), details
    if strategy == "dependency_timeout":
        started = time.monotonic()
        code = http_code(case_dir, "http://127.0.0.1:8080/orders")
        elapsed = time.monotonic() - started
        client_timeout_ms = _json_integer(case_dir, APP_CONFIG, "dependency_timeout_ms")
        dependency_delay_ms = _json_integer(case_dir, DEPENDENCY_CONFIG, "delay_ms")
        timeout_covers_delay = client_timeout_ms > dependency_delay_ms
        details.update(
            orders_status=code,
            elapsed_sec=round(elapsed, 3),
            client_timeout_ms=client_timeout_ms,
            dependency_delay_ms=dependency_delay_ms,
        )
        if active:
            return (code != 200 and not timeout_covers_delay), details
        return (code == 200 and timeout_covers_delay and elapsed < 2.0), details
    if strategy in {"dependency_dns", "dependency_port", "dependency_status", "dependency_payload"}:
        started = time.monotonic()
        code = http_code(case_dir, "http://127.0.0.1:8080/orders")
        elapsed = time.monotonic() - started
        details.update(orders_status=code, elapsed_sec=round(elapsed, 3))
        return ((code != 200) if active else (code == 200 and elapsed < 0.6)), details
    if strategy == "feature_flag":
        code = http_code(case_dir, "http://127.0.0.1:8080/checkout")
        details["checkout_status"] = code
        return ((code == 500) if active else (code == 200)), details
    if strategy == "file_lock":
        code = http_code(case_dir, "http://127.0.0.1:8080/report")
        holder = shell(case_dir, "test -s /run/report-holder.pid && kill -0 $(cat /run/report-holder.pid)", check=False).returncode == 0
        details.update(report_status=code, lock_holder=holder)
        return ((code == 503 and holder) if active else (code == 200 and not holder)), details
    if strategy == "temp_permission":
        code = http_code(case_dir, "http://127.0.0.1:8080/temp")
        details["temp_status"] = code
        return ((code == 500) if active else (code == 200)), details
    if strategy == "tls_hostname":
        verified = http_code(case_dir, "https://target:8443/health", cacert="/etc/opsbench/ca.crt")
        insecure = _insecure_tls_code(case_dir)
        details.update(verified_status=verified, insecure_status=insecure)
        return ((verified == 0 and insecure == 200) if active else (verified == 200)), details
    if strategy == "environment_override":
        expected = http_code(case_dir, "http://127.0.0.1:8080/health")
        alternate = http_code(case_dir, "http://127.0.0.1:8082/health")
        details.update(expected_port=expected, overridden_port=alternate)
        return ((expected == 0 and alternate == 200) if active else (expected == 200)), details
    raise RuntimeError(f"unsupported strategy: {strategy}")


def repair_for_smoke_test(case_dir: Path, data: dict[str, Any]) -> None:
    strategy = data["strategy"]
    if strategy in {"cpu_runaway", "memory_growth"}:
        shell(case_dir, "test ! -s /run/system-report.pid || kill $(cat /run/system-report.pid) 2>/dev/null || true; rm -f /run/system-report.pid")
    elif strategy == "fd_leak":
        set_json_value(case_dir, APP_CONFIG, "fd_leak", False); app_restart(case_dir)
    elif strategy == "disk_full":
        shell(case_dir, "pids=$(lsof -t +L1 2>/dev/null || true); test -z \"$pids\" || kill $pids 2>/dev/null || true; rm -f /run/storage-index.pid; sleep 0.2")
    elif strategy == "inode_full":
        shell(case_dir, "rm -rf /data/cache")
    elif strategy == "upload_permission":
        shell(case_dir, "chown demo:demo /data/uploads; chmod 0775 /data/uploads")
    elif strategy == "wrong_port":
        set_json_value(case_dir, APP_CONFIG, "port", 8080); app_restart(case_dir)
    elif strategy == "loopback_bind":
        set_json_value(case_dir, APP_CONFIG, "bind", "0.0.0.0"); app_restart(case_dir)
    elif strategy == "malformed_config":
        shell(case_dir, "sed -i 's/,}/}/' /etc/opsbench/app.json; rm -f /run/demo-app.pid"); app_start(case_dir)
    elif strategy == "stale_pid":
        shell(case_dir, "rm -f /run/demo-app.pid"); app_start(case_dir)
    elif strategy == "dependency_dns":
        set_json_value(case_dir, APP_CONFIG, "dependency_host", "127.0.0.1"); app_restart(case_dir)
    elif strategy == "dependency_port":
        set_json_value(case_dir, APP_CONFIG, "dependency_port", 9001); app_restart(case_dir)
    elif strategy == "dependency_status":
        shell(case_dir, "chown demo:demo /var/lib/catalog/catalog.json; chmod 0644 /var/lib/catalog/catalog.json")
    elif strategy == "dependency_payload":
        shell(case_dir, "printf '%s\\n' '{\"catalog\":\"ready\",\"items\":3}' >/var/lib/catalog/catalog.json; chown demo:demo /var/lib/catalog/catalog.json")
    elif strategy == "dependency_timeout":
        set_json_value(case_dir, APP_CONFIG, "dependency_timeout_ms", 1200); app_restart(case_dir)
    elif strategy == "feature_flag":
        set_json_value(case_dir, APP_CONFIG, "feature_checkout_v2", False)
    elif strategy == "file_lock":
        shell(case_dir, "pids=$(lsof -t /run/report.lock 2>/dev/null || true); test -z \"$pids\" || kill $pids 2>/dev/null || true; rm -f /run/report-holder.pid; sleep 0.2")
    elif strategy == "temp_permission":
        shell(case_dir, "chown demo:demo /tmp/app-cache; chmod 0775 /tmp/app-cache")
    elif strategy == "tls_hostname":
        shell(case_dir, "openssl req -newkey rsa:2048 -nodes -subj '/CN=target' -keyout /etc/opsbench/tls/server.key -out /tmp/target.csr >/dev/null 2>&1; printf 'subjectAltName=DNS:target\\nextendedKeyUsage=serverAuth\\n' >/tmp/target.ext; openssl x509 -req -days 365 -sha256 -in /tmp/target.csr -CA /opt/opsbench/certs/ca.crt -CAkey /opt/opsbench/certs/ca.key -CAcreateserial -extfile /tmp/target.ext -out /etc/opsbench/tls/server.crt >/dev/null 2>&1; chown demo:demo /etc/opsbench/tls/server.*; rm -f /tmp/target.csr /tmp/target.ext"); app_restart(case_dir)
    elif strategy == "environment_override":
        shell(case_dir, "rm -f /etc/opsbench/app.env"); app_restart(case_dir)
    else:
        raise RuntimeError(f"unsupported strategy: {strategy}")


def _worker_pid(case_dir: Path) -> int:
    result = shell(case_dir, "cat /run/system-report.pid 2>/dev/null", check=False)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _cpu_cores(case_dir: Path) -> float:
    pid = _worker_pid(case_dir)
    if not pid:
        return 0.0
    command = f"test -r /proc/{pid}/stat && awk '{{print $14+$15}}' /proc/{pid}/stat"
    first = _integer_output(case_dir, command)
    time.sleep(0.6)
    second = _integer_output(case_dir, command)
    ticks = max(_integer_output(case_dir, "getconf CLK_TCK"), 1)
    return max(0.0, (second - first) / ticks / 0.6)


def _worker_rss_kib(case_dir: Path) -> int:
    pid = _worker_pid(case_dir)
    return _integer_output(case_dir, f"awk '/VmRSS:/ {{print $2}}' /proc/{pid}/status") if pid else 0


def _app_fd_count(case_dir: Path) -> int:
    return _integer_output(case_dir, "pid=$(cat /run/demo-app.pid 2>/dev/null || true); test -n \"$pid\" && find /proc/$pid/fd -mindepth 1 -maxdepth 1 | wc -l || echo 0")


def _integer_output(case_dir: Path, command: str) -> int:
    result = shell(case_dir, command, check=False)
    try:
        return int(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def _json_integer(case_dir: Path, path: str, key: str) -> int:
    program = "import json,sys; print(int(json.load(open(sys.argv[1]))[sys.argv[2]]))"
    result = target(case_dir, ["python3", "-c", program, path, key], check=False)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _insecure_tls_code(case_dir: Path) -> int:
    result = target(case_dir, ["curl", "-ksS", "--max-time", "4", "-o", "/dev/null", "-w", "%{http_code}", "https://127.0.0.1:8443/health"], check=False)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _large_upload_code(case_dir: Path) -> int:
    result = shell(
        case_dir,
        "head -c 2097152 /dev/zero | curl -sS --max-time 6 -o /tmp/opsbench-upload-probe -w '%{http_code}' --data-binary @- http://127.0.0.1:8080/upload",
        timeout=10,
        check=False,
    )
    try:
        return int(result.stdout.strip()[-3:]) if result.returncode == 0 else 0
    except ValueError:
        return 0
