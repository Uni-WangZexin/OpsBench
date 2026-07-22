# Kubernetes 故障注入说明（TCI038-TCI092）

## 1. 实现原则

TCI038-TCI092 共 55 个 case 均在 benchmark 管理的 Docker-backed Minikube 中执行。每个 case 有独立 namespace，agent 本身运行在独立容器中，只能通过统一工具和受限 kubeconfig 观察、修复集群。

故障判定不再依赖状态 ConfigMap。注入器必须创建真实 Kubernetes 对象、修改真实 Demo 资源或启动真实负载；`check_injected.py` 直接检查相应对象、Prometheus/cAdvisor 指标和运行状态；`verify.py` 直接检查修复后的对象、端点、Ready 状态及资源指标。`otel-demo-alert-context` 只提供告警线索，不参与评分。

> 节点、云服务和物理网络类原始故障在单节点本地集群中不能安全地一比一执行。例如停止唯一 kubelet 会同时切断 agent 的修复通道，OBS/ELB 也不存在真实云账号。因此这些 case 使用可恢复的 Kubernetes 等价故障，但等价故障本身必须真实发生并产生 Pending、CrashLoop、服务中断或调度状态变化，绝不以单独修改状态字段代替故障。

## 2. 生命周期与隔离

1. runner 确保专用 `opsbench` Minikube 和缓存的 OpenTelemetry Demo Helm chart 可用。
2. `setup.py` 创建 case namespace、安装 Demo、建立需要的健康基线对象和 agent 的受限 RBAC。
3. `inject.py` 执行真实注入，并等待真实故障检查成立；不成立则本次运行直接失败。
4. agent 容器只能访问 Kubernetes API 和标准可观测工具，不能读取 case/hidden/work 宿主目录。
5. `verify.py` 检查 namespace 和真实资源是否恢复，不调用 agent 工具，也不接受状态声明作为修复证据。
6. `cleanup.py` 卸载 release、删除 namespace，并兜底撤销 Node cordon/taint 和 ClusterRoleBinding。

## 3. 注入机制

| 策略 | 保真类型 | 实际动作 | 注入/修复判据 |
| --- | --- | --- | --- |
| `stress` | 直接负载注入 | 创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。 | 故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。 |
| `workload_stress` | 目标工作负载真实压力 | 向目标 Demo Deployment 注入名称中性的辅助容器；CPU case 执行单核忙循环，内存 case 实际分配 448MiB，I/O case 持续 fsync。压力直接体现在目标 Pod，而不是另建带故障标识的 Pod。 | 注入时同时检查 Deployment sidecar 和 cAdvisor 资源指标；修复后辅助容器消失、Deployment Ready 且对应指标回落。 |
| `deployment` | 真实工作负载变更 | 直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。 | 检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。 |
| `service` | 真实服务发现故障 | 直接修改或删除 Demo Service，造成错误 selector、targetPort、sessionAffinity、Service 类型或服务缺失。 | 检查 Service spec/存在性和 Endpoints；修复后目标值恢复且端点重新可用。 |
| `network_policy` | 真实网络策略 | 创建 networking.k8s.io/v1 NetworkPolicy，对目标工作负载实施 ingress/egress 隔离。策略是否丢包由集群 CNI 执行。 | 检查 NetworkPolicy 存在；修复时删除策略并确认资源消失。 |
| `proxy` | 真实数据面故障 | 创建 TCP 故障代理和保留原后端 selector 的上游 Service，再把业务 Service selector 切到代理；代理按 case 实际增加 500ms 延迟、约 50% 连接丢弃或 16KiB/s 限速。 | 检查代理 Pod Running、Service 已选择代理且 Endpoints 可用；修复后 Service 必须重新选择原组件并恢复端点。 |
| `node` | 安全节点级注入 | 对 benchmark 专用 Minikube 节点执行 cordon 或 NoSchedule taint，真实改变调度状态。为保证单节点集群可恢复，不停止 kubelet。 | 检查 Node unschedulable/taint；修复后 uncordon 或移除 taint。cleanup 也会兜底恢复。 |
| `config_probe` | 配置驱动的真实失败 | 创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。 | 同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。 |
| `pending` | 真实调度失败 | 创建具有不可满足 CPU 请求或拓扑约束的 Pod，由 Kubernetes scheduler 实际保持 Pending 并产生 FailedScheduling Event。 | 检查 Pod phase=Pending；修复时删除错误工作负载。 |
| `pull_secret` | 真实镜像凭据变更 | 创建无效 dockerconfig Secret 并将其挂到 Demo Deployment 的 imagePullSecrets，触发真实滚动更新和拉取凭据路径。 | 检查 Deployment PodTemplate；修复后移除错误引用且 Deployment Ready。 |
| `quota` | 真实资源配额耗尽 | 按当前 Pod 用量创建 ResourceQuota，使 pods hard 等于 used，后续 Pod 创建被 API Server 拒绝。 | 检查 ResourceQuota status.used >= hard；修复后删除或放宽配额。 |
| `ingress` | 真实 Ingress 配置故障 | 创建并修改 networking.k8s.io/v1 Ingress 的 path 或 ssl-redirect annotation。 | 检查真实 Ingress spec/annotation；修复后恢复健康值。 |

## 4. Case 总览

