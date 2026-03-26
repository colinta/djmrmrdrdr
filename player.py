from __future__ import annotations

from contextlib import contextmanager
from typing import Dict, Iterator

from mpd import CommandError, ConnectionError, MPDClient


class MusicPlayer:
    def __init__(self, host: str = "localhost", port: int = 6600, timeout: int = 10) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout

    def connect(self) -> MPDClient:
        client = MPDClient()
        client.timeout = self.timeout
        client.idletimeout = None
        client.connect(self.host, self.port)
        return client

    def disconnect(self, client: MPDClient) -> None:
        try:
            client.close()
        except Exception:
            pass
        try:
            client.disconnect()
        except Exception:
            pass

    @contextmanager
    def _client(self) -> Iterator[MPDClient]:
        client = self.connect()
        try:
            yield client
        finally:
            self.disconnect(client)

    def _run(self, operation):
        last_error = None
        for _ in range(2):
            try:
                with self._client() as client:
                    return operation(client)
            except (ConnectionError, BrokenPipeError, OSError) as exc:
                last_error = exc
        if last_error:
            raise last_error

    def play_folder(self, path: str) -> None:
        def operation(client: MPDClient) -> None:
            client.clear()
            client.add(path)
            client.play(0)

        self._run(operation)

    def play_playlist(self, name: str, shuffle: bool = False) -> None:
        def operation(client: MPDClient) -> None:
            client.clear()
            client.load(name)
            if shuffle:
                client.shuffle()
            client.play(0)

        self._run(operation)

    def pause(self) -> str:
        def operation(client: MPDClient) -> str:
            client.pause(1)
            return client.status().get("state", "unknown")

        return self._run(operation)

    def resume(self) -> str:
        def operation(client: MPDClient) -> str:
            client.pause(0)
            return client.status().get("state", "unknown")

        return self._run(operation)

    def toggle_pause(self) -> str:
        def operation(client: MPDClient) -> str:
            state = client.status().get("state", "stop")
            if state == "play":
                client.pause(1)
            else:
                client.pause(0)
            return client.status().get("state", "unknown")

        return self._run(operation)

    def next_track(self) -> None:
        self._run(lambda client: client.next())

    def get_status(self) -> Dict[str, str]:
        return self._run(lambda client: client.status())


if __name__ == "__main__":
    player = MusicPlayer()
    try:
        print(player.get_status())
    except (ConnectionError, CommandError) as exc:
        print(f"MPD error: {exc}")
