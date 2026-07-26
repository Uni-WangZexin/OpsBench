# OpsBench Task: Order Requests Cannot Connect Downstream

Health checks pass, but GET /orders returns 502 while the catalog process
remains alive on an unexpected listener. The catalog service contract is port
9001; repointing the caller to a drifted process port is not an acceptable fix.

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

The benchmark independently verifies the catalog process and caller both use
the 9001 contract, the drifted listener is gone, orders work again, and the main
health endpoint returns HTTP 200.
