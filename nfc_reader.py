from __future__ import annotations

import threading
import time
from typing import Callable, Optional

from mfrc522 import SimpleMFRC522


class NFCReader:
    def __init__(
        self,
        callback: Callable[[str], None],
        on_removed: Optional[Callable[[str], None]] = None,
        debounce_seconds: float = 2.0,
        poll_interval: float = 0.1,
        removal_timeout: float = 0.5,
    ) -> None:
        self.callback = callback
        self.on_removed = on_removed
        self.debounce_seconds = debounce_seconds
        self.poll_interval = poll_interval
        self.removal_timeout = removal_timeout
        self.reader = SimpleMFRC522()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_uid: Optional[str] = None
        self._last_seen_at: float = 0.0
        self._present_uid: Optional[str] = None
        self._present_last_seen_at: float = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="nfc-reader", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 1.0) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                uid = self.reader.read_id_no_block()
                now = time.monotonic()
                if uid:
                    self._handle_uid(str(uid), now)
                else:
                    self._handle_missing_tag(now)
                    time.sleep(self.poll_interval)
            except Exception as exc:
                print(f"NFC read error: {exc}")
                time.sleep(1.0)

    def _handle_uid(self, uid: str, now: float) -> None:
        self._present_uid = uid
        self._present_last_seen_at = now
        if uid == self._last_uid and now - self._last_seen_at < self.debounce_seconds:
            return
        self._last_uid = uid
        self._last_seen_at = now
        self.callback(uid)

    def _handle_missing_tag(self, now: float) -> None:
        if not self._present_uid:
            return
        if now - self._present_last_seen_at < self.removal_timeout:
            return
        removed_uid = self._present_uid
        self._present_uid = None
        if self.on_removed:
            self.on_removed(removed_uid)
