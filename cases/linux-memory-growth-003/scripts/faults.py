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
CONTROL_PLANE_CONFIG = "/var/lib/opsbench/control/current"
APP_CONFIG_OVERLAY = "/var/lib/opsbench/app-config/current"
UPLOAD_STORE = "/data/.stores/upload-primary"
TEMP_STORE = "/var/cache/demo/jobs"


def inject_fault(case_dir: Path, data: dict[str, Any]) -> None:
    strategy = data["strategy"]
    if strategy == "cpu_runaway":
        command = (
            "touch /run/system-report.enabled; "
            "nohup sh -c 'while test -e /run/system-report.enabled; do "
            "REPORT_PROFILE=compute python3 /opt/opsbench/runtime/workload.pyc; "
            "sleep 0.1; done' >/var/log/demo/system-report.log 2>&1 </dev/null & "
            "echo $! >/run/system-report-supervisor.pid"
        )
        shell(case_dir, command)
        time.sleep(0.5)
    elif strategy == "memory_growth":
        shell(
            case_dir,
            "REPORT_PROFILE=retention nohup python3 /opt/opsbench/runtime/workload.pyc "
            ">/var/log/demo/system-report.log 2>&1 </dev/null & "
            "echo $! >/run/system-report.pid",
        )
        time.sleep(2.0)
    elif strategy == "fd_leak":
        set_json_value(case_dir, APP_CONFIG, "template_cache_scope", "process")
        app_restart(case_dir)
        for _ in range(48):
            http_code(case_dir, "http://127.0.0.1:8080/report-template")
    elif strategy == "disk_full":
        shell(case_dir, "REPORT_PROFILE=storage nohup python3 /opt/opsbench/runtime/workload.pyc >/var/log/demo/storage-index.log 2>&1 </dev/null & echo $! >/run/storage-index.pid")
        time.sleep(1.0)
    elif strategy == "inode_full":
        shell(case_dir, "mkdir -p /data/cache; i=0; while touch /data/cache/item-$i 2>/dev/null; do i=$((i+1)); done; true")
    elif strategy == "upload_permission":
        shell(case_dir, f"chown root:root {UPLOAD_STORE}; chmod 2750 {UPLOAD_STORE}")
    elif strategy == "wrong_port":
        set_json_value(case_dir, CONTROL_PLANE_CONFIG, "listener_port", 8081)
        if not wait_http(case_dir, "http://127.0.0.1:8081/health"):
            raise RuntimeError("listener policy was not reconciled to port 8081")
    elif strategy == "loopback_bind":
        shell(
            case_dir,
            "ip=$(hostname -i | awk '{print $1}'); "
            "iptables -I OUTPUT 1 -d \"$ip\" -p tcp --dport 8080 "
            "-m comment --comment opsbench-peer-block -j REJECT",
        )
    elif strategy == "malformed_config":
        app_stop(case_dir)
        shell(case_dir, f"printf '%s\\n' '{{\"tls_enabled\": tru' >{APP_CONFIG_OVERLAY}")
        app_start(case_dir, check=False)
    elif strategy == "stale_pid":
        app_stop(case_dir)
        shell(case_dir, "printf '999999\\n' >/run/demo-app.pid")
    elif strategy == "dependency_dns":
        shell(
            case_dir,
            "sed '/[[:space:]]catalog\\.internal$/d' /etc/hosts >/tmp/opsbench-hosts; "
            "cat /tmp/opsbench-hosts >/etc/hosts; "
            "printf '%s\\n' '192.0.2.77 catalog.internal' >>/etc/hosts",
        )
    elif strategy == "dependency_port":
        shell(
            case_dir,
            "printf 'CATALOG_PORT=9002\\n' >/etc/opsbench/dependency.env; "
            "/opt/opsbench/runtime/dependencyctl.sh restart",
        )
    elif strategy == "dependency_status":
        shell(case_dir, "chown root:root /var/lib/catalog/catalog.json; chmod 0000 /var/lib/catalog/catalog.json")
    elif strategy == "dependency_payload":
        shell(case_dir, "printf '%s\\n' '{\"catalog\":{\"state\":\"ready\"},\"items\":\"3\"}' >/var/lib/catalog/catalog.json; chown demo:demo /var/lib/catalog/catalog.json")
    elif strategy == "dependency_timeout":
        set_json_value(case_dir, DEPENDENCY_CONFIG, "delay_ms", 900)
        set_json_value(case_dir, APP_CONFIG, "dependency_timeout_ms", 150)
        app_restart(case_dir)
    elif strategy == "feature_flag":
        set_json_value(case_dir, CONTROL_PLANE_CONFIG, "feature_checkout_v2", True)
        time.sleep(1.0)
    elif strategy == "file_lock":
        shell(
            case_dir,
            "touch /run/report.lock /run/report-worker.enabled; "
            "chown demo:demo /run/report.lock; "
            "nohup sh -c 'while test -e /run/report-worker.enabled; do "
            "flock /run/report.lock sleep 3600; sleep 0.1; done' "
            ">/var/log/demo/report-worker.log 2>&1 </dev/null & "
            "echo $! >/run/report-supervisor.pid; sleep 0.3",
        )
    elif strategy == "temp_permission":
        shell(case_dir, f"chown root:root {TEMP_STORE}; chmod 3550 {TEMP_STORE}")
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
        workers = _workload_pids(case_dir)
        supervisors = _process_pids_containing(case_dir, "/run/system-report.enabled")
        enabled = shell(case_dir, "test -e /run/system-report.enabled", check=False).returncode == 0
        details.update(
            cpu_cores=value,
            worker_pids=workers,
            supervisor_pids=supervisors,
            restart_enabled=enabled,
        )
        if active:
            return (value >= 0.20 and bool(workers) and bool(supervisors) and enabled), details
        return (value < 0.08 and not workers and not supervisors and not enabled), details
    if strategy == "memory_growth":
        rss = _worker_rss_kib(case_dir)
        details.update(rss_kib=rss, worker_pids=_workload_pids(case_dir))
        return ((rss >= 60000) if active else (rss == 0)), details
    if strategy == "fd_leak":
        before, after, code = _report_template_probe(case_dir)
        details.update(
            fd_count_before=before,
            fd_count_after=after,
            fd_growth=after - before,
            report_template_status=code,
        )
        if active:
            return (after >= 40), details
        return (after < 25 and after - before <= 1 and code == 200), details
    if strategy == "disk_full":
        available = _integer_output(case_dir, "df -Pk /data | awk 'NR==2 {print $4}'")
        code = _large_upload_code(case_dir)
        worker_pids = _workload_pids(case_dir)
        details.update(
            available_kib=available,
            upload_status=code,
            storage_worker_pids=worker_pids,
        )
        if active:
            return (available <= 1024 and code != 201 and bool(worker_pids)), details
        return (available >= 4096 and code == 201 and not worker_pids), details
    if strategy == "inode_full":
        free = _integer_output(case_dir, "df -Pi /data | awk 'NR==2 {print $4}'")
        result = shell(case_dir, "p=/data/inode-probe-$$; touch $p 2>/dev/null && rm -f $p", check=False)
        details.update(free_inodes=free, create_succeeded=result.returncode == 0)
        return ((result.returncode != 0) if active else (result.returncode == 0 and free >= 8)), details
    if strategy == "upload_permission":
        code = http_code(case_dir, "http://127.0.0.1:8080/upload", "POST", "probe")
        mode = _integer_output(case_dir, f"stat -c %a {UPLOAD_STORE}")
        owner = _text_output(case_dir, f"stat -c %U:%G {UPLOAD_STORE}")
        resolved = _text_output(case_dir, "readlink -f /data/uploads")
        is_link = shell(case_dir, "test -L /data/uploads", check=False).returncode == 0
        details.update(
            upload_status=code,
            store_mode=mode,
            store_owner=owner,
            resolved_upload_dir=resolved,
            upload_dir_is_symlink=is_link,
        )
        if active:
            return (code != 201 and (mode != 2770 or owner != "root:demo")), details
        return (
            code == 201
            and mode == 2770
            and owner == "root:demo"
            and resolved == UPLOAD_STORE
            and is_link
        ), details
    if strategy == "wrong_port":
        expected = http_code(case_dir, "http://127.0.0.1:8080/health")
        alternate = http_code(case_dir, "http://127.0.0.1:8081/health")
        configured_port = _json_integer(case_dir, APP_CONFIG, "port")
        policy_port = _json_integer(case_dir, CONTROL_PLANE_CONFIG, "listener_port")
        reconcilers = _process_pids_containing(case_dir, "config-reconciler.pyc")
        details.update(
            expected_port=expected,
            alternate_port=alternate,
            configured_port=configured_port,
            policy_port=policy_port,
            reconciler_pids=reconcilers,
        )
        if active:
            return (
                expected == 0
                and alternate == 200
                and configured_port == 8081
                and policy_port == 8081
                and bool(reconcilers)
            ), details
        return (
            expected == 200
            and alternate == 0
            and configured_port == 8080
            and policy_port == 8080
            and bool(reconcilers)
        ), details
    if strategy == "loopback_bind":
        local = http_code(case_dir, "http://127.0.0.1:8080/health")
        network = http_code(case_dir, "http://target:8080/health")
        rule = _peer_block_rule_present(case_dir)
        bind = _text_output(case_dir, f"python3 -c 'import json; print(json.load(open(\"{APP_CONFIG}\"))[\"bind\"])'")
        details.update(loopback_status=local, network_status=network, peer_block_rule=rule, configured_bind=bind)
        if active:
            return (local == 200 and network == 0 and rule and bind == "0.0.0.0"), details
        return (network == 200 and not rule and bind == "0.0.0.0"), details
    if strategy == "malformed_config":
        base_valid = target(case_dir, ["python3", "-m", "json.tool", APP_CONFIG], check=False).returncode == 0
        overlay_valid = target(case_dir, ["python3", "-m", "json.tool", APP_CONFIG_OVERLAY], check=False).returncode == 0
        running = target(case_dir, ["/opt/opsbench/runtime/appctl.sh", "status"], check=False).returncode == 0
        details.update(base_config_valid=base_valid, release_overlay_valid=overlay_valid, app_running=running)
        if active:
            return (base_valid and not overlay_valid and not running), details
        return (base_valid and overlay_valid and running and wait_http(case_dir, "http://127.0.0.1:8080/health")), details
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
        return (
            code == 200
            and timeout_covers_delay
            and dependency_delay_ms <= 250
            and elapsed < 0.6
        ), details
    if strategy == "dependency_status":
        started = time.monotonic()
        code = http_code(case_dir, "http://127.0.0.1:8080/orders")
        elapsed = time.monotonic() - started
        mode = _integer_output(case_dir, "stat -c %a /var/lib/catalog/catalog.json")
        owner = _text_output(case_dir, "stat -c %U:%G /var/lib/catalog/catalog.json")
        details.update(
            orders_status=code,
            elapsed_sec=round(elapsed, 3),
            catalog_mode=mode,
            catalog_owner=owner,
        )
        if active:
            return (code != 200), details
        return (code == 200 and elapsed < 0.6 and mode in {600, 640} and owner == "demo:demo"), details
    if strategy == "dependency_dns":
        started = time.monotonic()
        code = http_code(case_dir, "http://127.0.0.1:8080/orders")
        elapsed = time.monotonic() - started
        configured_host = _json_string(case_dir, APP_CONFIG, "dependency_host")
        resolved_host = _text_output(
            case_dir,
            "getent ahostsv4 catalog.internal | awk 'NR==1 {print $1}'",
        )
        details.update(
            orders_status=code,
            elapsed_sec=round(elapsed, 3),
            configured_host=configured_host,
            resolved_host=resolved_host,
        )
        if active:
            return (code != 200 and configured_host == "catalog.internal" and resolved_host == "192.0.2.77"), details
        return (code == 200 and elapsed < 0.6 and configured_host == "catalog.internal" and resolved_host == "127.0.0.1"), details
    if strategy == "dependency_port":
        code = http_code(case_dir, "http://127.0.0.1:8080/orders")
        expected = http_code(case_dir, "http://127.0.0.1:9001/catalog")
        drifted = http_code(case_dir, "http://127.0.0.1:9002/catalog")
        configured_port = _json_integer(case_dir, APP_CONFIG, "dependency_port")
        override = _text_output(case_dir, "sed -n 's/^CATALOG_PORT=//p' /etc/opsbench/dependency.env 2>/dev/null")
        details.update(
            orders_status=code,
            expected_dependency_status=expected,
            drifted_dependency_status=drifted,
            configured_dependency_port=configured_port,
            dependency_port_override=override,
        )
        if active:
            return (code != 200 and expected == 0 and drifted == 200 and configured_port == 9001 and override == "9002"), details
        return (code == 200 and expected == 200 and drifted == 0 and configured_port == 9001 and override == ""), details
    if strategy == "dependency_payload":
        started = time.monotonic()
        code = http_code(case_dir, "http://127.0.0.1:8080/orders")
        elapsed = time.monotonic() - started
        details.update(orders_status=code, elapsed_sec=round(elapsed, 3))
        return ((code != 200) if active else (code == 200 and elapsed < 0.6)), details
    if strategy == "feature_flag":
        code = http_code(case_dir, "http://127.0.0.1:8080/checkout")
        configured = _json_boolean(case_dir, APP_CONFIG, "feature_checkout_v2")
        desired = _json_boolean(case_dir, CONTROL_PLANE_CONFIG, "feature_checkout_v2")
        reconcilers = _process_pids_containing(case_dir, "config-reconciler.pyc")
        details.update(
            checkout_status=code,
            configured_flag=configured,
            desired_flag=desired,
            reconciler_pids=reconcilers,
        )
        if active:
            return (code == 500 and configured and desired and bool(reconcilers)), details
        return (code == 200 and not configured and not desired and bool(reconcilers)), details
    if strategy == "file_lock":
        first = http_code(case_dir, "http://127.0.0.1:8080/report")
        time.sleep(0.5)
        second = http_code(case_dir, "http://127.0.0.1:8080/report")
        holders = _lock_holder_pids(case_dir)
        supervisors = _process_pids_containing(case_dir, "/run/report-worker.enabled")
        enabled = shell(case_dir, "test -e /run/report-worker.enabled", check=False).returncode == 0
        details.update(
            report_statuses=[first, second],
            lock_holder_pids=holders,
            supervisor_pids=supervisors,
            restart_enabled=enabled,
        )
        if active:
            return (first == 503 and second == 503 and bool(holders) and bool(supervisors) and enabled), details
        return (first == 200 and second == 200 and not holders and not supervisors and not enabled), details
    if strategy == "temp_permission":
        code = http_code(case_dir, "http://127.0.0.1:8080/temp")
        mode = _integer_output(case_dir, f"stat -c %a {TEMP_STORE}")
        owner = _text_output(case_dir, f"stat -c %U:%G {TEMP_STORE}")
        resolved = _text_output(case_dir, "readlink -f /tmp/app-cache")
        is_link = shell(case_dir, "test -L /tmp/app-cache", check=False).returncode == 0
        details.update(
            temp_status=code,
            store_mode=mode,
            store_owner=owner,
            resolved_temp_dir=resolved,
            temp_dir_is_symlink=is_link,
        )
        if active:
            return (code == 500 and (mode != 3770 or owner != "root:demo")), details
        return (
            code == 200
            and mode == 3770
            and owner == "root:demo"
            and resolved == TEMP_STORE
            and is_link
        ), details
    if strategy == "tls_hostname":
        verified = http_code(case_dir, "https://target:8443/health", cacert="/etc/opsbench/ca.crt")
        insecure = _insecure_tls_code(case_dir)
        details.update(verified_status=verified, insecure_status=insecure)
        return ((verified == 0 and insecure == 200) if active else (verified == 200)), details
    if strategy == "environment_override":
        expected = http_code(case_dir, "http://127.0.0.1:8080/health")
        alternate = http_code(case_dir, "http://127.0.0.1:8082/health")
        override_present = shell(case_dir, "test -e /etc/opsbench/app.env", check=False).returncode == 0
        details.update(
            expected_port=expected,
            overridden_port=alternate,
            override_present=override_present,
        )
        if active:
            return (expected == 0 and alternate == 200 and override_present), details
        return (expected == 200 and alternate == 0 and not override_present), details
    raise RuntimeError(f"unsupported strategy: {strategy}")


