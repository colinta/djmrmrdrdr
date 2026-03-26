from __future__ import annotations

from typing import Callable, List

from gpiozero import Button


class Buttons:
    def __init__(
        self,
        on_toggle_pause: Callable[[], None],
        on_next_track: Callable[[], None],
        pause_pin: int = 17,
        next_pin: int = 27,
        bounce_time: float = 0.05,
    ) -> None:
        self._buttons: List[Button] = [
            Button(pause_pin, pull_up=True, bounce_time=bounce_time),
            Button(next_pin, pull_up=True, bounce_time=bounce_time),
        ]
        self._buttons[0].when_pressed = on_toggle_pause
        self._buttons[1].when_pressed = on_next_track

    def close(self) -> None:
        for button in self._buttons:
            button.close()
