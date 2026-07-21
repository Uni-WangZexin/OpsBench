import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from opsbench.cases import load_case
from opsbench.runner import _agent_container_cmd


ROOT = Path(__file__).resolve().parents[1]


def load_kubernetes_common():
    path = ROOT / "cases" / "_kubernetes_otel" / "scripts" / "common.py"
    spec = importlib.util.spec_from_file_location("kubernetes_case_common", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class KubernetesCaseTests(unittest.TestCase):
    def test_restricted_kubeconfig_is_namespace_scoped_and_uses_short_lived_token(self):
        common = load_kubernetes_common()
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "agent-kubeconfig.json"
            source_config = {
                "current-context": "admin",
                "contexts": [
                    {"name": "admin", "context": {"cluster": "target", "user": "admin"}}
                ],
                "clusters": [
                    {
                        "name": "target",
                        "cluster": {
                            "server": "https://cluster.example:6443",
                            "certificate-authority-data": "Y2E=",
                        },
                    }
                ],
            }
            responses = iter(
                [
                    subprocess.CompletedProcess([], 0, "short-lived-token\n", ""),
                    subprocess.CompletedProcess([], 0, json.dumps(source_config), ""),
                ]
            )
            env = {
                "OPSBENCH_NAMESPACE": "ops-tci061-test",
                "OPSBENCH_AGENT_KUBECONFIG": str(output),
            }
            applied_manifests = []

            def fake_apply(command, **kwargs):
                applied_manifests.append(json.loads(kwargs["input"]))
                return subprocess.CompletedProcess(command, 0, "applied", "")

            with patch.dict(os.environ, env, clear=False), patch.object(
                common,
                "kubectl",
                side_effect=lambda *args, **kwargs: next(responses),
            ), patch.object(
                common.subprocess,
                "run",
                side_effect=fake_apply,
            ):
                created = common.write_restricted_agent_kubeconfig()

            self.assertEqual(created, output.resolve())
            config = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(config["contexts"][0]["context"]["namespace"], "ops-tci061-test")
            self.assertEqual(config["users"][0]["user"]["token"], "short-lived-token")
            self.assertNotIn("admin", json.dumps(config))
            role = next(
                item for item in applied_manifests[0]["items"] if item["kind"] == "Role"
            )
            self.assertTrue(
                any(
                    rule["resources"] == ["services/proxy"]
                    and rule["verbs"] == ["get"]
                    for rule in role["rules"]
                )
            )

    def test_kubernetes_agent_mounts_no_case_or_admin_kubeconfig(self):
        case = load_case(ROOT / "cases" / "otel-k8s-tci061-image-reference")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            agent_dir = root / "agent"
            agent_dir.mkdir()
            agent = agent_dir / "run.sh"
            agent.write_text("#!/bin/sh\n", encoding="utf-8")
            task = root / "task.md"
            task.write_text("task", encoding="utf-8")
            trace = root / "trace"
            trace.mkdir()
            kubeconfig = root / "agent-kubeconfig.json"
            kubeconfig.write_text("{}", encoding="utf-8")
            env = {
                "OPSBENCH_COMPOSE_PROJECT": "opsbench_test",
                "OPSBENCH_CASE_ID": case.id,
                "OPSBENCH_RUN_ID": "run",
                "OPSBENCH_NAMESPACE": "ops-tci061-test",
                "OPSBENCH_AGENT_KUBECONFIG": str(kubeconfig),
            }

            command = _agent_container_cmd(
                case,
                agent,
                task,
                root,
                trace,
                420,
                env,
            )

            joined = " ".join(command)
            self.assertIn(f"{agent_dir}:/agent:ro", command)
            self.assertIn(f"{kubeconfig.resolve()}:/kube/config:ro", command)
            self.assertNotIn(f"{case.case_dir}:", joined)
            self.assertNotIn(str(Path.home() / ".kube"), joined)


if __name__ == "__main__":
    unittest.main()
