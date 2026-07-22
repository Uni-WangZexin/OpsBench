# Lightweight Container Fault Cases

Cases 002-021 each start one resource-bounded Debian target container. The
evaluated Agent process runs directly in that target container after fault
injection. Injection and verification remain benchmark-side operations.

Common target limits: 1.00 CPU, 384 MiB memory, 128 PIDs, a 24 MiB
data tmpfs, and an 8 MiB temporary tmpfs. The application process is
separately capped at 64 file descriptors for the FD exhaustion case.

| Case | Domain | Strategy | Real injection and verification |
| --- | --- | --- | --- |
| `linux-cpu-runaway-002` | linux | `cpu_runaway` | Start a real SHA-256 compute loop; verify CPU time advances and later falls below the recovery threshold. |
| `linux-memory-growth-003` | linux | `memory_growth` | Start a process that allocates and retains 72 MiB; verify its live RSS and later disappearance. |
| `linux-fd-exhaustion-004` | linux | `fd_leak` | Enable a real application descriptor leak under a nofile limit of 64 and exercise the affected endpoint. |
| `linux-disk-full-005` | filesystem | `disk_full` | Fill the data tmpfs with an unlinked file that remains open in a live process; df is full while du cannot see the owner. |
| `linux-inode-exhaustion-006` | filesystem | `inode_full` | Create small files until the tmpfs inode limit rejects another file even though byte capacity remains. |
| `linux-upload-permission-007` | filesystem | `upload_permission` | Remove write access for the non-root service user and verify a real upload fails. |
| `http-wrong-port-008` | network | `wrong_port` | Restart the application on 8081 while clients continue to use the published contract on 8080. |
| `http-loopback-bind-009` | network | `loopback_bind` | Bind the application to 127.0.0.1 so local probes pass but peer-container traffic fails. |
| `app-malformed-config-010` | configuration | `malformed_config` | Install malformed runtime JSON and exercise the real startup parser failure path. |
| `app-stale-pid-011` | process | `stale_pid` | Leave a stale PID file that causes the service control command to reject a new start. |
| `http-dependency-dns-012` | network | `dependency_dns` | Configure a non-resolving dependency hostname and verify the order request returns 502. |
| `http-dependency-port-013` | network | `dependency_port` | Point the client at a closed dependency port while the downstream process remains healthy. |
| `http-downstream-500-014` | distributed_system | `dependency_status` | Remove the downstream service user's access to its live catalog data so it returns HTTP 500. |
| `http-downstream-json-015` | distributed_system | `dependency_payload` | Corrupt the downstream catalog data file so the caller receives malformed JSON over a successful HTTP response. |
| `http-upstream-timeout-016` | distributed_system | `dependency_timeout` | Delay the downstream for 900 ms while the caller times out after 150 ms. |
| `app-feature-flag-017` | configuration | `feature_flag` | Enable a known-incompatible checkout code path and verify only checkout fails. |
| `linux-file-lock-018` | process | `file_lock` | Start a real process holding an advisory lock required by report generation. |
| `linux-temp-permission-019` | filesystem | `temp_permission` | Remove write access from the service temporary directory and exercise file creation. |
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
