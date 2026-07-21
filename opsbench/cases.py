from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from opsbench.agent_tools import tool_names_for_standard


class CaseManifestError(ValueError):
    """Raised when a case manifest is missing required fields or is invalid."""


@dataclass(frozen=True)
class Case:
    id: str
    domain: str
    case_dir: Path
    compose_file: Path
    environment_type: str
    services: list[str]
    scripts: dict[str, Path]
    task_file: Path
    hidden_metadata: Path
    agent_timeout_sec: int
    namespace_prefix: str
    tool_standard: dict[str, Any]
    raw_manifest: dict[str, Any]


REQUIRED_TOP_LEVEL_KEYS = {
    "id",
    "domain",
    "environment",
    "scripts",
    "task",
    "hidden_metadata",
}

REQUIRED_SCRIPT_KEYS = {"inject", "check_injected", "verify"}
OPTIONAL_SCRIPT_KEYS = {"setup", "cleanup"}
SUPPORTED_ENVIRONMENT_TYPES = {"compose", "kubernetes"}


def load_case(case_dir: str | Path) -> Case:
    resolved_case_dir = Path(case_dir).resolve()
    manifest_path = resolved_case_dir / "manifest.yaml"
    manifest = _load_json_compatible_yaml(manifest_path)
    _require_keys(manifest, REQUIRED_TOP_LEVEL_KEYS, manifest_path)

    environment = _require_mapping(manifest, "environment", manifest_path)
    environment_type = environment.get("type", "compose")
    if environment_type not in SUPPORTED_ENVIRONMENT_TYPES:
        raise CaseManifestError(
            f"{manifest_path}: environment.type must be one of "
            f"{', '.join(sorted(SUPPORTED_ENVIRONMENT_TYPES))}"
        )
    scripts = _require_mapping(manifest, "scripts", manifest_path)
    _require_keys(scripts, REQUIRED_SCRIPT_KEYS, manifest_path)

    compose_file = _resolve_child(
        resolved_case_dir,
        _require_string(environment, "compose_file", manifest_path),
    )
    task_file = _resolve_child(
        resolved_case_dir,
        _require_string(manifest, "task", manifest_path),
    )
    hidden_metadata = _resolve_child(
        resolved_case_dir,
        _require_string(manifest, "hidden_metadata", manifest_path),
    )
    script_paths = {
        name: _resolve_child(resolved_case_dir, _require_string(scripts, name, manifest_path))
        for name in REQUIRED_SCRIPT_KEYS
    }
    for name in OPTIONAL_SCRIPT_KEYS:
        if name in scripts:
            script_paths[name] = _resolve_child(
                resolved_case_dir,
                _require_string(scripts, name, manifest_path),
            )

    tool_standard = _require_mapping(manifest, "tool_standard", manifest_path)
    tool_id = _require_string(tool_standard, "id", manifest_path)
    tools = tool_standard.get("tools")
    commands = tool_standard.get("commands", [])
    try:
        expected_tools = list(tool_names_for_standard(tool_id))
    except ValueError as exc:
        raise CaseManifestError(f"{manifest_path}: {exc}") from exc
    if tools != expected_tools:
        raise CaseManifestError(
            f"{manifest_path}: tool_standard.tools must be exactly {expected_tools!r} "
            f"for {tool_id}"
        )
    if not isinstance(commands, list) or not all(
        isinstance(command, str) and command for command in commands
    ):
        raise CaseManifestError(
            f"{manifest_path}: tool_standard.commands must be a list of strings"
        )

    timeouts = manifest.get("timeouts", {})
    if timeouts is None:
        timeouts = {}
    if not isinstance(timeouts, dict):
        raise CaseManifestError(f"{manifest_path}: timeouts must be an object")

    return Case(
        id=_require_string(manifest, "id", manifest_path),
        domain=_require_string(manifest, "domain", manifest_path),
        case_dir=resolved_case_dir,
        compose_file=compose_file,
        environment_type=environment_type,
        services=list(environment.get("services", [])),
        scripts=script_paths,
        task_file=task_file,
        hidden_metadata=hidden_metadata,
        agent_timeout_sec=int(timeouts.get("agent_sec", 300)),
        namespace_prefix=str(environment.get("namespace_prefix", "opsbench")),
        tool_standard={"id": tool_id, "tools": tools, "commands": commands},
        raw_manifest=manifest,
    )


def load_hidden_labels(case: Case) -> dict[str, Any]:
    return _load_json_compatible_yaml(case.hidden_metadata)


def _load_json_compatible_yaml(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaseManifestError(f"{path}: file not found") from exc
    except json.JSONDecodeError as exc:
        raise CaseManifestError(
            f"{path}: must be JSON-compatible YAML ({exc.msg})"
        ) from exc

    if not isinstance(data, dict):
        raise CaseManifestError(f"{path}: top-level document must be an object")
    return data


def _require_keys(data: dict[str, Any], keys: set[str], path: Path) -> None:
    missing = sorted(key for key in keys if key not in data)
    if missing:
        raise CaseManifestError(f"{path}: missing required key(s): {', '.join(missing)}")


def _require_mapping(data: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise CaseManifestError(f"{path}: {key} must be an object")
    return value


def _require_string(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise CaseManifestError(f"{path}: {key} must be a non-empty string")
    return value


def _resolve_child(parent: Path, child: str) -> Path:
    path = Path(child)
    resolved = path.resolve() if path.is_absolute() else (parent / path).resolve()
    if not resolved.is_relative_to(parent):
        raise CaseManifestError(
            f"{parent}: referenced path must stay inside the case directory: {child}"
        )
    return resolved
