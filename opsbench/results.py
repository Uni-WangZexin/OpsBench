from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def append_run(path: str | Path, record: dict[str, Any]) -> None:
    results_path = Path(path)
    results_path.parent.mkdir(parents=True, exist_ok=True)
    with results_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def load_runs(path: str | Path) -> list[dict[str, Any]]:
    results_path = Path(path)
    if not results_path.exists():
        return []

    runs: list[dict[str, Any]] = []
    with results_path.open(encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                runs.append(json.loads(stripped))
    return runs
