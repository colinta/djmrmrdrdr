from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

TAGS_PATH = Path("/etc/musicplayer/tags.yaml")
QUEUE_PATH = Path("/etc/musicplayer/assignment_queue.yaml")
RUNTIME_STATE_PATH = Path("/opt/musicplayer/runtime/state.yaml")


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open() as f:
        data = yaml.safe_load(f)
    return default if data is None else data


def _save_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def load_tags() -> Dict[str, Any]:
    data = _load_yaml(TAGS_PATH, {"tags": {}})
    data.setdefault("tags", {})
    return data


def save_tags(data: Dict[str, Any]) -> None:
    data.setdefault("tags", {})
    _save_yaml(TAGS_PATH, data)


def load_queue() -> Dict[str, List[Dict[str, Any]]]:
    data = _load_yaml(QUEUE_PATH, {"assignment_mode": False, "queue": []})
    data.setdefault("assignment_mode", False)
    data.setdefault("queue", [])
    return data


def save_queue(data: Dict[str, Any]) -> None:
    data.setdefault("assignment_mode", False)
    data.setdefault("queue", [])
    _save_yaml(QUEUE_PATH, data)


def load_runtime_state() -> Dict[str, Any]:
    data = _load_yaml(
        RUNTIME_STATE_PATH,
        {
            "last_scanned_uid": None,
            "last_unknown_uid": None,
            "last_assignment": None,
            "message": "ready",
        },
    )
    data.setdefault("last_scanned_uid", None)
    data.setdefault("last_unknown_uid", None)
    data.setdefault("last_assignment", None)
    data.setdefault("message", "ready")
    return data


def save_runtime_state(data: Dict[str, Any]) -> None:
    _save_yaml(RUNTIME_STATE_PATH, data)
