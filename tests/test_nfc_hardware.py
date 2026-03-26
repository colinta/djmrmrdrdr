from __future__ import annotations

import signal
import sys
import time

from nfc_reader import NFCReader

seen = {}
running = True


def on_tag(uid: str) -> None:
    now = time.time()
    previous = seen.get(uid)
    if previous is None:
        print(f"NEW TAG: {uid}")
    else:
        print(f"TAG AGAIN: {uid} ({now - previous:.1f}s since last accepted read)")
    seen[uid] = now


def handle_signal(signum, _frame) -> None:
    global running
    print(f"Stopping on signal {signum}")
    running = False


if __name__ == "__main__":
    print("Initializing NFC reader...")
    print("Make sure the RC522 is wired to SPI and powered from 3.3V.")
    print("Present tags to the reader. Press Ctrl+C to stop.")

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        reader = NFCReader(callback=on_tag, debounce_seconds=2.0, poll_interval=0.1)
    except Exception as exc:
        print(f"Failed to initialize NFC reader: {exc}")
        sys.exit(1)

    reader.start()
    try:
        while running:
            time.sleep(0.25)
    finally:
        reader.stop()
        print("Reader stopped.")