def repair_for_smoke_test(case_dir: Path, data: dict[str, Any]) -> None:
    strategy = data["strategy"]
    if strategy == "cpu_runaway":
        shell(case_dir, "rm -f /run/system-report.enabled")
        pids = sorted(set(_workload_pids(case_dir) + _process_pids_containing(case_dir, "/run/system-report.enabled")))
        if pids:
            shell(case_dir, "kill " + " ".join(str(pid) for pid in pids) + " 2>/dev/null || true")
        shell(case_dir, "rm -f /run/system-report-supervisor.pid /run/system-report.pid; sleep 0.2")
    elif strategy == "memory_growth":
        pids = _workload_pids(case_dir)
        if pids:
            shell(case_dir, "kill " + " ".join(str(pid) for pid in pids) + " 2>/dev/null || true")
        shell(case_dir, "rm -f /run/system-report.pid")
    elif strategy == "fd_leak":
        set_json_value(case_dir, APP_CONFIG, "template_cache_scope", "request"); app_restart(case_dir)
    elif strategy == "disk_full":
        shell(case_dir, "pids=$(lsof -t +L1 2>/dev/null || true); test -z \"$pids\" || kill $pids 2>/dev/null || true; rm -f /run/storage-index.pid; sleep 0.2")
    elif strategy == "inode_full":
        shell(case_dir, "rm -rf /data/cache")
    elif strategy == "upload_permission":
        shell(case_dir, f"chown root:demo {UPLOAD_STORE}; chmod 2770 {UPLOAD_STORE}")
    elif strategy == "wrong_port":
        set_json_value(case_dir, CONTROL_PLANE_CONFIG, "listener_port", 8080)
        if not wait_http(case_dir, "http://127.0.0.1:8080/health"):
            raise RuntimeError("listener policy did not reconcile back to port 8080")
    elif strategy == "loopback_bind":
        shell(case_dir, "ip=$(hostname -i | awk '{print $1}'); iptables -D OUTPUT -d \"$ip\" -p tcp --dport 8080 -m comment --comment opsbench-peer-block -j REJECT")
    elif strategy == "malformed_config":
        shell(case_dir, f"printf '%s\\n' '{{}}' >{APP_CONFIG_OVERLAY}; rm -f /run/demo-app.pid"); app_start(case_dir)
    elif strategy == "stale_pid":
        shell(case_dir, "rm -f /run/demo-app.pid"); app_start(case_dir)
    elif strategy == "dependency_dns":
        shell(case_dir, "sed '/[[:space:]]catalog\\.internal$/d' /etc/hosts >/tmp/opsbench-hosts; cat /tmp/opsbench-hosts >/etc/hosts; printf '%s\\n' '127.0.0.1 catalog.internal' >>/etc/hosts")
        set_json_value(case_dir, APP_CONFIG, "dependency_host", "catalog.internal")
    elif strategy == "dependency_port":
        shell(case_dir, "rm -f /etc/opsbench/dependency.env; /opt/opsbench/runtime/dependencyctl.sh restart")
        set_json_value(case_dir, APP_CONFIG, "dependency_port", 9001)
    elif strategy == "dependency_status":
        shell(case_dir, "chown demo:demo /var/lib/catalog/catalog.json; chmod 0640 /var/lib/catalog/catalog.json")
    elif strategy == "dependency_payload":
        shell(case_dir, "printf '%s\\n' '{\"catalog\":\"ready\",\"items\":3}' >/var/lib/catalog/catalog.json; chown demo:demo /var/lib/catalog/catalog.json")
    elif strategy == "dependency_timeout":
        set_json_value(case_dir, DEPENDENCY_CONFIG, "delay_ms", 20)
        set_json_value(case_dir, APP_CONFIG, "dependency_timeout_ms", 500); app_restart(case_dir)
    elif strategy == "feature_flag":
        set_json_value(case_dir, CONTROL_PLANE_CONFIG, "feature_checkout_v2", False)
        time.sleep(1.0)
    elif strategy == "file_lock":
        shell(case_dir, "rm -f /run/report-worker.enabled")
        pids = sorted(set(_lock_holder_pids(case_dir) + _process_pids_containing(case_dir, "/run/report-worker.enabled")))
        if pids:
            shell(case_dir, "kill " + " ".join(str(pid) for pid in pids) + " 2>/dev/null || true")
        shell(case_dir, "rm -f /run/report-supervisor.pid /run/report-holder.pid; sleep 0.3")
    elif strategy == "temp_permission":
        shell(case_dir, f"chown root:demo {TEMP_STORE}; chmod 3770 {TEMP_STORE}")
    elif strategy == "tls_hostname":
        shell(case_dir, "openssl req -newkey rsa:2048 -nodes -subj '/CN=target' -keyout /etc/opsbench/tls/server.key -out /tmp/target.csr >/dev/null 2>&1; printf 'subjectAltName=DNS:target\\nextendedKeyUsage=serverAuth\\n' >/tmp/target.ext; openssl x509 -req -days 365 -sha256 -in /tmp/target.csr -CA /opt/opsbench/certs/ca.crt -CAkey /opt/opsbench/certs/ca.key -CAcreateserial -extfile /tmp/target.ext -out /etc/opsbench/tls/server.crt >/dev/null 2>&1; chown demo:demo /etc/opsbench/tls/server.*; rm -f /tmp/target.csr /tmp/target.ext"); app_restart(case_dir)
    elif strategy == "environment_override":
        shell(case_dir, "rm -f /etc/opsbench/app.env"); app_restart(case_dir)
    else:
        raise RuntimeError(f"unsupported strategy: {strategy}")


