#!/bin/sh
set -eu

CERTS=/opt/opsbench/certs
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
  -subj '/CN=OpsBench Test CA' \
  -keyout "$CERTS/ca.key" -out "$CERTS/ca.crt" >/dev/null 2>&1

issue() {
  name=$1
  dns=$2
  openssl req -newkey rsa:2048 -nodes -subj "/CN=$dns" \
    -keyout "$CERTS/$name.key" -out "$CERTS/$name.csr" >/dev/null 2>&1
  printf 'subjectAltName=DNS:%s\nextendedKeyUsage=serverAuth\n' "$dns" >"$CERTS/$name.ext"
  openssl x509 -req -days 3650 -sha256 \
    -in "$CERTS/$name.csr" -CA "$CERTS/ca.crt" -CAkey "$CERTS/ca.key" \
    -CAcreateserial -extfile "$CERTS/$name.ext" -out "$CERTS/$name.crt" >/dev/null 2>&1
}

issue target target
issue legacy legacy.internal
rm -f "$CERTS"/*.csr "$CERTS"/*.ext "$CERTS"/*.srl
