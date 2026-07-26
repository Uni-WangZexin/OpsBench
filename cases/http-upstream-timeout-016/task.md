# OpsBench Task: Order Requests Time Out Waiting For Catalog

The catalog eventually responds, but the main API abandons order requests
first. Healthy order requests are expected to finish in under 600 ms; merely
increasing the client timeout enough to wait through the current downstream
delay is not an acceptable repair.

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

The benchmark independently verifies that the downstream delay is returned to
its operating range, order requests succeed in under 600 ms with a consistent
client timeout, and the main health endpoint returns HTTP 200. The target
container must remain running.