def _workload_pids(case_dir: Path) -> list[int]:
    program = """
import pathlib

pids = []
for proc in pathlib.Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    try:
        argv = [part.decode(errors='replace') for part in proc.joinpath('cmdline').read_bytes().split(b'\\0') if part]
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if argv == ['python3', '/opt/opsbench/runtime/workload.pyc']:
        pids.append(int(proc.name))
print(' '.join(str(pid) for pid in sorted(pids)))
"""
    result = target(case_dir, ["python3", "-c", program], check=False)
    return [int(value) for value in result.stdout.split() if value.isdigit()]


def _process_pids_containing(case_dir: Path, needle: str) -> list[int]:
    program = """
import os, pathlib, sys

needle = sys.argv[1]
pids = []
for proc in pathlib.Path('/proc').iterdir():
    if not proc.name.isdigit():
        continue
    if int(proc.name) == os.getpid():
        continue
    try:
        command = proc.joinpath('cmdline').read_bytes().replace(b'\\0', b' ').decode(errors='replace')
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    if needle in command:
        pids.append(int(proc.name))
print(' '.join(str(pid) for pid in sorted(pids)))
"""
    result = target(case_dir, ["python3", "-c", program, needle], check=False)
    return [int(value) for value in result.stdout.split() if value.isdigit()]


