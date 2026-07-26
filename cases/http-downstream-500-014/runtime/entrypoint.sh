#!/bin/sh
set -eu

mkdir -p /etc/opsbench/tls /var/log/demo /var/lib/catalog \
  /data/.stores/upload-primary /var/cache/demo/jobs \
  /var/lib/opsbench/control/releases /var/lib/opsbench/app-config/releases
chmod 0777 /data
rm -rf /data/uploads /tmp/app-cache
ln -s /data/.stores/upload-primary /data/uploads
ln -s /var/cache/demo/jobs /tmp/app-cache
chown root:demo /data/.stores/upload-primary /var/cache/demo/jobs
chmod 2770 /data/.stores/upload-primary
chmod 3770 /var/cache/demo/jobs
cp /opt/opsbench/runtime/default-config.json /etc/opsbench/app.json
cp /opt/opsbench/runtime/default-dependency.json /etc/opsbench/dependency.json
printf '%s\n' '{"revision":"2026-07-stable","listener_port":8080,"feature_checkout_v2":false}' \
  >/var/lib/opsbench/control/releases/2026-07-stable.json
ln -s releases/2026-07-stable.json /var/lib/opsbench/control/current
printf '%s\n' '{}' >/var/lib/opsbench/app-config/releases/2026-07-stable.json
ln -s releases/2026-07-stable.json /var/lib/opsbench/app-config/current
cp /opt/opsbench/certs/target.crt /etc/opsbench/tls/server.crt
cp /opt/opsbench/certs/target.key /etc/opsbench/tls/server.key
cp /opt/opsbench/certs/ca.crt /etc/opsbench/ca.crt
printf '%s\n' '{"catalog":"ready","items":3}' >/var/lib/catalog/catalog.json
sed '/[[:space:]]catalog\.internal$/d' /etc/hosts >/tmp/opsbench-hosts
cat /tmp/opsbench-hosts >/etc/hosts
printf '%s\n' '127.0.0.1 catalog.internal' >>/etc/hosts
touch /run/report.lock
chown -R demo:demo /var/log/demo /etc/opsbench/tls /var/lib/catalog /run/report.lock
chmod 0640 /var/lib/catalog/catalog.json
rm -f /etc/opsbench/app.env /etc/opsbench/dependency.env \
  /run/demo-app.pid /run/catalog.pid /run/config-reconciler.pid /run/system-report.pid \
  /run/system-report-supervisor.pid /run/system-report.enabled \
  /run/report-holder.pid /run/report-supervisor.pid /run/report-worker.enabled

/opt/opsbench/runtime/dependencyctl.sh start
/opt/opsbench/runtime/appctl.sh start
nohup python3 /opt/opsbench/runtime/config-reconciler.pyc \
  >>/var/log/demo/config-reconciler-process.log 2>&1 </dev/null &
echo $! >/run/config-reconciler.pid
rm -f /opt/opsbench/runtime/default-config.json /opt/opsbench/runtime/default-dependency.json

trap '/opt/opsbench/runtime/appctl.sh stop; /opt/opsbench/runtime/dependencyctl.sh stop; exit 0' TERM INT
while true; do sleep 3600 & wait $!; done