| TC | Case | 原始子场景 | 真实实现 | 健康值 -> 故障值 |
| --- | --- | --- | --- | --- |
| TCI038 | `otel-k8s-tci038-cpu-load` | CCE工作负载运行异常 | `strategy=workload_stress, mode=cpu, component=frontend` | `normal` -> `saturated` |
| TCI039 | `otel-k8s-tci039-memory-pressure` | CCE工作负载运行异常 | `strategy=workload_stress, mode=memory, component=frontend` | `normal` -> `exhausted` |
| TCI040 | `otel-k8s-tci040-disk-io-pressure` | CCE工作负载运行异常 | `strategy=workload_stress, mode=io, component=checkoutservice` | `normal` -> `saturated` |
| TCI041 | `otel-k8s-tci041-pod-lifecycle` | CCE工作负载运行异常 | `strategy=deployment, component=checkoutservice, fault=crash` | `stable` -> `forced-restart` |
| TCI042 | `otel-k8s-tci042-listen-port` | CCE工作负载运行异常 | `strategy=service, component=frontendproxy, fault=target_port, faulty=65535` | `8080` -> `closed` |
| TCI043 | `otel-k8s-tci043-pod-connectivity` | CCE工作负载运行异常 | `strategy=network_policy, component=frontend, fault=deny_ingress` | `allowed` -> `denied` |
| TCI044 | `otel-k8s-tci044-cpu-limit` | CCE工作负载运行异常 | `strategy=deployment, component=productcatalogservice, fault=cpu_limit, faulty=100m` | `500m` -> `100m` |
| TCI045 | `otel-k8s-tci045-node-network` | CCE工作负载运行异常 | `strategy=node, fault=taint, key=opsbench.io/network-unreachable` | `reachable` -> `unreachable` |
| TCI046 | `otel-k8s-tci046-cpu-pressure` | CCE Node节点状态异常 | `strategy=stress, mode=cpu, target=node` | `false` -> `true` |
| TCI047 | `otel-k8s-tci047-memory-pressure` | CCE Node节点状态异常 | `strategy=stress, mode=memory, target=node` | `false` -> `true` |
| TCI048 | `otel-k8s-tci048-disk-io-pressure` | CCE Node节点状态异常 | `strategy=stress, mode=io, target=node` | `false` -> `true` |
| TCI049 | `otel-k8s-tci049-network-utilization` | CCE Node节点状态异常 | `strategy=stress, mode=network, target=frontendproxy` | `normal` -> `saturated` |
| TCI050 | `otel-k8s-tci050-kubelet-state` | CCE Node节点状态异常 | `strategy=node, fault=cordon` | `running` -> `stopped` |
| TCI051 | `otel-k8s-tci051-kubelet-certificate` | CCE Node节点状态异常 | `strategy=config_probe, key=certificate, faulty=expired` | `valid` -> `expired` |
| TCI052 | `otel-k8s-tci052-cgroup-driver` | CCE Node节点状态异常 | `strategy=config_probe, key=cgroup-driver, faulty=cgroupfs` | `systemd` -> `mismatched` |
| TCI053 | `otel-k8s-tci053-root-filesystem` | CCE Node节点状态异常 | `strategy=deployment, component=frontend, fault=read_only_root` | `writable` -> `read-only` |
| TCI054 | `otel-k8s-tci054-disk-usage` | CCE Node节点状态异常 | `strategy=stress, mode=disk_fill, target=node` | `45%` -> `100%` |
| TCI055 | `otel-k8s-tci055-ip-forward` | CCE Node节点状态异常 | `strategy=config_probe, key=ip-forward, faulty=0` | `1` -> `0` |
| TCI056 | `otel-k8s-tci056-scheduler-capacity` | CCE工作负载创删异常 | `strategy=pending, fault=oversized_cpu` | `available` -> `insufficient` |
| TCI057 | `otel-k8s-tci057-node-affinity` | CCE工作负载创删异常 | `strategy=deployment, component=frontend, fault=node_selector` | `satisfiable` -> `unsatisfiable` |
| TCI058 | `otel-k8s-tci058-volume-zone` | CCE工作负载创删异常 | `strategy=pending, fault=volume_zone` | `same-zone` -> `cross-zone` |
| TCI059 | `otel-k8s-tci059-nfs-endpoint` | CCE工作负载创删异常 | `strategy=config_probe, key=nfs-endpoint, faulty=203.0.113.1:2049` | `available` -> `unavailable` |
| TCI060 | `otel-k8s-tci060-obs-access-key` | CCE工作负载创删异常 | `strategy=config_probe, key=obs-access-key, faulty=invalid-access-key` | `valid` -> `invalid` |
| TCI061 | `otel-k8s-tci061-image-reference` | CCE工作负载创删异常 | `strategy=deployment, component=frontend, fault=image` | `valid` -> `invalid-tag` |
| TCI062 | `otel-k8s-tci062-image-pull-secret` | CCE工作负载创删异常 | `strategy=pull_secret, component=frontend` | `valid` -> `invalid` |
| TCI063 | `otel-k8s-tci063-subnet-ip-capacity` | CCE工作负载创删异常 | `strategy=quota` | `available` -> `exhausted` |
| TCI064 | `otel-k8s-tci064-conntrack-capacity` | CCE网络时延增大 | `strategy=stress, mode=connections, target=frontendproxy` | `available` -> `exhausted` |
| TCI065 | `otel-k8s-tci065-packet-loss` | CCE网络时延增大 | `strategy=proxy, mode=packet_loss, component=frontendproxy` | `0%` -> `50%` |
| TCI066 | `otel-k8s-tci066-egress-bandwidth` | CCE网络时延增大 | `strategy=proxy, mode=bandwidth, component=frontendproxy` | `normal` -> `saturated` |
| TCI067 | `otel-k8s-tci067-syn-backlog` | CCE网络时延增大 | `strategy=stress, mode=connections, target=frontendproxy` | `normal` -> `flooded` |
| TCI068 | `otel-k8s-tci068-security-group-port-80` | CCE网络不通 | `strategy=network_policy, component=frontendproxy, fault=deny_ingress` | `allow` -> `deny` |
| TCI069 | `otel-k8s-tci069-network-acl` | CCE网络不通 | `strategy=network_policy, component=frontendproxy, fault=deny_all` | `allow` -> `deny` |
| TCI070 | `otel-k8s-tci070-service-owner` | CCE网络不通 | `strategy=service, component=checkoutservice, fault=selector, faulty=shadow-backend` | `expected` -> `shadowed` |
| TCI071 | `otel-k8s-tci071-controller-config` | CCE Nginx-Ingress访问异常 | `strategy=config_probe, key=controller-config, faulty=invalid` | `valid` -> `invalid` |
| TCI072 | `otel-k8s-tci072-session-affinity` | CCE Nginx-Ingress访问异常 | `strategy=service, component=frontendproxy, fault=affinity, faulty=None` | `cookie` -> `none` |
| TCI073 | `otel-k8s-tci073-service-selector` | CCE Nginx-Ingress访问异常 | `strategy=service, component=frontend, fault=selector, faulty=missing-backend` | `matched` -> `missing` |
| TCI074 | `otel-k8s-tci074-rewrite-target` | CCE Nginx-Ingress访问异常 | `strategy=ingress, fault=path, faulty=/invalid-path` | `/` -> `/invalid-path` |
| TCI075 | `otel-k8s-tci075-service-port` | CCE Nginx-Ingress访问异常 | `strategy=service, component=frontendproxy, fault=target_port, faulty=9999` | `80` -> `8080` |
| TCI076 | `otel-k8s-tci076-controller-image` | CCE Nginx-Ingress访问异常 | `strategy=deployment, component=frontendproxy, fault=image` | `valid` -> `invalid` |
| TCI077 | `otel-k8s-tci077-coredns-kubernetes-plugin` | CCE域名解析失败 | `strategy=config_probe, key=coredns-kubernetes-plugin, faulty=removed` | `enabled` -> `removed` |
| TCI078 | `otel-k8s-tci078-dns-ingress` | CCE域名解析失败 | `strategy=network_policy, component=otelcol, fault=deny_ingress` | `allowed` -> `denied` |
| TCI079 | `otel-k8s-tci079-nodelocaldns-upstream` | CCE域名解析失败 | `strategy=config_probe, key=dns-upstream, faulty=127.0.0.1:9999` | `kube-dns` -> `127.0.0.1:9999` |
| TCI080 | `otel-k8s-tci080-dns-egress-udp-53` | CCE域名解析失败 | `strategy=network_policy, component=loadgenerator, fault=deny_egress` | `allowed` -> `denied` |
| TCI081 | `otel-k8s-tci081-coredns-cpu-limit` | CCE域名解析失败 | `strategy=stress, mode=dns, target=kube-dns` | `200m` -> `50m` |
| TCI082 | `otel-k8s-tci082-dns-query-rate` | CCE域名解析失败 | `strategy=stress, mode=dns, target=kube-dns` | `normal` -> `overloaded` |
| TCI083 | `otel-k8s-tci083-backend-replicas` | CCE ELB-Ingress异常 | `strategy=deployment, component=checkoutservice, fault=replicas, faulty=0` | `2` -> `0` |
| TCI084 | `otel-k8s-tci084-backend-memory-limit` | CCE ELB-Ingress异常 | `strategy=deployment, component=checkoutservice, fault=memory_limit, faulty=10Mi` | `256Mi` -> `10Mi` |
| TCI085 | `otel-k8s-tci085-upstream-retries` | CCE ELB-Ingress异常 | `strategy=config_probe, key=upstream-retries, faulty=1` | `3` -> `1` |
| TCI086 | `otel-k8s-tci086-ingress-path` | CCE ELB-Ingress异常 | `strategy=ingress, fault=path, faulty=/wrong-path` | `/` -> `/wrong-path` |
| TCI087 | `otel-k8s-tci087-backend-service` | CCE ELB-Ingress异常 | `strategy=service, component=checkoutservice, fault=delete, faulty=deleted` | `present` -> `deleted` |
| TCI088 | `otel-k8s-tci088-backend-latency` | CCE ELB-Ingress异常 | `strategy=proxy, mode=latency, component=checkoutservice` | `0ms` -> `500ms` |
| TCI089 | `otel-k8s-tci089-ingress-cpu-limit` | CCE ELB-Ingress异常 | `strategy=deployment, component=frontendproxy, fault=cpu_limit, faulty=100m` | `500m` -> `100m` |
| TCI090 | `otel-k8s-tci090-ssl-redirect` | CCE ELB-Ingress异常 | `strategy=ingress, fault=ssl_redirect, faulty=false` | `true` -> `false` |
| TCI091 | `otel-k8s-tci091-tls-certificate` | CCE ELB-Ingress异常 | `strategy=config_probe, key=tls-certificate, faulty=expired` | `valid` -> `expired` |
| TCI092 | `otel-k8s-tci092-elb-eip` | CCE ELB-Ingress异常 | `strategy=service, component=frontendproxy, fault=type, faulty=LoadBalancer` | `bound` -> `unbound` |

