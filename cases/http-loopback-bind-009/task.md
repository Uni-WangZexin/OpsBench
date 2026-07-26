# OpsBench Task: API Works Locally But Not Across The Network

The service responds through 127.0.0.1 but requests addressed to the target's
network identity fail on port 8080. The running process already reports a
wildcard listener, so changing the application bind value is not a valid fix.

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

The benchmark independently verifies both loopback and network-identity access,
the wildcard application binding, removal of the underlying packet-path fault,
and HTTP 200 from the main health endpoint. The target container must remain
running.
