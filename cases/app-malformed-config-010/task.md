# OpsBench Task: Application Fails During Startup

The target container remains running, but the HTTP application exits during
startup. The generated base JSON is still syntactically valid; startup also
consumes a versioned release overlay, and a failed start may leave process
control state behind.

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

The benchmark independently validates both configuration layers, confirms the
service is genuinely running after recovery, and checks HTTP 200 from the main
health endpoint. The target container must remain running.
