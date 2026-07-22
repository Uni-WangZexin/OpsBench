from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], env: dict[str, str], timeout: int = 180) -> None:
    result = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed ({' '.join(command)}):\n{result.stdout}\n{result.stderr}"
        )


def smoke(case_dir: Path) -> None:
    project = "opsbench_smoke_" + hashlib.sha1(case_dir.name.encode()).hexdigest()[:10]
    compose = ["docker", "compose", "-p", project, "-f", str(case_dir / "docker-compose.yaml")]
    env = os.environ.copy()
    env["OPSBENCH_COMPOSE_PROJECT"] = project
    trace_dir = Path("/tmp") / project
    trace_dir.mkdir(parents=True, exist_ok=True)
    env["OPSBENCH_AGENT_SOURCE"] = str(ROOT / "agents" / "langchain-react-agent")
    env["OPSBENCH_TASK_SOURCE"] = str(case_dir / "task.md")
    env["OPSBENCH_TRACE_DIR"] = str(trace_dir)
    agent_trace_dir = trace_dir / "agent"
    agent_trace_dir.mkdir(parents=True, exist_ok=True)
    env["OPSBENCH_AGENT_TRACE_DIR"] = str(agent_trace_dir)
    (trace_dir / "inject.log").write_text("benchmark-only sentinel\n", encoding="utf-8")
    tool_probe = """
from pathlib import Path
from opsbench.agent_tools import LINUX_OPERATIONS_TOOL_NAMES, ToolContext, create_tools
trace = Path('/tmp/operations-tool-smoke')
context = ToolContext(Path('/agent-runtime'), trace, tool_standard='linux-operations-v2')
tools = create_tools(context)
assert tuple(tools) == LINUX_OPERATIONS_TOOL_NAMES
pid = int(Path('/run/demo-app.pid').read_text())
checks = [
    tools['read_logs']('', '', 20),
    tools['inspect_processes']('python', 20),
    tools['inspect_sockets'](8080, True),
    tools['query_host_metrics'](pid, 0.1),
    tools['inspect_filesystem']('/data'),
    tools['probe_http']('http://127.0.0.1:8080/health', 'GET', '', 5, ''),
    tools['inspect_file']('/etc/opsbench/app.json', 1000),
    tools['manage_service']('demo-app', 'status'),
]
probe = Path('/tmp/opsbench-edit-probe')
probe.write_text('before')
checks.append(tools['edit_file'](str(probe), 'before', 'after'))
assert probe.read_text() == 'after'
assert all('returncode=0' in item or not item.startswith('$ ') for item in checks)
assert len(list(trace.glob('tool-*.log'))) >= 9
"""
    try:
        run([*compose, "up", "-d", "--build", "--wait"], env, timeout=300)
        run(
            [
                *compose,
                "exec",
                "-T",
                "target",
                "sh",
                "-c",
                "test \"$(hostname)\" = target && "
                "test -d /proc/$(cat /run/demo-app.pid) && "
                "test -x /agent/run.sh && test -f /task/task.md && "
                "test ! -e /trace/inject.log && "
                "python3 -c 'import agents.langchain_react_agent.agent' && "
                "! command -v sshpass >/dev/null",
            ],
            env,
        )
        run([*compose, "exec", "-T", "target", "python3", "-c", tool_probe], env)
        for phase in ["inject", "check_injected"]:
            run(
                [sys.executable, str(case_dir / "scripts" / f"{phase}.py"), "--case-dir", str(case_dir)],
                env,
            )
        repair = (
            "import sys; from pathlib import Path; "
            f"p=Path({str(case_dir)!r}).resolve(); "
            "sys.path.insert(0,str(p/'scripts')); "
            "from common import scenario; from faults import repair_for_smoke_test; "
            "repair_for_smoke_test(p, scenario(p)['implementation'])"
        )
        run([sys.executable, "-c", repair], env)
        run(
            [sys.executable, str(case_dir / "scripts" / "verify.py"), "--case-dir", str(case_dir)],
            env,
        )
        print(f"PASS {case_dir.name}", flush=True)
    finally:
        run([*compose, "down", "-v", "--remove-orphans"], env)
        shutil.rmtree(trace_dir, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="*")
    args = parser.parse_args()
    if args.cases:
        case_dirs = [(ROOT / item).resolve() for item in args.cases]
    else:
        case_dirs = sorted(
            path
            for path in (ROOT / "cases").iterdir()
            if path.is_dir()
            and (path / "manifest.yaml").is_file()
            and re.search(r"-(?:00[2-9]|01[0-9]|02[01])$", path.name)
        )
    for case_dir in case_dirs:
        smoke(case_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
