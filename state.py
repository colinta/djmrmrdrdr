from __future__ import annotations

from pathlib import Path
from typing import NotRequired, TypeVar, TypedDict

import yaml

TAGS_PATH = Path("/etc/musicplayer/tags.yaml")
QUEUE_PATH = Path("/etc/musicplayer/assignment_queue.yaml")
PLAYLISTS_PATH = Path("/etc/musicplayer/playlists.yaml")
RUNTIME_STATE_PATH = Path("/opt/musicplayer/runtime/state.yaml")

T = TypeVar("T")


class TagMapping(TypedDict):
    action: str
    folder: NotRequired[str]
    playlist: NotRequired[str]
    shuffle: NotRequired[bool]


class TagsState(TypedDict):
    tags: dict[str, TagMapping]


class QueueItem(TypedDict):
    action: str
    folder: str


class QueueState(TypedDict):
    assignment_mode: bool
    queue: list[QueueItem]


class LastAssignment(QueueItem):
    uid: str


class Playlist(TypedDict):
    name: str
    tracks: list[str]
    created_at: str
    created_by: str


class RuntimeState(TypedDict):
    last_scanned_uid: str | None
    last_unknown_uid: str | None
    last_assignment: LastAssignment | None
    message: str


def _load_yaml(path: Path, default: T) -> T:
    if not path.exists():
        return default
    with path.open() as f:
        data = yaml.safe_load(f)
    return default if data is None else data


def _save_yaml(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def load_tags() -> TagsState:
    data = _load_yaml(TAGS_PATH, {"tags": {}})
    data.setdefault("tags", {})
    return data


def save_tags(data: TagsState) -> None:
    data.setdefault("tags", {})
    _save_yaml(TAGS_PATH, data)


def load_queue() -> QueueState:
    data = _load_yaml(QUEUE_PATH, {"assignment_mode": False, "queue": []})
    data.setdefault("assignment_mode", False)
    data.setdefault("queue", [])
    return data


def save_queue(data: QueueState) -> None:
    data.setdefault("assignment_mode", False)
    data.setdefault("queue", [])
    _save_yaml(QUEUE_PATH, data)


def load_playlists() -> list[Playlist]:
    data = _load_yaml(PLAYLISTS_PATH, [])
    if not isinstance(data, list):
        return []

    playlists: list[Playlist] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        tracks = item.get("tracks", [])
        created_at = str(item.get("created_at", "")).strip()
        created_by = str(item.get("created_by", "Tory")).strip() or "Tory"
        if not name:
            continue
        if not isinstance(tracks, list):
            tracks = []
        playlists.append({
            "name": name,
            "tracks": [str(track) for track in tracks if str(track).strip()],
            "created_at": created_at,
            "created_by": created_by,
        })
    return playlists


def save_playlists(data: list[Playlist]) -> None:
    _save_yaml(PLAYLISTS_PATH, data)


def load_runtime_state() -> RuntimeState:
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


def save_runtime_state(data: RuntimeState) -> None:
    _save_yaml(RUNTIME_STATE_PATH, data)
