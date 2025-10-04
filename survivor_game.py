"""Top-down Survivor mini game implemented with tkinter.

The game fulfils the following requirements:
- 200x200 tile map that wraps around endlessly
- Player controlled with WASD or arrow keys
- Movement features light acceleration and friction based deceleration
- Before the gameplay starts an introduction screen is shown
- The player's tile position is displayed in the top right corner
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass
from typing import Iterable

TILE_COUNT = 200
TILE_SIZE = 4  # pixels per tile => 800x800px canvas
MAP_PIXEL_SIZE = TILE_COUNT * TILE_SIZE

ACCELERATION = 0.12
MAX_SPEED = 1.2
FRICTION = 0.82
SPEED_EPSILON = 0.01
UPDATE_DELAY_MS = 16  # ~60 FPS

BACKGROUND_COLOR = "#111318"
GRID_COLOR = "#1f2530"
PLAYER_COLOR = "#3ddc84"
HUD_TEXT_COLOR = "#f5f7fb"
INTRO_BG_COLOR = "#1b2330"
INTRO_TEXT_COLOR = "#f0f3ff"


@dataclass
class Vector2:
    x: float
    y: float

    def __add__(self, other: "Vector2") -> "Vector2":
        return Vector2(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Vector2") -> "Vector2":
        return Vector2(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> "Vector2":
        return Vector2(self.x * scalar, self.y * scalar)

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def normalize(self) -> "Vector2":
        length = self.length()
        if length == 0:
            return Vector2(0.0, 0.0)
        return Vector2(self.x / length, self.y / length)

    def clamp_magnitude(self, max_length: float) -> "Vector2":
        length = self.length()
        if length <= max_length:
            return self
        if length == 0:
            return Vector2(0.0, 0.0)
        scale = max_length / length
        return Vector2(self.x * scale, self.y * scale)


class SurvivorGame:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Survivor")
        self.root.configure(bg=BACKGROUND_COLOR)
        self.root.resizable(False, False)

        self.canvas = tk.Canvas(
            self.root,
            width=MAP_PIXEL_SIZE,
            height=MAP_PIXEL_SIZE,
            bg=BACKGROUND_COLOR,
            highlightthickness=0,
        )
        self.canvas.pack(padx=20, pady=20)

        self.position_label = tk.Label(
            self.root,
            font=("Helvetica", 12, "bold"),
            fg=HUD_TEXT_COLOR,
            bg=BACKGROUND_COLOR,
            text="Position: (100, 100)",
        )
        self.position_label.place(relx=1.0, rely=0.0, anchor="ne", x=-10, y=10)

        self.velocity = Vector2(0.0, 0.0)
        self.position = Vector2(TILE_COUNT / 2, TILE_COUNT / 2)
        self.keys_pressed: set[str] = set()
        self.game_running = False

        self._draw_grid()
        self.player_id = self._create_player_sprite()

        self.intro_overlay = self._create_intro_overlay()

    def _draw_grid(self) -> None:
        for index in range(TILE_COUNT + 1):
            offset = index * TILE_SIZE
            self.canvas.create_line(0, offset, MAP_PIXEL_SIZE, offset, fill=GRID_COLOR)
            self.canvas.create_line(offset, 0, offset, MAP_PIXEL_SIZE, fill=GRID_COLOR)

    def _create_player_sprite(self) -> int:
        pixel_position = self._to_pixel_position(self.position)
        radius = TILE_SIZE * 0.8
        return self.canvas.create_oval(
            pixel_position.x - radius,
            pixel_position.y - radius,
            pixel_position.x + radius,
            pixel_position.y + radius,
            fill=PLAYER_COLOR,
            outline="",
        )

    def _create_intro_overlay(self) -> tk.Frame:
        overlay = tk.Frame(self.root, bg=INTRO_BG_COLOR)
        overlay.place(relx=0.5, rely=0.5, anchor="center", relwidth=1.0, relheight=1.0)

        intro_text = (
            "Willkommen bei Survivor!\n\n"
            "Steuere die Spielfigur mit WASD oder den Pfeiltasten.\n"
            "Beschleunige vorsichtig: Lässt du die Tasten los, verlangsamt\n"
            "die Figur durch Reibung schnell wieder.\n\n"
            "Die Karte umfasst 200x200 Felder und läuft an den Rändern\n"
            "nahtlos weiter. Versuche so lange wie möglich zu überleben!"
        )

        headline = tk.Label(
            overlay,
            text="Survivor",
            font=("Helvetica", 26, "bold"),
            fg=INTRO_TEXT_COLOR,
            bg=INTRO_BG_COLOR,
        )
        headline.pack(pady=(60, 20))

        body = tk.Label(
            overlay,
            text=intro_text,
            font=("Helvetica", 14),
            fg=INTRO_TEXT_COLOR,
            bg=INTRO_BG_COLOR,
            justify="center",
        )
        body.pack(padx=40)

        start_button = tk.Button(
            overlay,
            text="Spiel starten",
            font=("Helvetica", 14, "bold"),
            command=self.start_game,
            bg="#3ddc84",
            fg="#101417",
            activebackground="#34c974",
            activeforeground="#101417",
            relief=tk.FLAT,
            padx=20,
            pady=8,
        )
        start_button.pack(pady=40)

        overlay.focus_set()
        overlay.bind("<Return>", lambda _event: self.start_game())
        overlay.bind("<space>", lambda _event: self.start_game())

        return overlay

    def start_game(self) -> None:
        if self.game_running:
            return
        self.intro_overlay.destroy()
        self._setup_bindings()
        self.game_running = True
        self._schedule_next_frame()

    def _setup_bindings(self) -> None:
        for key in self._movement_keys():
            self.root.bind_all(f"<KeyPress-{key}>", self._on_key_press)
            self.root.bind_all(f"<KeyRelease-{key}>", self._on_key_release)

    @staticmethod
    def _movement_keys() -> Iterable[str]:
        return ("w", "a", "s", "d", "Up", "Down", "Left", "Right")

    def _on_key_press(self, event: tk.Event) -> None:  # type: ignore[override]
        self.keys_pressed.add(event.keysym.lower())

    def _on_key_release(self, event: tk.Event) -> None:  # type: ignore[override]
        self.keys_pressed.discard(event.keysym.lower())

    def _apply_input(self) -> None:
        direction = Vector2(0.0, 0.0)
        if "w" in self.keys_pressed or "up" in self.keys_pressed:
            direction = direction + Vector2(0.0, -1.0)
        if "s" in self.keys_pressed or "down" in self.keys_pressed:
            direction = direction + Vector2(0.0, 1.0)
        if "a" in self.keys_pressed or "left" in self.keys_pressed:
            direction = direction + Vector2(-1.0, 0.0)
        if "d" in self.keys_pressed or "right" in self.keys_pressed:
            direction = direction + Vector2(1.0, 0.0)

        if direction.length() > 0.0:
            normalized = direction.normalize()
            self.velocity = (self.velocity + normalized * ACCELERATION).clamp_magnitude(MAX_SPEED)
        else:
            self.velocity = Vector2(self.velocity.x * FRICTION, self.velocity.y * FRICTION)
            if abs(self.velocity.x) < SPEED_EPSILON:
                self.velocity = Vector2(0.0, self.velocity.y)
            if abs(self.velocity.y) < SPEED_EPSILON:
                self.velocity = Vector2(self.velocity.x, 0.0)

    def _update_position(self) -> None:
        new_x = (self.position.x + self.velocity.x) % TILE_COUNT
        new_y = (self.position.y + self.velocity.y) % TILE_COUNT
        self.position = Vector2(new_x, new_y)

    def _update_player_sprite(self) -> None:
        pixel_position = self._to_pixel_position(self.position)
        radius = TILE_SIZE * 0.8
        self.canvas.coords(
            self.player_id,
            pixel_position.x - radius,
            pixel_position.y - radius,
            pixel_position.x + radius,
            pixel_position.y + radius,
        )

    def _update_hud(self) -> None:
        tile_x = int(self.position.x) % TILE_COUNT
        tile_y = int(self.position.y) % TILE_COUNT
        self.position_label.config(text=f"Position: ({tile_x:03d}, {tile_y:03d})")

    def _schedule_next_frame(self) -> None:
        self.root.after(UPDATE_DELAY_MS, self._game_loop)

    def _game_loop(self) -> None:
        if not self.game_running:
            return
        self._apply_input()
        self._update_position()
        self._update_player_sprite()
        self._update_hud()
        self._schedule_next_frame()

    @staticmethod
    def _to_pixel_position(tile_position: Vector2) -> Vector2:
        return Vector2(
            (tile_position.x + 0.5) * TILE_SIZE,
            (tile_position.y + 0.5) * TILE_SIZE,
        )

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    game = SurvivorGame()
    game.run()


if __name__ == "__main__":
    main()
