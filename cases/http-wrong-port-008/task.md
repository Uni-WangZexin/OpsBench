# OpsBench Task: API Is Missing From Its Published Port

Clients cannot connect to the API on port 8080 even though an application
process is running. Listener settings are reconciled from a desired-state
source, so editing only the generated application configuration is temporary.

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

The benchmark independently verifies the desired state and effective listener,
confirms the reconciler remains healthy, rejects the unintended listener, and
checks HTTP 200 from the main health endpoint. The target container must remain
running.