## 5. 各 Case 详细说明

### TCI038 · CCE工作负载运行异常

- **目录**：`cases/otel-k8s-tci038-cpu-load/`
- **原始根因**：CPU过载
- **语义资源**：`Deployment/frontend`
- **实现参数**：`strategy=workload_stress, mode=cpu, component=frontend`
- **保真类型**：目标工作负载真实压力
- **语义状态**：`cpu_load: normal -> saturated`

**原始建议手段**

```text
通过压力测试工具（如stress-ng）模拟高CPU占用。
```

**当前真实注入**

向目标 Demo Deployment 注入名称中性的辅助容器；CPU case 执行单核忙循环，内存 case 实际分配 448MiB，I/O case 持续 fsync。压力直接体现在目标 Pod，而不是另建带故障标识的 Pod。

具体参数为 `{"strategy":"workload_stress","mode":"cpu","component":"frontend","active_threshold":0.65,"recovery_threshold":0.35}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

注入时同时检查 Deployment sidecar 和 cAdvisor 资源指标；修复后辅助容器消失、Deployment Ready 且对应指标回落。

### TCI039 · CCE工作负载运行异常

- **目录**：`cases/otel-k8s-tci039-memory-pressure/`
- **原始根因**：内存过载
- **语义资源**：`Deployment/frontend`
- **实现参数**：`strategy=workload_stress, mode=memory, component=frontend`
- **保真类型**：目标工作负载真实压力
- **语义状态**：`memory_pressure: normal -> exhausted`

**原始建议手段**

```text
使用dd或内存填充工具耗尽内存。
```

**当前真实注入**

向目标 Demo Deployment 注入名称中性的辅助容器；CPU case 执行单核忙循环，内存 case 实际分配 448MiB，I/O case 持续 fsync。压力直接体现在目标 Pod，而不是另建带故障标识的 Pod。

具体参数为 `{"strategy":"workload_stress","mode":"memory","component":"frontend","active_threshold":367001600,"recovery_threshold":314572800}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

注入时同时检查 Deployment sidecar 和 cAdvisor 资源指标；修复后辅助容器消失、Deployment Ready 且对应指标回落。

### TCI040 · CCE工作负载运行异常

- **目录**：`cases/otel-k8s-tci040-disk-io-pressure/`
- **原始根因**：磁盘过载
- **语义资源**：`Pod/accounting`
- **实现参数**：`strategy=workload_stress, mode=io, component=checkoutservice`
- **保真类型**：目标工作负载真实压力
- **语义状态**：`disk_io_pressure: normal -> saturated`

**原始建议手段**

```text
写入大文件或模拟高IOPS操作（如fio）。
```

**当前真实注入**

向目标 Demo Deployment 注入名称中性的辅助容器；CPU case 执行单核忙循环，内存 case 实际分配 448MiB，I/O case 持续 fsync。压力直接体现在目标 Pod，而不是另建带故障标识的 Pod。

