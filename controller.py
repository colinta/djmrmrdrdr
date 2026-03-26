from __future__ import annotations

import signal
from pathlib import Path
from typing import Any, Dict

import yaml

from buttons import Buttons
from nfc_reader import NFCReader
from player import MusicPlayer

CONFIG_PATH = Path("/etc/musicplayer/tags.yaml")


class Controller:
    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self.config_path = config_path
        self.player = MusicPlayer()
        self.config = self._load_config()
        self.active_tag_uid: str | None = None
        self.paused_by_tag_removal = False
        # Temporarily disable tag-removal pause/resume behavior during testing.
        # To restore it later, pass on_removed=self.on_tag_removed again.
        self.nfc_reader = NFCReader(callback=self.on_tag)
        self.buttons = Buttons(
            on_toggle_pause=self.on_toggle_pause,
            on_next_track=self.on_next_track,
        )
        self._running = True

    def _load_config(self) -> Dict[str, Any]:
        with self.config_path.open() as f:
            data = yaml.safe_load(f) or {}
        data.setdefault("tags", {})
        return data

    def start(self) -> None:
        print("Controller starting")
        self.nfc_reader.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        print("Controller stopping")
        self.nfc_reader.stop()
        self.buttons.close()

    def on_toggle_pause(self) -> None:
        try:
            state = self.player.toggle_pause()
            self.paused_by_tag_removal = False
            print(f"Pause/resume button pressed; new state={state}")
        except Exception as exc:
            print(f"Pause/resume failed: {exc}")

    def on_next_track(self) -> None:
        try:
            self.player.next_track()
            print("Next track button pressed")
        except Exception as exc:
            print(f"Next track failed: {exc}")

    def on_tag(self, uid: str) -> None:
        tag = self.config["tags"].get(uid)
        if not tag:
            print(f"Unknown NFC UID: {uid}")
            return

        try:
            if uid == self.active_tag_uid and self.paused_by_tag_removal:
                state = self.player.resume()
                self.paused_by_tag_removal = False
                print(f"Resumed playback for UID {uid}; new state={state}")
                return

            action = tag.get("action")
            if action == "play_folder":
                folder = tag["folder"]
                print(f"Playing folder for UID {uid}: {folder}")
                self.player.play_folder(folder)
            elif action == "play_playlist":
                playlist = tag["playlist"]
                shuffle = bool(tag.get("shuffle", False))
                print(f"Playing playlist for UID {uid}: {playlist} (shuffle={shuffle})")
                self.player.play_playlist(playlist, shuffle=shuffle)
            else:
                print(f"Unsupported action for UID {uid}: {action}")
                return

            self.active_tag_uid = uid
            self.paused_by_tag_removal = False
        except Exception as exc:
            print(f"Failed handling UID {uid}: {exc}")

    def on_tag_removed(self, uid: str) -> None:
        if uid != self.active_tag_uid:
            return
        try:
            status = self.player.get_status()
            if status.get("state") != "play":
                return
            state = self.player.pause()
            self.paused_by_tag_removal = True
            print(f"Paused playback because UID {uid} was removed; new state={state}")
        except Exception as exc:
            print(f"Failed handling removal of UID {uid}: {exc}")


def main() -> None:
    controller = Controller()

    def handle_signal(signum, _frame) -> None:
        print(f"Received signal {signum}")
        controller.stop()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    controller.start()
    signal.pause()


if __name__ == "__main__":
    main()
