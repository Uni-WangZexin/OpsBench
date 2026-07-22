from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from generate_kubernetes_cases import CASES_ROOT, STATE_SPECS, parse_fault_rows


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Kubernetes故障注入说明.md"


STRATEGY_DETAILS = {
    "stress": (
        "直接负载注入",
        "创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。",
        "故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。",
    ),
    "workload_stress": (
        "目标工作负载真实压力",
        "向目标 Demo Deployment 注入名称中性的辅助容器；CPU case 执行单核忙循环，内存 case 实际分配 448MiB，I/O case 持续 fsync。压力直接体现在目标 Pod，而不是另建带故障标识的 Pod。",
        "注入时同时检查 Deployment sidecar 和 cAdvisor 资源指标；修复后辅助容器消失、Deployment Ready 且对应指标回落。",
    ),
    "deployment": (
        "真实工作负载变更",
        "直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。",
        "检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。",
    ),
    "service": (
        "真实服务发现故障",
        "直接修改或删除 Demo Service，造成错误 selector、targetPort、sessionAffinity、Service 类型或服务缺失。",
        "检查 Service spec/存在性和 Endpoints；修复后目标值恢复且端点重新可用。",
    ),
    "network_policy": (
        "真实网络策略",
        "创建 networking.k8s.io/v1 NetworkPolicy，对目标工作负载实施 ingress/egress 隔离。策略是否丢包由集群 CNI 执行。",
        "检查 NetworkPolicy 存在；修复时删除策略并确认资源消失。",
    ),
    "proxy": (
        "真实数据面故障",
        "创建 TCP 故障代理和保留原后端 selector 的上游 Service，再把业务 Service selector 切到代理；代理按 case 实际增加 500ms 延迟、约 50% 连接丢弃或 16KiB/s 限速。",
        "检查代理 Pod Running、Service 已选择代理且 Endpoints 可用；修复后 Service 必须重新选择原组件并恢复端点。",
    ),
    "node": (
        "安全节点级注入",
        "对 benchmark 专用 Minikube 节点执行 cordon 或 NoSchedule taint，真实改变调度状态。为保证单节点集群可恢复，不停止 kubelet。",
        "检查 Node unschedulable/taint；修复后 uncordon 或移除 taint。cleanup 也会兜底恢复。",
    ),
    "config_probe": (
        "配置驱动的真实失败",
        "创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。",
        "同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。",
    ),
    "pending": (
        "真实调度失败",
        "创建具有不可满足 CPU 请求或拓扑约束的 Pod，由 Kubernetes scheduler 实际保持 Pending 并产生 FailedScheduling Event。",
        "检查 Pod phase=Pending；修复时删除错误工作负载。",
    ),
    "pull_secret": (
        "真实镜像凭据变更",
        "创建无效 dockerconfig Secret 并将其挂到 Demo Deployment 的 imagePullSecrets，触发真实滚动更新和拉取凭据路径。",
        "检查 Deployment PodTemplate；修复后移除错误引用且 Deployment Ready。",
    ),
    "quota": (
        "真实资源配额耗尽",
        "按当前 Pod 用量创建 ResourceQuota，使 pods hard 等于 used，后续 Pod 创建被 API Server 拒绝。",
        "检查 ResourceQuota status.used >= hard；修复后删除或放宽配额。",
    ),
    "ingress": (
        "真实 Ingress 配置故障",
        "创建并修改 networking.k8s.io/v1 Ingress 的 path 或 ssl-redirect annotation。",
        "检查真实 Ingress spec/annotation；修复后恢复健康值。",
    ),
}


def fenced(value: str) -> str:
    return f"```text\n{value.strip().replace('```', '`` `') or '未提供'}\n```"


def implementation_summary(implementation: dict[str, Any]) -> str:
    values = [f"strategy={implementation['strategy']}"]
    for key in ("mode", "component", "target", "fault", "key", "faulty"):
        if key in implementation:
            values.append(f"{key}={implementation[key]}")
    return ", ".join(values)