def _lock_holder_pids(case_dir: Path) -> list[int]:
    result = shell(case_dir, "lsof -t /run/report.lock 2>/dev/null || true", check=False)
    return [int(value) for value in result.stdout.split() if value.isdigit()]


def _process_cpu_ticks(case_dir: Path, pids: list[int]) -> int:
    if not pids:
        return 0
    program = """
import pathlib, sys

total = 0
for value in sys.argv[1:]:
    try:
        fields = pathlib.Path('/proc', value, 'stat').read_text().split()
        total += int(fields[13]) + int(fields[14])
    except (FileNotFoundError, ProcessLookupError):
        pass
print(total)
"""
    result = target(
        case_dir,
        ["python3", "-c", program, *[str(pid) for pid in pids]],
        check=False,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _cpu_cores(case_dir: Path) -> float:
    pids = _workload_pids(case_dir)
    if not pids:
        return 0.0
    first = _process_cpu_ticks(case_dir, pids)
    time.sleep(0.6)
    second = _process_cpu_ticks(case_dir, pids)
    ticks = max(_integer_output(case_dir, "getconf CLK_TCK"), 1)
    return max(0.0, (second - first) / ticks / 0.6)


def _worker_rss_kib(case_dir: Path) -> int:
    total = 0
    for pid in _workload_pids(case_dir):
        total += _integer_output(
            case_dir,
            f"awk '/VmRSS:/ {{print $2}}' /proc/{pid}/status",
        )
    return total


def _app_fd_count(case_dir: Path) -> int:
    return _integer_output(case_dir, "pid=$(cat /run/demo-app.pid 2>/dev/null || true); test -n \"$pid\" && find /proc/$pid/fd -mindepth 1 -maxdepth 1 | wc -l || echo 0")


def _report_template_probe(case_dir: Path) -> tuple[int, int, int]:
    before = _app_fd_count(case_dir)
    code = 0
    for _ in range(8):
        code = http_code(case_dir, "http://127.0.0.1:8080/report-template")
    after = _app_fd_count(case_dir)
    return before, after, code


def _integer_output(case_dir: Path, command: str) -> int:
    result = shell(case_dir, command, check=False)
    try:
        return int(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def _text_output(case_dir: Path, command: str) -> str:
    return shell(case_dir, command, check=False).stdout.strip()


def _json_integer(case_dir: Path, path: str, key: str) -> int:
    program = "import json,sys; print(int(json.load(open(sys.argv[1]))[sys.argv[2]]))"
    result = target(case_dir, ["python3", "-c", program, path, key], check=False)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _json_string(case_dir: Path, path: str, key: str) -> str:
    program = "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]])"
    result = target(case_dir, ["python3", "-c", program, path, key], check=False)
    return result.stdout.strip()


def _json_boolean(case_dir: Path, path: str, key: str) -> bool:
    program = "import json,sys; print('true' if json.load(open(sys.argv[1]))[sys.argv[2]] else 'false')"
    result = target(case_dir, ["python3", "-c", program, path, key], check=False)
    return result.stdout.strip() == "true"


def _peer_block_rule_present(case_dir: Path) -> bool:
    result = shell(
        case_dir,
        "ip=$(hostname -i | awk '{print $1}'); "
        "iptables -C OUTPUT -d \"$ip\" -p tcp --dport 8080 "
        "-m comment --comment opsbench-peer-block -j REJECT",
        check=False,
    )
    return result.returncode == 0


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
