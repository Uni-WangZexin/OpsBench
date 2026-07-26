# OpsBench Task: Temporary Jobs Cannot Create Files

GET /temp fails while ordinary health and read requests continue to work. The
configured path is an alias to a group-shared job store that requires inherited
group ownership and sticky deletion semantics; it must not become world
accessible.

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

The benchmark independently verifies temporary job creation, the stable path
mapping, platform/service-group ownership, setgid and sticky semantics, no
world access, and HTTP 200 from the main health endpoint.
