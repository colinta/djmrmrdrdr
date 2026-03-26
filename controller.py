from __future__ import annotations

import signal
from pathlib import Path

from buttons import Buttons
from nfc_reader import NFCReader
from player import MusicPlayer
from state import TagsState, load_queue, load_runtime_state, load_tags, save_queue, save_runtime_state, save_tags

CONFIG_PATH = Path("/etc/musicplayer/tags.yaml")


class Controller:
    def __init__(self, config_path: Path = CONFIG_PATH) -> None:
        self.config_path = config_path
        self.player = MusicPlayer()
        self.config = self._load_config()
        self.active_tag_uid: str | None = None
        self.paused_by_tag_removal = False
        self.awaiting_retap_uids: set[str] = set()
        self.nfc_reader = NFCReader(callback=self.on_tag, on_removed=self.on_tag_removed)
        self.buttons = Buttons(
            on_toggle_pause=self.on_toggle_pause,
            on_next_track=self.on_next_track,
        )
        self._running = True

    def _load_config(self) -> TagsState:
        return load_tags()

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
        runtime_state = load_runtime_state()
        runtime_state["last_scanned_uid"] = uid
        save_runtime_state(runtime_state)

        self.config = self._load_config()
        tag = self.config["tags"].get(uid)
        if not tag:
            self._handle_unknown_tag(uid)
            return

        try:
            if uid in self.awaiting_retap_uids:
                runtime_state["message"] = f"tag {uid} assigned; remove it, then tap again to play"
                save_runtime_state(runtime_state)
                print(f"Ignoring UID {uid} until it is removed after assignment")
                return

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
                runtime_state["message"] = f"played {folder}"
            elif action == "play_playlist":
                playlist = tag["playlist"]
                shuffle = bool(tag.get("shuffle", False))
                print(f"Playing playlist for UID {uid}: {playlist} (shuffle={shuffle})")
                self.player.play_playlist(playlist, shuffle=shuffle)
                runtime_state["message"] = f"played playlist {playlist}"
            else:
                print(f"Unsupported action for UID {uid}: {action}")
                runtime_state["message"] = f"unsupported action for {uid}: {action}"
                save_runtime_state(runtime_state)
                return

            self.active_tag_uid = uid
            self.paused_by_tag_removal = False
            save_runtime_state(runtime_state)
        except Exception as exc:
            print(f"Failed handling UID {uid}: {exc}")
            runtime_state["message"] = f"play failed for {uid}: {exc}"
            save_runtime_state(runtime_state)

    def on_tag_removed(self, uid: str) -> None:
        if uid not in self.awaiting_retap_uids:
            return
        self.awaiting_retap_uids.remove(uid)
        runtime_state = load_runtime_state()
        runtime_state["message"] = f"tag {uid} assigned; tap again when you want to play it"
        save_runtime_state(runtime_state)
        print(f"UID {uid} was removed after assignment and is now ready to play")

    def _handle_unknown_tag(self, uid: str) -> None:
        runtime_state = load_runtime_state()
        runtime_state["last_unknown_uid"] = uid
        queue_state = load_queue()
        queue = queue_state.get("queue", [])

        if not queue:
            runtime_state["message"] = f"unknown tag {uid}; queue empty"
            save_runtime_state(runtime_state)
            print(f"Unknown NFC UID with empty queue: {uid}")
            return

        assignment = queue.pop(0)
        tags = load_tags()
        tags.setdefault("tags", {})
        tags["tags"][uid] = {
            "action": assignment.get("action", "play_folder"),
            "folder": assignment["folder"],
        }
        save_tags(tags)
        queue_state["queue"] = queue
        save_queue(queue_state)
        self.config = tags
        self.awaiting_retap_uids.add(uid)
        runtime_state["last_assignment"] = {"uid": uid, **assignment}
        runtime_state["message"] = f"assigned {uid} -> {assignment['folder']}; remove tag, then tap again to play"
        save_runtime_state(runtime_state)
        print(f"Assigned UID {uid} to {assignment['folder']}; waiting for removal before playback")


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
