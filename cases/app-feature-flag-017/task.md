# OpsBench Task: Checkout Fails For The Enabled Code Path

Health and order requests pass, but GET /checkout consistently returns HTTP
500. Effective rollout flags are reconciled from a desired-state source;
editing only the generated application configuration will be overwritten.

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

The benchmark independently verifies checkout, desired and effective flag
state, continued reconciliation, and HTTP 200 from the main health endpoint.
The target container must remain running.