具体参数为 `{"strategy":"workload_stress","mode":"io","component":"checkoutservice"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

注入时同时检查 Deployment sidecar 和 cAdvisor 资源指标；修复后辅助容器消失、Deployment Ready 且对应指标回落。

### TCI041 · CCE工作负载运行异常

- **目录**：`cases/otel-k8s-tci041-pod-lifecycle/`
- **原始根因**：强制重启
- **语义资源**：`Pod/checkout`
- **实现参数**：`strategy=deployment, component=checkoutservice, fault=crash`
- **保真类型**：真实工作负载变更
- **语义状态**：`pod_lifecycle: stable -> forced-restart`

**原始建议手段**

```text
kubectl delete pod <pod>模拟崩溃
```

**当前真实注入**

直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。

具体参数为 `{"strategy":"deployment","component":"checkoutservice","fault":"crash"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。

### TCI042 · CCE工作负载运行异常

- **目录**：`cases/otel-k8s-tci042-listen-port/`
- **原始根因**：端口未监听
- **语义资源**：`Deployment/frontend-proxy`
- **实现参数**：`strategy=service, component=frontendproxy, fault=target_port, faulty=65535`
- **保真类型**：真实服务发现故障
- **语义状态**：`listen_port: 8080 -> closed`

**原始建议手段**

```text
修改容器启动命令
# Kubernetes Deployment 示例
containers:
- name: app
  image: your-app:latest
  command: ["/bin/sh", "-c"]  # 覆盖原始启动命令
  args: ["echo '模拟端口未监听' && sleep infinity"]  # 不启动真实服务
```

**当前真实注入**

直接修改或删除 Demo Service，造成错误 selector、targetPort、sessionAffinity、Service 类型或服务缺失。

具体参数为 `{"strategy":"service","component":"frontendproxy","fault":"target_port","healthy":8080,"faulty":65535}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Service spec/存在性和 Endpoints；修复后目标值恢复且端点重新可用。

### TCI043 · CCE工作负载运行异常

- **目录**：`cases/otel-k8s-tci043-pod-connectivity/`
- **原始根因**：网络隔离
- **语义资源**：`NetworkPolicy/frontend`
- **实现参数**：`strategy=network_policy, component=frontend, fault=deny_ingress`
- **保真类型**：真实网络策略
- **语义状态**：`pod_connectivity: allowed -> denied`

**原始建议手段**

```text
通过NetworkPolicy限制Pod间通信
```

**当前真实注入**

创建 networking.k8s.io/v1 NetworkPolicy，对目标工作负载实施 ingress/egress 隔离。策略是否丢包由集群 CNI 执行。

具体参数为 `{"strategy":"network_policy","component":"frontend","fault":"deny_ingress"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 NetworkPolicy 存在；修复时删除策略并确认资源消失。

### TCI044 · CCE工作负载运行异常

- **目录**：`cases/otel-k8s-tci044-cpu-limit/`
- **原始根因**：CPU limits
- **语义资源**：`Deployment/product-catalog`
- **实现参数**：`strategy=deployment, component=productcatalogservice, fault=cpu_limit, faulty=100m`
- **保真类型**：真实工作负载变更
- **语义状态**：`cpu_limit: 500m -> 100m`

**原始建议手段**

```text
设置极低的CPU limits（如100m）并施加计算压力。
```

**当前真实注入**

直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。

具体参数为 `{"strategy":"deployment","component":"productcatalogservice","fault":"cpu_limit","healthy":"500m","faulty":"100m"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。

### TCI045 · CCE工作负载运行异常

- **目录**：`cases/otel-k8s-tci045-node-network/`
- **原始根因**：网络异常
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=node, fault=taint, key=opsbench.io/network-unreachable`
- **保真类型**：安全节点级注入
- **语义状态**：`node_network: reachable -> unreachable`

**原始建议手段**

```text
关闭节点或模拟节点网络断开
```

**当前真实注入**

对 benchmark 专用 Minikube 节点执行 cordon 或 NoSchedule taint，真实改变调度状态。为保证单节点集群可恢复，不停止 kubelet。

具体参数为 `{"strategy":"node","fault":"taint","key":"opsbench.io/network-unreachable"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Node unschedulable/taint；修复后 uncordon 或移除 taint。cleanup 也会兜底恢复。

### TCI046 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci046-cpu-pressure/`
- **原始根因**：CPU过载
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=stress, mode=cpu, target=node`
- **保真类型**：直接负载注入
- **语义状态**：`cpu_pressure: false -> true`

**原始建议手段**

```text
使用stress-ng --cpu 8 --vm 4 --vm-bytes 2G模拟。
```

**当前真实注入**

创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。

具体参数为 `{"strategy":"stress","mode":"cpu","target":"node","workers":4,"active_threshold":2.0,"recovery_threshold":0.2}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。

### TCI047 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci047-memory-pressure/`
- **原始根因**：内存过载
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=stress, mode=memory, target=node`
- **保真类型**：直接负载注入
- **语义状态**：`memory_pressure: false -> true`

**原始建议手段**

```text
使用stress-ng --cpu 8 --vm 4 --vm-bytes 2G模拟。
```

**当前真实注入**

创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。

具体参数为 `{"strategy":"stress","mode":"memory","target":"node","memory_mib":1280,"active_threshold":1073741824,"recovery_threshold":134217728}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。

### TCI048 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci048-disk-io-pressure/`
- **原始根因**：磁盘IO过载
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=stress, mode=io, target=node`
- **保真类型**：直接负载注入
- **语义状态**：`disk_io_pressure: false -> true`

**原始建议手段**

```text
通过fio工具制造高IO压力。
```

**当前真实注入**

创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。

具体参数为 `{"strategy":"stress","mode":"io","target":"node"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。

### TCI049 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci049-network-utilization/`
- **原始根因**：网络带宽过载
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=stress, mode=network, target=frontendproxy`
- **保真类型**：直接负载注入
- **语义状态**：`network_utilization: normal -> saturated`

**原始建议手段**

```text
用iperf3饱和节点网络。
```

**当前真实注入**

创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。

具体参数为 `{"strategy":"stress","mode":"network","target":"frontendproxy"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。

### TCI050 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci050-kubelet-state/`
- **原始根因**：手动停止组件
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=node, fault=cordon`
- **保真类型**：安全节点级注入
- **语义状态**：`kubelet_state: running -> stopped`

**原始建议手段**

```text
systemctl stop kubelet
```

**当前真实注入**

对 benchmark 专用 Minikube 节点执行 cordon 或 NoSchedule taint，真实改变调度状态。为保证单节点集群可恢复，不停止 kubelet。

具体参数为 `{"strategy":"node","fault":"cordon"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Node unschedulable/taint；修复后 uncordon 或移除 taint。cleanup 也会兜底恢复。

### TCI051 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci051-kubelet-certificate/`
- **原始根因**：模拟证书过期
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=config_probe, key=certificate, faulty=expired`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`kubelet_certificate: valid -> expired`

**原始建议手段**

```text
修改kubelet证书时间
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"certificate","healthy":"valid","faulty":"expired"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI052 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci052-cgroup-driver/`
- **原始根因**：修改kubelet源码或配置文件触发逻辑错误
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=config_probe, key=cgroup-driver, faulty=cgroupfs`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`cgroup_driver: systemd -> mismatched`

**原始建议手段**

```text
错误的cgroup驱动
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"cgroup-driver","healthy":"systemd","faulty":"cgroupfs"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI053 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci053-root-filesystem/`
- **原始根因**：强制挂载为只读
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=deployment, component=frontend, fault=read_only_root`
- **保真类型**：真实工作负载变更
- **语义状态**：`root_filesystem: writable -> read-only`

**原始建议手段**

```text
mount -o remount,ro /
```

**当前真实注入**

直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。

具体参数为 `{"strategy":"deployment","component":"frontend","fault":"read_only_root"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。

### TCI054 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci054-disk-usage/`
- **原始根因**：占满磁盘。
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=stress, mode=disk_fill, target=node`
- **保真类型**：直接负载注入
- **语义状态**：`disk_usage: 45% -> 100%`

**原始建议手段**

```text
dd if=/dev/zero of=/var/log/mount_fill bs=1G count=100
```

**当前真实注入**

创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。

具体参数为 `{"strategy":"stress","mode":"disk_fill","target":"node"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。

### TCI055 · CCE Node节点状态异常

- **目录**：`cases/otel-k8s-tci055-ip-forward/`
- **原始根因**：ip_forward=0
- **语义资源**：`Node/worker-0`
- **实现参数**：`strategy=config_probe, key=ip-forward, faulty=0`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`ip_forward: 1 -> 0`

**原始建议手段**

```text
echo 0 > /proc/sys/net/ipv4/ip_forward关闭IP转发
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"ip-forward","healthy":"1","faulty":"0"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI056 · CCE工作负载创删异常

- **目录**：`cases/otel-k8s-tci056-scheduler-capacity/`
- **原始根因**：资源不足
- **语义资源**：`Pod/load-generator`
- **实现参数**：`strategy=pending, fault=oversized_cpu`
- **保真类型**：真实调度失败
- **语义状态**：`scheduler_capacity: available -> insufficient`

**原始建议手段**

```text
通过创建超规格Pod（如requests.cpu: 100）耗尽集群资源
```

**当前真实注入**

创建具有不可满足 CPU 请求或拓扑约束的 Pod，由 Kubernetes scheduler 实际保持 Pending 并产生 FailedScheduling Event。

具体参数为 `{"strategy":"pending","fault":"oversized_cpu"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Pod phase=Pending；修复时删除错误工作负载。

### TCI057 · CCE工作负载创删异常

- **目录**：`cases/otel-k8s-tci057-node-affinity/`
- **原始根因**：亲和性配置
- **语义资源**：`Deployment/frontend`
- **实现参数**：`strategy=deployment, component=frontend, fault=node_selector`
- **保真类型**：真实工作负载变更
- **语义状态**：`node_affinity: satisfiable -> unsatisfiable`

**原始建议手段**

```text
设置无法满足的nodeAffinity（如匹配不存在的标签）
```

**当前真实注入**

直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。

具体参数为 `{"strategy":"deployment","component":"frontend","fault":"node_selector"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。

### TCI058 · CCE工作负载创删异常

- **目录**：`cases/otel-k8s-tci058-volume-zone/`
- **原始根因**：EVS挂载异常
- **语义资源**：`PersistentVolume/checkout`
- **实现参数**：`strategy=pending, fault=volume_zone`
- **保真类型**：真实调度失败
- **语义状态**：`volume_zone: same-zone -> cross-zone`

**原始建议手段**

```text
在非共享AZ的节点上创建EVS卷
```

**当前真实注入**

创建具有不可满足 CPU 请求或拓扑约束的 Pod，由 Kubernetes scheduler 实际保持 Pending 并产生 FailedScheduling Event。

具体参数为 `{"strategy":"pending","fault":"volume_zone"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Pod phase=Pending；修复时删除错误工作负载。

### TCI059 · CCE工作负载创删异常

- **目录**：`cases/otel-k8s-tci059-nfs-endpoint/`
- **原始根因**：NFS异常
- **语义资源**：`PersistentVolume/accounting`
- **实现参数**：`strategy=config_probe, key=nfs-endpoint, faulty=203.0.113.1:2049`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`nfs_endpoint: available -> unavailable`

**原始建议手段**

```text
手动停止NFS服务（systemctl stop nfs-server）
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"nfs-endpoint","healthy":"nfs.internal:2049","faulty":"203.0.113.1:2049"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI060 · CCE工作负载创删异常

- **目录**：`cases/otel-k8s-tci060-obs-access-key/`
- **原始根因**：OBS密钥错误
- **语义资源**：`Secret/telemetry-export`
- **实现参数**：`strategy=config_probe, key=obs-access-key, faulty=invalid-access-key`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`obs_access_key: valid -> invalid`

**原始建议手段**

```text
修改Secret中的access_key为无效值
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"obs-access-key","healthy":"valid-access-key","faulty":"invalid-access-key"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI061 · CCE工作负载创删异常

- **目录**：`cases/otel-k8s-tci061-image-reference/`
- **原始根因**：镜像错误
- **语义资源**：`Deployment/frontend`
- **实现参数**：`strategy=deployment, component=frontend, fault=image`
- **保真类型**：真实工作负载变更
- **语义状态**：`image_reference: valid -> invalid-tag`

**原始建议手段**

```text
指定不存在镜像（如nginx:invalid-tag）
```

**当前真实注入**

直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。

具体参数为 `{"strategy":"deployment","component":"frontend","fault":"image"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。

### TCI062 · CCE工作负载创删异常

- **目录**：`cases/otel-k8s-tci062-image-pull-secret/`
- **原始根因**：密钥错误
- **语义资源**：`ServiceAccount/default`
- **实现参数**：`strategy=pull_secret, component=frontend`
- **保真类型**：真实镜像凭据变更
- **语义状态**：`image_pull_secret: valid -> invalid`

**原始建议手段**

```text
创建错误的imagePullSecret
```

**当前真实注入**

创建无效 dockerconfig Secret 并将其挂到 Demo Deployment 的 imagePullSecrets，触发真实滚动更新和拉取凭据路径。

具体参数为 `{"strategy":"pull_secret","component":"frontend"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment PodTemplate；修复后移除错误引用且 Deployment Ready。

### TCI063 · CCE工作负载创删异常

- **目录**：`cases/otel-k8s-tci063-subnet-ip-capacity/`
- **原始根因**：子网不足
- **语义资源**：`Namespace/otel-demo`
- **实现参数**：`strategy=quota`
- **保真类型**：真实资源配额耗尽
- **语义状态**：`subnet_ip_capacity: available -> exhausted`

**原始建议手段**

```text
创建大量InitContainer耗尽子网IP（如每个Pod需2个IP）
```

**当前真实注入**

按当前 Pod 用量创建 ResourceQuota，使 pods hard 等于 used，后续 Pod 创建被 API Server 拒绝。

具体参数为 `{"strategy":"quota"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 ResourceQuota status.used >= hard；修复后删除或放宽配额。

### TCI064 · CCE网络时延增大

- **目录**：`cases/otel-k8s-tci064-conntrack-capacity/`
- **原始根因**：模拟短连接洪水
- **语义资源**：`Pod/frontend-proxy`
- **实现参数**：`strategy=stress, mode=connections, target=frontendproxy`
- **保真类型**：直接负载注入
- **语义状态**：`conntrack_capacity: available -> exhausted`

**原始建议手段**

```text
# 在Pod内执行快速端口消耗
for i in {1..65535}; do timeout 1 nc -z <target-ip> $i & done
```

**当前真实注入**

创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。

具体参数为 `{"strategy":"stress","mode":"connections","target":"frontendproxy"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。

### TCI065 · CCE网络时延增大

- **目录**：`cases/otel-k8s-tci065-packet-loss/`
- **原始根因**：数据丢包
- **语义资源**：`NetworkPolicy/frontend`
- **实现参数**：`strategy=proxy, mode=packet_loss, component=frontendproxy`
- **保真类型**：真实数据面故障
- **语义状态**：`packet_loss: 0% -> 50%`

**原始建议手段**

```text
# 在节点网络接口注入丢包（示例为eth0，50%丢包率）
tc qdisc add dev eth0 root netem loss 50%
```

**当前真实注入**

创建 TCP 故障代理和保留原后端 selector 的上游 Service，再把业务 Service selector 切到代理；代理按 case 实际增加 500ms 延迟、约 50% 连接丢弃或 16KiB/s 限速。

具体参数为 `{"strategy":"proxy","component":"frontendproxy","mode":"packet_loss"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查代理 Pod Running、Service 已选择代理且 Endpoints 可用；修复后 Service 必须重新选择原组件并恢复端点。

### TCI066 · CCE网络时延增大

- **目录**：`cases/otel-k8s-tci066-egress-bandwidth/`
- **原始根因**：带宽压测
- **语义资源**：`Service/frontend-proxy`
- **实现参数**：`strategy=proxy, mode=bandwidth, component=frontendproxy`
- **保真类型**：真实数据面故障
- **语义状态**：`egress_bandwidth: normal -> saturated`

**原始建议手段**

```text
# 在SNAT关联的节点发起带宽压测
iperf3 -c <公网IP> -t 600 -b 2G  # 持续10分钟2Gbps流量
```

**当前真实注入**

创建 TCP 故障代理和保留原后端 selector 的上游 Service，再把业务 Service selector 切到代理；代理按 case 实际增加 500ms 延迟、约 50% 连接丢弃或 16KiB/s 限速。

具体参数为 `{"strategy":"proxy","component":"frontendproxy","mode":"bandwidth"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查代理 Pod Running、Service 已选择代理且 Endpoints 可用；修复后 Service 必须重新选择原组件并恢复端点。

### TCI067 · CCE网络时延增大

- **目录**：`cases/otel-k8s-tci067-syn-backlog/`
- **原始根因**：模拟SYN Flood
- **语义资源**：`Service/frontend-proxy`
- **实现参数**：`strategy=stress, mode=connections, target=frontendproxy`
- **保真类型**：直接负载注入
- **语义状态**：`syn_backlog: normal -> flooded`

**原始建议手段**

```text
# 使用hping3模拟SYN Flood（需在测试环境执行）
hping3 -S -p 80 --flood --rand-source <target-IP>
```

**当前真实注入**

创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。

具体参数为 `{"strategy":"stress","mode":"connections","target":"frontendproxy"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。

### TCI068 · CCE网络不通

- **目录**：`cases/otel-k8s-tci068-security-group-port-80/`
- **原始根因**：修改安全组规则（模拟误操作）
- **语义资源**：`ConfigMap/security-group`
- **实现参数**：`strategy=network_policy, component=frontendproxy, fault=deny_ingress`
- **保真类型**：真实网络策略
- **语义状态**：`security_group_port_80: allow -> deny`

**原始建议手段**

```text
1. 登录华为云控制台
访问 华为云官网
点击右上角「控制台」登录
2. 进入安全组管理界面
在顶部搜索栏输入「安全组」→ 选择「安全组」服务
或依次进入：「服务列表」→「网络」→「虚拟私有云 VPC」→「安全组」
3. 修改安全组规则
找到目标安全组（可通过ID sg-xxxx 搜索）
点击安全组名称进入详情页 → 选择「入方向规则」或「出方向规则」页签
添加拒绝规则：
点击「添加规则」
配置参数：
方向：入方向
协议：TCP
端口范围：80
源地址：0.0.0.0/0
策略：拒绝
点击「确认」
4. 验证规则生效
在规则列表中查看新增的拒绝规则
可通过「云服务器 ECS」→「远程登录」测试80端口连通性
```

**当前真实注入**

创建 networking.k8s.io/v1 NetworkPolicy，对目标工作负载实施 ingress/egress 隔离。策略是否丢包由集群 CNI 执行。

具体参数为 `{"strategy":"network_policy","component":"frontendproxy","fault":"deny_ingress"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 NetworkPolicy 存在；修复时删除策略并确认资源消失。

### TCI069 · CCE网络不通

- **目录**：`cases/otel-k8s-tci069-network-acl/`
- **原始根因**：修改ACL规则（模拟误操作）
- **语义资源**：`ConfigMap/network-acl`
- **实现参数**：`strategy=network_policy, component=frontendproxy, fault=deny_all`
- **保真类型**：真实网络策略
- **语义状态**：`network_acl: allow -> deny`

**原始建议手段**

```text
1. 登录控制台
访问华为云官网 → 登录控制台
2. 进入网络ACL管理
顶部搜索栏输入「网络ACL」→ 选择「网络ACL」服务
或依次进入：「服务列表」→「网络」→「虚拟私有云 VPC」→「网络ACL」
3. 添加拒绝规则
找到目标网络ACL（通过ID acl-xxxx 或名称搜索）
点击ACL名称进入详情页 → 选择「入方向规则」页签
点击「添加规则」并填写：
策略：拒绝
协议：ANY
源地址：0.0.0.0/0
动作：拒绝
优先级：1（数字越小优先级越高）
点击「确定」保存
4. 绑定子网（如未自动关联）
在ACL详情页选择「关联子网」→ 选择需要绑定的子网
```

**当前真实注入**

创建 networking.k8s.io/v1 NetworkPolicy，对目标工作负载实施 ingress/egress 隔离。策略是否丢包由集群 CNI 执行。

具体参数为 `{"strategy":"network_policy","component":"frontendproxy","fault":"deny_all"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 NetworkPolicy 存在；修复时删除策略并确认资源消失。

### TCI070 · CCE网络不通

- **目录**：`cases/otel-k8s-tci070-service-owner/`
- **原始根因**：恶意创建同名Service
- **语义资源**：`Service/critical-svc`
- **实现参数**：`strategy=service, component=checkoutservice, fault=selector, faulty=shadow-backend`
- **保真类型**：真实服务发现故障
- **语义状态**：`service_owner: expected -> shadowed`

**原始建议手段**

```text
apiVersion: v1
kind: Service
metadata:
  name: critical-svc
spec:
  selector:
    app: fake-app
  ports:
  - protocol: TCP
    port: 80
    targetPort: 9090
```

**当前真实注入**

直接修改或删除 Demo Service，造成错误 selector、targetPort、sessionAffinity、Service 类型或服务缺失。

具体参数为 `{"strategy":"service","component":"checkoutservice","fault":"selector","healthy":"checkoutservice","faulty":"shadow-backend"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Service spec/存在性和 Endpoints；修复后目标值恢复且端点重新可用。

### TCI071 · CCE Nginx-Ingress访问异常

- **目录**：`cases/otel-k8s-tci071-controller-config/`
- **原始根因**：在ConfigMap中注入错误参数
- **语义资源**：`ConfigMap/ingress-nginx-controller`
- **实现参数**：`strategy=config_probe, key=controller-config, faulty=invalid`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`controller_config: valid -> invalid`

**原始建议手段**

```text
# 错误示例：拼写错误或无效参数
data:
  enable-underscores-in-headers: "truee"  # 非布尔值
  proxy-buffering-size: "10G"             # 超出合理范围
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"controller-config","healthy":"valid","faulty":"invalid"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI072 · CCE Nginx-Ingress访问异常

- **目录**：`cases/otel-k8s-tci072-session-affinity/`
- **原始根因**：关闭Ingress的affinity配置
- **语义资源**：`Ingress/frontend`
- **实现参数**：`strategy=service, component=frontendproxy, fault=affinity, faulty=None`
- **保真类型**：真实服务发现故障
- **语义状态**：`session_affinity: cookie -> none`

**原始建议手段**

```text
annotations:
  nginx.ingress.kubernetes.io/affinity: "none"  # 显式关闭
```

**当前真实注入**

直接修改或删除 Demo Service，造成错误 selector、targetPort、sessionAffinity、Service 类型或服务缺失。

具体参数为 `{"strategy":"service","component":"frontendproxy","fault":"affinity","healthy":"ClientIP","faulty":"None"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Service spec/存在性和 Endpoints；修复后目标值恢复且端点重新可用。

### TCI073 · CCE Nginx-Ingress访问异常

- **目录**：`cases/otel-k8s-tci073-service-selector/`
- **原始根因**：删除后端Service的Selector标签
- **语义资源**：`Service/frontend`
- **实现参数**：`strategy=service, component=frontend, fault=selector, faulty=missing-backend`
- **保真类型**：真实服务发现故障
- **语义状态**：`service_selector: matched -> missing`

**原始建议手段**

```text
kubectl edit svc <service-name> -n <namespace>
# 修改selector为不存在的标签，如 app=non-existent
```

**当前真实注入**

直接修改或删除 Demo Service，造成错误 selector、targetPort、sessionAffinity、Service 类型或服务缺失。

具体参数为 `{"strategy":"service","component":"frontend","fault":"selector","healthy":"frontend","faulty":"missing-backend"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Service spec/存在性和 Endpoints；修复后目标值恢复且端点重新可用。

### TCI074 · CCE Nginx-Ingress访问异常

- **目录**：`cases/otel-k8s-tci074-rewrite-target/`
- **原始根因**：错误配置路径重写规则
- **语义资源**：`Ingress/frontend`
- **实现参数**：`strategy=ingress, fault=path, faulty=/invalid-path`
- **保真类型**：真实 Ingress 配置故障
- **语义状态**：`rewrite_target: / -> /invalid-path`

**原始建议手段**

```text
annotations:
  nginx.ingress.kubernetes.io/rewrite-target: /invalid-path
```

**当前真实注入**

创建并修改 networking.k8s.io/v1 Ingress 的 path 或 ssl-redirect annotation。

具体参数为 `{"strategy":"ingress","fault":"path","healthy":"/","faulty":"/invalid-path"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查真实 Ingress spec/annotation；修复后恢复健康值。

### TCI075 · CCE Nginx-Ingress访问异常

- **目录**：`cases/otel-k8s-tci075-service-port/`
- **原始根因**：通过K8s Service覆盖ELB配置
- **语义资源**：`Service/frontend-proxy`
- **实现参数**：`strategy=service, component=frontendproxy, fault=target_port, faulty=9999`
- **保真类型**：真实服务发现故障
- **语义状态**：`service_port: 80 -> 8080`

**原始建议手段**

```text
apiVersion: v1
kind: Service
metadata:
  annotations:
    kubernetes.io/elb.port: "8080"  # 非标端口
spec:
  ports:
  - port: 80
    targetPort: 8080
```

**当前真实注入**

直接修改或删除 Demo Service，造成错误 selector、targetPort、sessionAffinity、Service 类型或服务缺失。

具体参数为 `{"strategy":"service","component":"frontendproxy","fault":"target_port","healthy":8080,"faulty":9999}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Service spec/存在性和 Endpoints；修复后目标值恢复且端点重新可用。

### TCI076 · CCE Nginx-Ingress访问异常

- **目录**：`cases/otel-k8s-tci076-controller-image/`
- **原始根因**：创建的nginx状态非正常
- **语义资源**：`Deployment/ingress-nginx-controller`
- **实现参数**：`strategy=deployment, component=frontendproxy, fault=image`
- **保真类型**：真实工作负载变更
- **语义状态**：`controller_image: valid -> invalid`

**原始建议手段**

```text
配置一个错误的nginx镜像
```

**当前真实注入**

直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。

具体参数为 `{"strategy":"deployment","component":"frontendproxy","fault":"image"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。

### TCI077 · CCE域名解析失败

- **目录**：`cases/otel-k8s-tci077-coredns-kubernetes-plugin/`
- **原始根因**：修改CoreDNS配置（模拟配置错误）
- **语义资源**：`ConfigMap/coredns`
- **实现参数**：`strategy=config_probe, key=coredns-kubernetes-plugin, faulty=removed`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`coredns_kubernetes_plugin: enabled -> removed`

**原始建议手段**

```text
kubectl -n kube-system edit configmap coredns
# 删除或注释掉`kubernetes cluster.local in-addr.arpa ip6.arpa`配置段
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"coredns-kubernetes-plugin","healthy":"enabled","faulty":"removed"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI078 · CCE域名解析失败

- **目录**：`cases/otel-k8s-tci078-dns-ingress/`
- **原始根因**：注入网络策略（禁止DNS查询）
- **语义资源**：`NetworkPolicy/coredns`
- **实现参数**：`strategy=network_policy, component=otelcol, fault=deny_ingress`
- **保真类型**：真实网络策略
- **语义状态**：`dns_ingress: allowed -> denied`

**原始建议手段**

```text
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-dns
  namespace: kube-system
spec:
  podSelector:
    matchLabels:
      k8s-app: kube-dns
  policyTypes: ["Ingress"]
  ingress: []  # 空规则表示拒绝所有入站
EOF
```

**当前真实注入**

创建 networking.k8s.io/v1 NetworkPolicy，对目标工作负载实施 ingress/egress 隔离。策略是否丢包由集群 CNI 执行。

具体参数为 `{"strategy":"network_policy","component":"otelcol","fault":"deny_ingress"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 NetworkPolicy 存在；修复时删除策略并确认资源消失。

### TCI079 · CCE域名解析失败

- **目录**：`cases/otel-k8s-tci079-nodelocaldns-upstream/`
- **原始根因**：修改NodeLocal DNS缓存配置
- **语义资源**：`ConfigMap/nodelocaldns`
- **实现参数**：`strategy=config_probe, key=dns-upstream, faulty=127.0.0.1:9999`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`nodelocaldns_upstream: kube-dns -> 127.0.0.1:9999`

**原始建议手段**

```text
kubectl -n kube-system edit configmap nodelocaldns
# 将上游DNS服务器改为无效地址（如：`forward . 127.0.0.1:9999`）
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"dns-upstream","healthy":"kube-dns","faulty":"127.0.0.1:9999"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI080 · CCE域名解析失败

- **目录**：`cases/otel-k8s-tci080-dns-egress-udp-53/`
- **原始根因**：VPC层面修改路由表（阻断53端口）
- **语义资源**：`ConfigMap/vpc-dns-policy`
- **实现参数**：`strategy=network_policy, component=loadgenerator, fault=deny_egress`
- **保真类型**：真实网络策略
- **语义状态**：`dns_egress_udp_53: allowed -> denied`

**原始建议手段**

```text
登录 华为云控制台
进入 VPC 服务 > 安全组
找到目标安全组 sg-xxxx，点击 "配置规则"
在 "出方向规则" 页签，点击 "添加规则"
按如下参数填写：
协议端口：UDP，端口填 53
目的地址：0.0.0.0/0
策略：拒绝
（可选）优先级：建议设置为高优先级（数值调小，如 1）
```

**当前真实注入**

创建 networking.k8s.io/v1 NetworkPolicy，对目标工作负载实施 ingress/egress 隔离。策略是否丢包由集群 CNI 执行。

具体参数为 `{"strategy":"network_policy","component":"loadgenerator","fault":"deny_egress"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 NetworkPolicy 存在；修复时删除策略并确认资源消失。

### TCI081 · CCE域名解析失败

- **目录**：`cases/otel-k8s-tci081-coredns-cpu-limit/`
- **原始根因**：限制DNS Pod资源（模拟性能不足）
- **语义资源**：`Deployment/coredns`
- **实现参数**：`strategy=stress, mode=dns, target=kube-dns`
- **保真类型**：直接负载注入
- **语义状态**：`coredns_cpu_limit: 200m -> 50m`

**原始建议手段**

```text
kubectl -n kube-system patch deployment coredns \
  --patch '{"spec":{"template":{"spec":{"containers":[{"name":"coredns","resources":{"limits":{"cpu":"50m","memory":"64Mi"}}}]}}}}'
```

**当前真实注入**

创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。

具体参数为 `{"strategy":"stress","mode":"dns","target":"kube-dns"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。

### TCI082 · CCE域名解析失败

- **目录**：`cases/otel-k8s-tci082-dns-query-rate/`
- **原始根因**：注入高负载流量
- **语义资源**：`Job/dns-stress-test`
- **实现参数**：`strategy=stress, mode=dns, target=kube-dns`
- **保真类型**：直接负载注入
- **语义状态**：`dns_query_rate: normal -> overloaded`

**原始建议手段**

```text
kubectl apply -f - <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: dns-stress-test
spec:
  template:
    spec:
      containers:
      - name: query
        image: alpine
        command: ["sh", "-c", "while true; do dig @coredns.kube-system.svc.cluster.local example.com; done"]
      restartPolicy: Never
EOF
```

**当前真实注入**

创建有资源上限的故障 Pod，实际执行 CPU 忙循环、内存分配、持续 fsync 写盘、网络请求、连接或 DNS 查询。

具体参数为 `{"strategy":"stress","mode":"dns","target":"kube-dns"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

故障 Pod 处于 Running/Pending；修复时删除该负载并确认资源消失。

### TCI083 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci083-backend-replicas/`
- **原始根因**：模拟后端服务不可用
- **语义资源**：`Deployment/checkout`
- **实现参数**：`strategy=deployment, component=checkoutservice, fault=replicas, faulty=0`
- **保真类型**：真实工作负载变更
- **语义状态**：`backend_replicas: 2 -> 0`

**原始建议手段**

```text
kubectl scale deployment <backend-deployment> --replicas=0 -n <namespace>
```

**当前真实注入**

直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。

具体参数为 `{"strategy":"deployment","component":"checkoutservice","fault":"replicas","healthy":1,"faulty":0}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。

### TCI084 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci084-backend-memory-limit/`
- **原始根因**：注入Pod资源超限
- **语义资源**：`Deployment/checkout`
- **实现参数**：`strategy=deployment, component=checkoutservice, fault=memory_limit, faulty=10Mi`
- **保真类型**：真实工作负载变更
- **语义状态**：`backend_memory_limit: 256Mi -> 10Mi`

**原始建议手段**

```text
# 修改Deployment资源限制触发OOM
resources:
  limits:
    cpu: "10m"
    memory: "10Mi"
```

**当前真实注入**

直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。

具体参数为 `{"strategy":"deployment","component":"checkoutservice","fault":"memory_limit","healthy":"128Mi","faulty":"10Mi"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。

### TCI085 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci085-upstream-retries/`
- **原始根因**：配置错误的重试策略（过低的重试次数）
- **语义资源**：`Ingress/frontend`
- **实现参数**：`strategy=config_probe, key=upstream-retries, faulty=1`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`upstream_retries: 3 -> 1`

**原始建议手段**

```text
annotations:
  nginx.ingress.kubernetes.io/proxy-next-upstream: "error timeout http_502"
  nginx.ingress.kubernetes.io/proxy-next-upstream-tries: "1"
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"upstream-retries","healthy":"3","faulty":"1"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI086 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci086-ingress-path/`
- **原始根因**：错误配置路径规则
- **语义资源**：`Ingress/frontend`
- **实现参数**：`strategy=ingress, fault=path, faulty=/wrong-path`
- **保真类型**：真实 Ingress 配置故障
- **语义状态**：`ingress_path: / -> /wrong-path`

**原始建议手段**

```text
spec:
  rules:
  - http:
      paths:
      - path: /wrong-path  # 错误路径
        backend:
          serviceName: <service-name>
          servicePort: 80
```

**当前真实注入**

创建并修改 networking.k8s.io/v1 Ingress 的 path 或 ssl-redirect annotation。

具体参数为 `{"strategy":"ingress","fault":"path","healthy":"/","faulty":"/wrong-path"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查真实 Ingress spec/annotation；修复后恢复健康值。

### TCI087 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci087-backend-service/`
- **原始根因**：删除后端Service
- **语义资源**：`Service/checkout`
- **实现参数**：`strategy=service, component=checkoutservice, fault=delete, faulty=deleted`
- **保真类型**：真实服务发现故障
- **语义状态**：`backend_service: present -> deleted`

**原始建议手段**

```text
kubectl delete svc <service-name> -n <namespace>
```

**当前真实注入**

直接修改或删除 Demo Service，造成错误 selector、targetPort、sessionAffinity、Service 类型或服务缺失。

具体参数为 `{"strategy":"service","component":"checkoutservice","fault":"delete","healthy":"present","faulty":"deleted"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Service spec/存在性和 Endpoints；修复后目标值恢复且端点重新可用。

### TCI088 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci088-backend-latency/`
- **原始根因**：模拟网络延迟
- **语义资源**：`Pod/checkout`
- **实现参数**：`strategy=proxy, mode=latency, component=checkoutservice`
- **保真类型**：真实数据面故障
- **语义状态**：`backend_latency: 0ms -> 500ms`

**原始建议手段**

```text
# 在Pod中注入tc命令
tc qdisc add dev eth0 root netem delay 500ms
```

**当前真实注入**

创建 TCP 故障代理和保留原后端 selector 的上游 Service，再把业务 Service selector 切到代理；代理按 case 实际增加 500ms 延迟、约 50% 连接丢弃或 16KiB/s 限速。

具体参数为 `{"strategy":"proxy","component":"checkoutservice","mode":"latency"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查代理 Pod Running、Service 已选择代理且 Endpoints 可用；修复后 Service 必须重新选择原组件并恢复端点。

### TCI089 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci089-ingress-cpu-limit/`
- **原始根因**：限制Ingress Controller资源（人为制造CPU瓶颈）
- **语义资源**：`Deployment/ingress-controller`
- **实现参数**：`strategy=deployment, component=frontendproxy, fault=cpu_limit, faulty=100m`
- **保真类型**：真实工作负载变更
- **语义状态**：`ingress_cpu_limit: 500m -> 100m`

**原始建议手段**

```text
resources:
  limits:
    cpu: "100m"
```

**当前真实注入**

直接 patch OpenTelemetry Demo Deployment 的镜像、启动命令、资源限制、副本数、安全上下文或调度约束，触发真实滚动更新、CrashLoop、ImagePullBackOff、OOM/限流或 Pending。

具体参数为 `{"strategy":"deployment","component":"frontendproxy","fault":"cpu_limit","healthy":null,"faulty":"100m"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Deployment spec 与可用副本；修复后 spec 回到基线且 Deployment Ready。

### TCI090 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci090-ssl-redirect/`
- **原始根因**：配置冲突的Annotations
- **语义资源**：`Ingress/frontend`
- **实现参数**：`strategy=ingress, fault=ssl_redirect, faulty=false`
- **保真类型**：真实 Ingress 配置故障
- **语义状态**：`ssl_redirect: true -> false`

**原始建议手段**

```text
annotations:
  kubernetes.io/ingress.class: "nginx"
  nginx.ingress.kubernetes.io/ssl-redirect: "false"  # 与全局配置冲突
```

**当前真实注入**

创建并修改 networking.k8s.io/v1 Ingress 的 path 或 ssl-redirect annotation。

具体参数为 `{"strategy":"ingress","fault":"ssl_redirect","healthy":"true","faulty":"false"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查真实 Ingress spec/annotation；修复后恢复健康值。

### TCI091 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci091-tls-certificate/`
- **原始根因**：过期证书不轮换
- **语义资源**：`Secret/frontend-tls`
- **实现参数**：`strategy=config_probe, key=tls-certificate, faulty=expired`
- **保真类型**：配置驱动的真实失败
- **语义状态**：`tls_certificate: valid -> expired`

**原始建议手段**

```text
# 手动修改Secret过期时间
kubectl edit secret <tls-secret> -n <namespace>
```

**当前真实注入**

创建独立配置消费者 Deployment；注入错误配置后重启消费者，使其实际校验失败并进入 CrashLoopBackOff，而不是只记录一个状态值。

具体参数为 `{"strategy":"config_probe","key":"tls-certificate","healthy":"valid","faulty":"expired"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

同时检查配置值和消费者不可用；修复配置后消费者必须重新 Ready。

### TCI092 · CCE ELB-Ingress异常

- **目录**：`cases/otel-k8s-tci092-elb-eip/`
- **原始根因**：ELB状态异常（不绑定EIP）
- **语义资源**：`Service/frontend-proxy`
- **实现参数**：`strategy=service, component=frontendproxy, fault=type, faulty=LoadBalancer`
- **保真类型**：真实服务发现故障
- **语义状态**：`elb_eip: bound -> unbound`

**原始建议手段**

```text
创建一个ELB，不绑定EIP
```

**当前真实注入**

直接修改或删除 Demo Service，造成错误 selector、targetPort、sessionAffinity、Service 类型或服务缺失。

具体参数为 `{"strategy":"service","component":"frontendproxy","fault":"type","healthy":"ClusterIP","faulty":"LoadBalancer"}`。
注入后还会写 Warning Event 与 `otel-demo-alert-context` 作为诊断线索，但二者不作为注入成功或评分依据。注入对象使用名称中性的工作负载名称和常规应用标签，不暴露 case id 或 `fault=true` 标签。

**检查与修复条件**

检查 Service spec/存在性和 Endpoints；修复后目标值恢复且端点重新可用。

## 6. 保真度边界

- CPU、内存、磁盘 I/O、磁盘占用、连接和 DNS 压力会执行真实消耗命令，并设置 requests/limits 与 namespace 隔离。
- Deployment、Service、Ingress、Secret、ResourceQuota、NetworkPolicy 和调度故障均作用于真实 Kubernetes API 对象。
- kubelet/节点 OS/云资源类 case 使用安全等价结果。它们会制造真实不可用状态，但不声称修改了宿主机 kubelet 配置或真实云厂商资源。
- NetworkPolicy 的实际封包执行能力取决于 Minikube CNI；资源对象与修复判据始终真实，后续可在基准集群启用 Calico/Cilium 进一步验证数据面阻断。
- 每个注入都必须可由 agent 在其统一权限内修复，并由 cleanup 在异常退出后回收。
- Chart 0.11.0 的 `v1.0.0-featureflagservice` 实际镜像架构为 amd64；在本 benchmark 的 ARM64 Minikube 中经模拟执行会段错误。Pod 带有 `demo.open-telemetry.io/baseline-known-issue=amd64-image-on-arm64` 注解，且不作为 case 故障证据。

本文档由 `tools/generate_fault_injection_docs.py` 生成。修改目录后运行：

```bash
python3 tools/generate_kubernetes_cases.py
python3 tools/generate_fault_injection_docs.py
```
