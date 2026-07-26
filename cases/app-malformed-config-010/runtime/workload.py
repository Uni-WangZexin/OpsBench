#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import time


def cpu() -> None:
    value = os.urandom(4096)
    while True:
        value = hashlib.sha256(value).digest() * 128


def memory() -> None:
    retained = []
    for _ in range(72):
        block = bytearray(1024 * 1024)
        for offset in range(0, len(block), 4096):
            block[offset] = 1
        retained.append(block)
        time.sleep(0.02)
    while True:
        time.sleep(60)


def storage() -> None:
    path = "/data/.segment-compaction"
    with open(path, "wb", buffering=0) as handle:
        handle.write(b"x" * (23 * 1024 * 1024))
        os.fsync(handle.fileno())
        os.unlink(path)
        while True:
            time.sleep(60)


profile = os.environ.get("REPORT_PROFILE", "")
if profile == "compute":
    cpu()
elif profile == "retention":
    memory()
elif profile == "storage":
    storage()
else:
    raise SystemExit("report profile is not configured")
