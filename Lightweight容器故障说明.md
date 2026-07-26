# Lightweight Container Fault Cases

Cases 002-021 each start one resource-bounded Debian target container. The
evaluated Agent process runs directly in that target container after fault
injection. Injection and verification remain benchmark-side operations.

Common target limits: 1.00 CPU, 384 MiB memory, 128 PIDs, a 24 MiB
data tmpfs, and an 8 MiB temporary tmpfs. The application process is
separately capped at 64 file descriptors for the FD exhaustion case.

| Case | Domain | Strategy | Real injection and verification |
| --- | --- | --- | --- |
| `linux-cpu-runaway-002` | linux | `cpu_runaway` | Start a supervised SHA-256 compute loop that is relaunched after a child-only kill; verify the lifecycle source and CPU signal are both removed. |
| `linux-memory-growth-003` | linux | `memory_growth` | Start a process that allocates and retains 72 MiB; verify its live RSS and later disappearance. |
| `linux-fd-exhaustion-004` | linux | `fd_leak` | Change the report-template cache scope so the real `/report-template` operation retains one descriptor per request under a nofile limit of 64; verify repeated requests no longer grow the FD set. |
| `linux-disk-full-005` | filesystem | `disk_full` | Fill the data tmpfs with an unlinked file held by a live worker; recovery requires both usable space and removal of the worker that owns the deleted file. |
| `linux-inode-exhaustion-006` | filesystem | `inode_full` | Create small files until the tmpfs inode limit rejects another file even though byte capacity remains. |
| `linux-upload-permission-007` | filesystem | `upload_permission` | Break group access on the backing store behind a stable upload symlink; recovery must restore setgid least privilege without replacing the alias. |
| `http-wrong-port-008` | network | `wrong_port` | Drift centrally reconciled listener desired state to 8081; direct edits to generated app config are reverted. |
| `http-loopback-bind-009` | network | `loopback_bind` | Add a real packet-filter rule that rejects port 8080 via the target network identity while loopback and the wildcard listener remain healthy. |
| `app-malformed-config-010` | configuration | `malformed_config` | Corrupt a versioned effective-config overlay while leaving the generated base JSON valid; recovery must also clear failed-start process state. |
| `app-stale-pid-011` | process | `stale_pid` | Leave a stale PID file that causes the service control command to reject a new start. |
| `http-dependency-dns-012` | network | `dependency_dns` | Poison the stable catalog service-discovery mapping while leaving the caller's hostname configuration correct. |
| `http-dependency-port-013` | network | `dependency_port` | Drift the downstream process itself to 9002 via an environment override while the caller correctly remains on the 9001 contract. |
| `http-downstream-500-014` | distributed_system | `dependency_status` | Remove access to sensitive catalog data; recovery must restore the service owner and least-privilege mode rather than world-readable access. |
| `http-downstream-json-015` | distributed_system | `dependency_payload` | Return syntactically valid JSON with the wrong nested/types schema; recovery must restore semantic compatibility without disabling validation. |
| `http-upstream-timeout-016` | distributed_system | `dependency_timeout` | Delay the downstream for 900 ms while the caller times out after 150 ms; recovery must satisfy the 600 ms request SLO rather than only inflating the timeout. |
| `app-feature-flag-017` | configuration | `feature_flag` | Enable a known-incompatible checkout rollout in reconciled desired state so direct edits to effective app config are temporary. |
| `linux-file-lock-018` | process | `file_lock` | Supervise a real advisory-lock holder so killing only the visible child is temporary; recovery must stop reacquisition. |
| `linux-temp-permission-019` | filesystem | `temp_permission` | Break group access and special mode bits on the backing store behind the temporary-path symlink; require setgid, sticky and no world access. |
| `tls-hostname-mismatch-020` | tls | `tls_hostname` | Serve a CA-valid certificate whose SAN names legacy.internal, remove the ready-made target certificate, and require correct reissuance. |
| `app-env-override-021` | configuration | `environment_override` | Set APP_PORT=8082 so the effective process configuration differs from the JSON file. |

## Agent Boundary

All 20 cases use `linux-operations-v2`: structured logs, processes,
sockets, host metrics, filesystem, HTTP/TLS, file inspection/editing and
service-management tools, plus an audited shell fallback. The Agent runs in the target
container alongside the affected services. It does not receive the case directory, scenario
JSON, injection code, verifier, Docker socket, or host filesystem.
Only the Agent-owned trace subdirectory is mounted at `/trace`; benchmark phase logs
such as setup, injection, and verification output remain outside the container mount.
Model credentials are added only to the Agent process and are not inherited by the service.
Target Python services are compiled during image construction; source files
and healthy bootstrap copies are removed before the Agent starts.

The target contains the live service, logs, runtime configuration and Linux
tools. A valid repair must remove the underlying process, resource, file,
permission, socket, dependency, TLS or effective-configuration signal and
restore the affected user operation plus `/health`.

## Difficulty Calibration

The target pass band is 40%–60% for the pinned `langchain-react-agent` model,
temperature and 60-step budget. It is a calibration target rather than a score
hard-coded into verification: every case remains independently solvable and is
scored only from the repaired live environment. Model or prompt changes require
a fresh 002–021 run before claiming the same band.

The harder cases reject common symptom-only repairs: deleting a PID file,
killing one supervised child, making sensitive data world-readable, accepting
arbitrary parseable JSON, or hiding downstream latency behind a larger client
timeout. Public tasks state the corresponding durability, schema, security and
latency requirements so those checks are not hidden rules.
