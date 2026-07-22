import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from opsbench.kubernetes_cluster import MinikubeClusterManager


class MinikubeClusterManagerTests(unittest.TestCase):
    def test_run_lock_serializes_shared_cluster_cases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = MinikubeClusterManager(temp_dir)
            second = MinikubeClusterManager(temp_dir)
            entered = []

            def contender():
                with second.run_lock(timeout=2):
                    entered.append("second")

            with first.run_lock(timeout=2):
                thread = threading.Thread(target=contender)
                thread.start()
                time.sleep(0.1)
                self.assertEqual(entered, [])
            thread.join(timeout=2)

            self.assertEqual(entered, ["second"])

    def test_ensure_starts_cluster_and_writes_dedicated_kubeconfig(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = MinikubeClusterManager(temp_dir, profile="opsbench-test")
            commands = []
            status = json.dumps(
                {"Host": "Stopped", "Kubelet": "Stopped", "APIServer": "Stopped"}
            )

            def fake_run(command, **kwargs):
                commands.append((command, kwargs))
                if command[1] == "status":
                    return subprocess.CompletedProcess(command, 0, status, "")
                if command[0] == "kubectl" and "view" in command:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        "apiVersion: v1\ncurrent-context: opsbench-test\n",
                        "",
                    )
                if command[0] == "helm":
                    manager.chart_archive.parent.mkdir(parents=True, exist_ok=True)
                    manager.chart_archive.write_bytes(b"chart")
                return subprocess.CompletedProcess(command, 0, "ok", "")

            with patch("opsbench.kubernetes_cluster.shutil.which", return_value="/bin/tool"), patch(
                "opsbench.kubernetes_cluster.subprocess.run", side_effect=fake_run
            ):
                kubeconfig = manager.ensure()

            self.assertEqual(kubeconfig, Path(temp_dir).resolve() / "kubeconfig")
            self.assertIn("current-context: opsbench-test", kubeconfig.read_text())
            start = next(command for command, _ in commands if command[1] == "start")
            self.assertIn("--driver=docker", start)
            self.assertIn("--listen-address=0.0.0.0", start)
            self.assertTrue(
                all(
                    kwargs["env"]["KUBECONFIG"] == str(kubeconfig)
                    for command, kwargs in commands
                    if command[0] == "minikube"
                )
            )

    def test_ensure_reuses_running_cluster(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = MinikubeClusterManager(temp_dir, profile="opsbench-test")
            commands = []
            running = json.dumps(
                {"Host": "Running", "Kubelet": "Running", "APIServer": "Running"}
            )
            manager.kubeconfig.write_text(
                "apiVersion: v1\ncurrent-context: opsbench-test\n", encoding="utf-8"
            )
            manager.chart_archive.parent.mkdir(parents=True)
            manager.chart_archive.write_bytes(b"chart")

            def fake_run(command, **kwargs):
                commands.append(command)
                if command[1] == "status":
                    return subprocess.CompletedProcess(command, 0, running, "")
                if command[0] == "kubectl" and "view" in command:
                    return subprocess.CompletedProcess(command, 0, "apiVersion: v1\n", "")
                return subprocess.CompletedProcess(command, 0, "ok", "")

            with patch("opsbench.kubernetes_cluster.shutil.which", return_value="/bin/tool"), patch(
                "opsbench.kubernetes_cluster.subprocess.run", side_effect=fake_run
            ):
                manager.ensure()

            self.assertFalse(any(command[1] == "start" for command in commands))

    def test_manager_ignores_default_user_kubeconfig(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = MinikubeClusterManager(temp_dir)
            with patch.dict(os.environ, {"KUBECONFIG": "/home/user/admin-config"}), patch(
                "opsbench.kubernetes_cluster.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    [],
                    0,
                    json.dumps(
                        {"Host": "Running", "Kubelet": "Running", "APIServer": "Running"}
                    ),
                    "",
                ),
            ) as run, patch("opsbench.kubernetes_cluster.shutil.which", return_value="/bin/minikube"):
                manager.status()

            self.assertEqual(run.call_args.kwargs["env"]["KUBECONFIG"], str(manager.kubeconfig))


if __name__ == "__main__":
    unittest.main()
