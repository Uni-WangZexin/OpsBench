# OpsBench Task: Order Requests Cannot Resolve Their Dependency

Health checks pass, but GET /orders returns 502 and dependency CPU usage is
normal. The catalog's stable service-discovery name is part of the public
contract and must not be replaced with a literal address in application config.

Diagnose the live target container and apply the smallest durable repair. Do not
work around the symptom by disabling validation or repeatedly restarting the
service without correcting the underlying state.

## Runtime Access

The evaluated agent process is already running inside the lightweight target
container. Shell commands execute directly in the same PID, network, cgroup and
filesystem environment as the affected services; do not use SSH or Docker.

The public service contract expects HTTP on port `8080` and HTTPS on port
`8443`. Normal Linux process, socket, filesystem, HTTP and TLS diagnostic tools
are installed in the target. Discover the effective runtime configuration,
logs and process-control mechanism from live state; their internal paths and
precedence are intentionally not supplied here.

## Success Criteria

The benchmark independently verifies the catalog name resolves to the local
service, the caller still uses that stable identity, orders meet their latency
budget, and the main health endpoint returns HTTP 200.
