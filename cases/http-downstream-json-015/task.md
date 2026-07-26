# OpsBench Task: Catalog Response Violates Its Contract

The catalog endpoint returns syntactically valid JSON, but GET /orders returns
502 because the response does not satisfy the catalog contract. The caller
expects a readiness value and a positive numeric item count; do not weaken its
schema validation.

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

The benchmark independently verifies that the catalog response has the expected
semantics, order requests work again within the normal latency budget, and the
main health endpoint returns HTTP 200. The target container must remain running.
