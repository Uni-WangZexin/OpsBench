# OpsBench Task: Catalog Dependency Returns Server Errors

The main API is healthy, but order requests fail because the local catalog
dependency cannot read its catalog data. The catalog contains internal data and
must remain owned by the service account without granting access to all users.

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

The benchmark independently verifies that order requests work again within the
normal latency budget, catalog ownership and least-privilege access are
restored, and the main health endpoint returns HTTP 200. The target container
must remain running.
