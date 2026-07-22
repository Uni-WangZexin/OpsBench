from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fcntl


class KubernetesClusterError(RuntimeError):
    """Raised when the benchmark-managed Kubernetes cluster is unavailable."""


@dataclass(frozen=True)
class ClusterStatus:
    profile: str
    running: bool
    kubeconfig: Path
    details: dict[str, Any]


class MinikubeClusterManager:
    """Own a reusable Docker-backed Minikube cluster for Kubernetes cases."""

    def __init__(
        self,
        runtime_dir: str | Path | None = None,
        profile: str | None = None,
    ) -> None:
        project_root = Path(__file__).resolve().parents[1]
        self.runtime_dir = Path(
            runtime_dir or project_root / "runtime" / "kubernetes"
        ).resolve()
        self.profile = profile or os.environ.get("OPSBENCH_MINIKUBE_PROFILE", "opsbench")
        self.kubeconfig = self.runtime_dir / "kubeconfig"

    @property
    def chart_archive(self) -> Path:
        version = os.environ.get("OPSBENCH_OTEL_CHART_VERSION", "0.11.0")
        return self.runtime_dir / "charts" / f"opentelemetry-demo-{version}.tgz"

    @contextmanager
    def run_lock(self, timeout: int = 1800):
        """Serialize cases that share the single benchmark Minikube node."""

        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        lock_path = self.runtime_dir / "case-run.lock"
        with lock_path.open("a+", encoding="utf-8") as handle:
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise KubernetesClusterError(
                            "timed out waiting for another Kubernetes case to finish"
                        )
                    time.sleep(1)
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()}\nprofile={self.profile}\n")
            handle.flush()
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def ensure(self) -> Path:
        self._require_command("docker")
        self._require_command("minikube")
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

        status = self.status()
        if not status.running or not self.kubeconfig.is_file():
            self._run(
                [
                    "minikube",
                    "start",
                    "-p",
                    self.profile,
                    "--driver=docker",
                    f"--cpus={os.environ.get('OPSBENCH_MINIKUBE_CPUS', '4')}",
                    f"--memory={os.environ.get('OPSBENCH_MINIKUBE_MEMORY_MB', '7800')}",
                    "--kubernetes-version="
                    f"{os.environ.get('OPSBENCH_KUBERNETES_VERSION', 'v1.30.0')}",
                    "--embed-certs",
                    "--listen-address=0.0.0.0",
                    "--keep-context",
                ],
                timeout=900,
                action="start benchmark Minikube cluster",
            )

        self._run(
            [
                "kubectl",
                "--kubeconfig",
                str(self.kubeconfig),
                "config",
                "use-context",
                self.profile,
            ],
            timeout=60,
            action="select benchmark Kubernetes context",
            inherit_kubeconfig=False,
        )
        exported = self._run(
            [
                "kubectl",
                "--kubeconfig",
                str(self.kubeconfig),
                "config",
                "view",
                "--raw",
                "--flatten",
            ],
            timeout=60,
            action="export benchmark kubeconfig",
            inherit_kubeconfig=False,
        )
        self.kubeconfig.write_text(exported.stdout, encoding="utf-8")
        self.kubeconfig.chmod(0o600)
        self._run(
            [
                "kubectl",
                "--kubeconfig",
                str(self.kubeconfig),
                "wait",
                "--for=condition=Ready",
                "node",
                "--all",
                "--timeout=180s",
            ],
            timeout=210,
            action="wait for benchmark Kubernetes node",
            inherit_kubeconfig=False,
        )
        self.ensure_chart()
        return self.kubeconfig

    def ensure_chart(self) -> Path:
        if self.chart_archive.is_file():
            return self.chart_archive
        self._require_command("helm")
        self.chart_archive.parent.mkdir(parents=True, exist_ok=True)
        version = os.environ.get("OPSBENCH_OTEL_CHART_VERSION", "0.11.0")
        last_error: KubernetesClusterError | None = None
        for attempt in range(1, 4):
            try:
                self._run(
                    [
                        "helm",
                        "pull",
                        "opentelemetry-demo",
                        "--repo",
                        "https://open-telemetry.github.io/opentelemetry-helm-charts",
                        "--version",
                        version,
                        "--destination",
                        str(self.chart_archive.parent),
                    ],
                    timeout=180,
                    action=f"download OpenTelemetry Demo chart (attempt {attempt}/3)",
                )
                if not self.chart_archive.is_file():
                    raise KubernetesClusterError(
                        f"helm did not create expected chart archive: {self.chart_archive}"
                    )
                return self.chart_archive
            except KubernetesClusterError as exc:
                last_error = exc
                if attempt < 3:
                    time.sleep(attempt * 2)
        assert last_error is not None
        raise last_error

    def status(self) -> ClusterStatus:
        if not shutil.which("minikube"):
            return ClusterStatus(self.profile, False, self.kubeconfig, {"error": "minikube not found"})
        completed = subprocess.run(
            ["minikube", "status", "-p", self.profile, "-o", "json"],
            env=self._environment(),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        try:
            details = json.loads(completed.stdout) if completed.stdout.strip() else {}
        except json.JSONDecodeError:
            details = {"stdout": completed.stdout.strip()}
        if completed.stderr.strip():
            details["stderr"] = completed.stderr.strip()
        running = completed.returncode == 0 and self._components_running(details)
        return ClusterStatus(self.profile, running, self.kubeconfig, details)

    def delete(self) -> None:
        self._require_command("minikube")
        self._run(
            ["minikube", "delete", "-p", self.profile],
            timeout=300,
            action="delete benchmark Minikube cluster",
        )
        self.kubeconfig.unlink(missing_ok=True)

    def _run(
        self,
        command: list[str],
        timeout: int,
        action: str,
        inherit_kubeconfig: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        environment = self._environment() if inherit_kubeconfig else os.environ.copy()
        completed = subprocess.run(
            command,
            env=environment,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
            raise KubernetesClusterError(f"{action} failed: {detail}")
        return completed

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment["KUBECONFIG"] = str(self.kubeconfig)
        return environment

    @staticmethod
    def _components_running(details: dict[str, Any]) -> bool:
        component = details.get("APIServer") or details.get("apiserver")
        host = details.get("Host") or details.get("host")
        kubelet = details.get("Kubelet") or details.get("kubelet")
        return all(str(value).lower() == "running" for value in (host, kubelet, component))

    @staticmethod
    def _require_command(command: str) -> None:
        if not shutil.which(command):
            raise KubernetesClusterError(
                f"{command} is required for benchmark-managed Kubernetes"
            )