def generate() -> str:
    rows = parse_fault_rows()
    lines = [
        "# Kubernetes 故障注入说明（TCI038-TCI092）",
        "",
        "## 1. 实现原则",
        "",
        "TCI038-TCI092 共 55 个 case 均在 benchmark 管理的 Docker-backed Minikube 中执行。每个 case 有独立 namespace，agent 本身运行在独立容器中，只能通过统一工具和受限 kubeconfig 观察、修复集群。",
        "",
        "故障判定不再依赖状态 ConfigMap。注入器必须创建真实 Kubernetes 对象、修改真实 Demo 资源或启动真实负载；`check_injected.py` 直接检查相应对象、Prometheus/cAdvisor 指标和运行状态；`verify.py` 直接检查修复后的对象、端点、Ready 状态及资源指标。`otel-demo-alert-context` 只提供告警线索，不参与评分。",
        "",
        "> 节点、云服务和物理网络类原始故障在单节点本地集群中不能安全地一比一执行。例如停止唯一 kubelet 会同时切断 agent 的修复通道，OBS/ELB 也不存在真实云账号。因此这些 case 使用可恢复的 Kubernetes 等价故障，但等价故障本身必须真实发生并产生 Pending、CrashLoop、服务中断或调度状态变化，绝不以单独修改状态字段代替故障。",
        "",
        "## 2. 生命周期与隔离",
        "",
        "1. runner 确保专用 `opsbench` Minikube 和缓存的 OpenTelemetry Demo Helm chart 可用。",
        "2. `setup.py` 创建 case namespace、安装 Demo、建立需要的健康基线对象和 agent 的受限 RBAC。",
        "3. `inject.py` 执行真实注入，并等待真实故障检查成立；不成立则本次运行直接失败。",
        "4. agent 容器只能访问 Kubernetes API 和标准可观测工具，不能读取 case/hidden/work 宿主目录。",
        "5. `verify.py` 检查 namespace 和真实资源是否恢复，不调用 agent 工具，也不接受状态声明作为修复证据。",
        "6. `cleanup.py` 卸载 release、删除 namespace，并兜底撤销 Node cordon/taint 和 ClusterRoleBinding。",
        "",
        "## 3. 注入机制",
        "",
        "| 策略 | 保真类型 | 实际动作 | 注入/修复判据 |",
        "| --- | --- | --- | --- |",
    ]
    for strategy, (fidelity, action, checks) in STRATEGY_DETAILS.items():
        lines.append(f"| `{strategy}` | {fidelity} | {action} | {checks} |")

    lines.extend([
        "",
        "## 4. Case 总览",
        "",
        "| TC | Case | 原始子场景 | 真实实现 | 健康值 -> 故障值 |",
        "| --- | --- | --- | --- | --- |",
    ])
    scenarios: list[tuple[dict[str, str], dict[str, Any]]] = []
    for tc in sorted(STATE_SPECS):
        field, healthy, faulty, _, _ = STATE_SPECS[tc]
        case_id = f"otel-k8s-{tc.lower()}-{field.replace('_', '-')}"
        scenario = json.loads((CASES_ROOT / case_id / "hidden" / "scenario.json").read_text(encoding="utf-8"))
        row = rows[tc]
        scenarios.append((row, scenario))
        lines.append(f"| {tc} | `{case_id}` | {row['subscene']} | `{implementation_summary(scenario['implementation'])}` | `{healthy}` -> `{faulty}` |")

    lines.extend(["", "## 5. 各 Case 详细说明", ""])
    for row, scenario in scenarios:
        implementation = scenario["implementation"]
        strategy = implementation["strategy"]
        fidelity, action, checks = STRATEGY_DETAILS[strategy]
        state = scenario["state"]
        lines.extend([
            f"### {scenario['tc']} · {row['subscene']}",
            "",
            f"- **目录**：`cases/{scenario['id']}/`",
            f"- **原始根因**：{row['root_cause']}",
            f"- **语义资源**：`{scenario['resource']}`",
            f"- **实现参数**：`{implementation_summary(implementation)}`",
            f"- **保真类型**：{fidelity}",
            f"- **语义状态**：`{state['field']}: {state['healthy']} -> {state['faulty']}`",
            "",
            "**原始建议手段**",
            "",
            fenced(row["context"]),
            "",
            "**当前真实注入**",
            "",
            action,
            "",
            f"具体参数为 `{json.dumps(implementation, ensure_ascii=False, separators=(',', ':'))}`。",
            "注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。",
            "",
            "**检查与修复条件**",
            "",
            checks,
            "",
        ])

    lines.extend([
        "## 6. 保真度边界",
        "",
        "- CPU、内存、磁盘 I/O、磁盘占用、连接和 DNS 压力会执行真实消耗命令，并设置 requests/limits 与 namespace 隔离。",
        "- Deployment、Service、Ingress、Secret、ResourceQuota、NetworkPolicy 和调度故障均作用于真实 Kubernetes API 对象。",
        "- kubelet/节点 OS/云资源类 case 使用安全等价结果。它们会制造真实不可用状态，但不声称修改了宿主机 kubelet 配置或真实云厂商资源。",
        "- NetworkPolicy 的实际封包执行能力取决于 Minikube CNI；资源对象与修复判据始终真实，后续可在基准集群启用 Calico/Cilium 进一步验证数据面阻断。",
        "- 每个注入都必须可由 agent 在其统一权限内修复，并由 cleanup 在异常退出后回收。",
        "- Chart 0.11.0 的 `v1.0.0-featureflagservice` 实际镜像架构为 amd64；在本 benchmark 的 ARM64 Minikube 中经模拟执行会段错误。Pod 带有 `demo.open-telemetry.io/baseline-known-issue=amd64-image-on-arm64` 注解，且不作为 case 故障证据。",
        "",
        "本文档由 `tools/generate_fault_injection_docs.py` 生成。修改目录后运行：",
        "",
        "```bash",
        "python3 tools/generate_kubernetes_cases.py",
        "python3 tools/generate_fault_injection_docs.py",
        "```",
    ])
    return "\n".join(lines) + "\n"


def main() -> None:
    OUTPUT.write_text(generate(), encoding="utf-8")
    print(f"generated {OUTPUT.name}")


if __name__ == "__main__":
    main()
