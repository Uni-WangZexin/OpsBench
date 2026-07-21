# OpsBench Task: TCI048 CCE Node节点状态异常

The OpenTelemetry Demo environment is reporting an operational incident in its
dedicated Kubernetes namespace. Diagnose the cause from live Kubernetes state
and restore the affected resource to a healthy condition.

## Observed Symptom

CCE Node节点状态异常：OpenTelemetry Demo 服务状态异常

Use the namespace and command-line clients supplied in the runtime context.
Do not delete the namespace, reinstall the Helm release, or access benchmark
control files. Make the smallest in-place repair and summarize your evidence.

## Success Criteria

The benchmark independently checks that the namespace remains available and
that the injected resource state has been repaired.
