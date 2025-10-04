"""Top-down Survivor mini game implemented with tkinter.

The game fulfils the following requirements:
- 200x200 tile map that wraps around endlessly
- Player controlled with WASD or arrow keys
- Movement features light acceleration and friction based deceleration
- Before the gameplay starts an introduction screen is shown
- Only a small portion of the map is visible at a time and the camera follows the player
- The camera can be dragged with the mouse but snaps back to the player as soon as they move
- Tiles are at least 64 pixels in size
- HUD shows player health, XP, inventory slots, coins and tile coordinates
"""

from __future__ import annotations

import math
import tkinter as tk
from dataclasses import dataclass
from typing import Iterable, List, Tuple

TILE_COUNT = 200
TILE_SIZE = 64  # pixels per tile
VIEWPORT_WIDTH = 800
VIEWPORT_HEIGHT = 600

ACCELERATION = 0.12
MAX_SPEED = 1.2
FRICTION = 0.82
SPEED_EPSILON = 0.01
UPDATE_DELAY_MS = 16  # ~60 FPS

CAMERA_RETURN_SPEED = 0.35

BACKGROUND_COLOR = "#111318"
GRID_COLOR = "#1f2530"
PLAYER_COLOR = "#3ddc84"
HUD_TEXT_COLOR = "#f5f7fb"
INTRO_BG_COLOR = "#1b2330"
INTRO_TEXT_COLOR = "#f0f3ff"
HEALTH_BAR_BG_COLOR = "#2d323d"
HEALTH_BAR_FILL_COLOR = "#ff5d62"
XP_BAR_BG_COLOR = "#2d323d"
XP_BAR_FILL_COLOR = "#4fb6ff"
INVENTORY_SLOT_COLOR = "#1f2530"
INVENTORY_SLOT_BORDER = "#394050"

XP_BAR_WIDTH = 320
XP_BAR_HEIGHT = 24


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
            width=VIEWPORT_WIDTH,
            height=VIEWPORT_HEIGHT,
            bg=BACKGROUND_COLOR,
            highlightthickness=0,
        )
        self.canvas.pack(padx=20, pady=(80, 20))

        self.position_label = tk.Label(
            self.root,
            font=("Helvetica", 12, "bold"),
            fg=HUD_TEXT_COLOR,
            bg=BACKGROUND_COLOR,
            text="Position: (100, 100)",
        )
        self.position_label.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=56)

        self.coin_label = tk.Label(
            self.root,
            font=("Helvetica", 14, "bold"),
            fg=HUD_TEXT_COLOR,
            bg=BACKGROUND_COLOR,
            text="Coins: 0",
        )
        self.coin_label.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=20)

        self.xp_canvas = tk.Canvas(
            self.root,
            width=XP_BAR_WIDTH,
            height=XP_BAR_HEIGHT,
            bg=BACKGROUND_COLOR,
            highlightthickness=0,
        )
        self.xp_canvas.place(relx=0.5, rely=0.0, anchor="n", y=20)
        self.xp_bar_bg = self.xp_canvas.create_rectangle(
            0,
            0,
            XP_BAR_WIDTH,
            XP_BAR_HEIGHT,
            fill=XP_BAR_BG_COLOR,
            outline="",
        )
        self.xp_bar_fill = self.xp_canvas.create_rectangle(
            2,
            2,
            2,
            XP_BAR_HEIGHT - 2,
            fill=XP_BAR_FILL_COLOR,
            outline="",
        )
        self.xp_bar_border = self.xp_canvas.create_rectangle(
            0,
            0,
            XP_BAR_WIDTH,
            XP_BAR_HEIGHT,
            outline=HUD_TEXT_COLOR,
            width=1,
        )
        self.xp_text_id = self.xp_canvas.create_text(
            XP_BAR_WIDTH / 2,
            XP_BAR_HEIGHT / 2,
            text="XP 0 / 100",
            fill=HUD_TEXT_COLOR,
            font=("Helvetica", 12, "bold"),
        )

        self.inventory_frame = tk.Frame(self.root, bg=BACKGROUND_COLOR)
        self.inventory_frame.place(relx=0.0, rely=0.0, anchor="nw", x=20, y=20)
        self.inventory_slots: List[Tuple[tk.Frame, tk.Label]] = []
        for row in range(2):
            for column in range(4):
                slot = tk.Frame(
                    self.inventory_frame,
                    width=56,
                    height=56,
                    bg=INVENTORY_SLOT_COLOR,
                    highlightbackground=INVENTORY_SLOT_BORDER,
                    highlightthickness=1,
                )
                slot.grid(row=row, column=column, padx=4, pady=4)
                slot.grid_propagate(False)
                label = tk.Label(
                    slot,
                    text="",
                    fg=HUD_TEXT_COLOR,
                    bg=INVENTORY_SLOT_COLOR,
                    font=("Helvetica", 10, "bold"),
                )
                label.place(relx=0.5, rely=0.5, anchor="center")
                self.inventory_slots.append((slot, label))

        self.weapons: List[str | None] = [None] * 4
        self.abilities: List[str | None] = [None] * 4
        self._refresh_inventory_display()

        self.velocity = Vector2(0.0, 0.0)
        self.position = Vector2(TILE_COUNT / 2, TILE_COUNT / 2)
        self.camera_position = Vector2(self.position.x, self.position.y)
        self.camera_manual_override = False
        self.camera_dragging = False
        self._last_mouse_position: Vector2 | None = None

        self.max_health = 100
        self.health = 100
        self.xp = 0
        self.xp_to_next_level = 100
        self.coins = 0
        self._update_coin_label()
        self._update_xp_bar()

        self.keys_pressed: set[str] = set()
        self.game_running = False

        self.canvas.bind("<ButtonPress-1>", self._on_mouse_press)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_release)

        self.player_id = self.canvas.create_oval(0, 0, 0, 0, fill=PLAYER_COLOR, outline="")
        self.health_bar_bg_id = self.canvas.create_rectangle(0, 0, 0, 0, fill=HEALTH_BAR_BG_COLOR, outline="")
        self.health_bar_fill_id = self.canvas.create_rectangle(0, 0, 0, 0, fill=HEALTH_BAR_FILL_COLOR, outline="")
        self.health_bar_border_id = self.canvas.create_rectangle(0, 0, 0, 0, outline=HUD_TEXT_COLOR, width=1)

        self.intro_overlay = self._create_intro_overlay()

    def _create_intro_overlay(self) -> tk.Frame:
        overlay = tk.Frame(self.root, bg=INTRO_BG_COLOR)
        overlay.place(relx=0.5, rely=0.5, anchor="center", relwidth=1.0, relheight=1.0)

        intro_text = (
            "Willkommen bei Survivor!\n\n"
            "Steuere die Spielfigur mit WASD oder den Pfeiltasten.\n"
            "Beschleunige vorsichtig: Lässt du die Tasten los, verlangsamt\n"
            "die Figur durch Reibung schnell wieder.\n\n"
            "Ziehe mit gedrückter linker Maustaste, um die Kamera zu verschieben.\n"
            "Sobald du dich bewegst, fokussiert die Kamera schnell wieder den Spieler.\n\n"
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
        self._schedule_coin_reward()
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

    def _on_mouse_press(self, event: tk.Event) -> None:  # type: ignore[override]
        self.canvas.focus_set()
        self.camera_dragging = True
        self.camera_manual_override = True
        self._last_mouse_position = Vector2(event.x, event.y)

    def _on_mouse_drag(self, event: tk.Event) -> None:  # type: ignore[override]
        if not self.camera_dragging or self._last_mouse_position is None:
            return
        delta_x = event.x - self._last_mouse_position.x
        delta_y = event.y - self._last_mouse_position.y
        self._last_mouse_position = Vector2(event.x, event.y)
        self.camera_position = Vector2(
            (self.camera_position.x - delta_x / TILE_SIZE) % TILE_COUNT,
            (self.camera_position.y - delta_y / TILE_SIZE) % TILE_COUNT,
        )

    def _on_mouse_release(self, _event: tk.Event) -> None:  # type: ignore[override]
        self.camera_dragging = False
        self._last_mouse_position = None

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
            self.camera_manual_override = False
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

    def _update_camera(self) -> None:
        if self.camera_manual_override and not self.keys_pressed and self.velocity.length() <= SPEED_EPSILON:
            return
        if self.velocity.length() > SPEED_EPSILON:
            self.camera_manual_override = False
        if self.camera_manual_override:
            self.camera_position = Vector2(self.camera_position.x % TILE_COUNT, self.camera_position.y % TILE_COUNT)
            return
        delta_x = self._wrapped_delta(self.camera_position.x, self.position.x)
        delta_y = self._wrapped_delta(self.camera_position.y, self.position.y)
        self.camera_position = Vector2(
            (self.camera_position.x + delta_x * CAMERA_RETURN_SPEED) % TILE_COUNT,
            (self.camera_position.y + delta_y * CAMERA_RETURN_SPEED) % TILE_COUNT,
        )

    @staticmethod
    def _wrapped_delta(current: float, target: float) -> float:
        diff = (target - current + TILE_COUNT / 2) % TILE_COUNT - TILE_COUNT / 2
        return diff

    def _render_scene(self) -> None:
        top_left_pixel_x = self.camera_position.x * TILE_SIZE - VIEWPORT_WIDTH / 2
        top_left_pixel_y = self.camera_position.y * TILE_SIZE - VIEWPORT_HEIGHT / 2

        start_tile_x = math.floor(top_left_pixel_x / TILE_SIZE)
        start_tile_y = math.floor(top_left_pixel_y / TILE_SIZE)

        visible_columns = VIEWPORT_WIDTH // TILE_SIZE + 3
        visible_rows = VIEWPORT_HEIGHT // TILE_SIZE + 3

        self.canvas.delete("grid")
        for column in range(visible_columns):
            tile_x = start_tile_x + column
            pixel_x = tile_x * TILE_SIZE - top_left_pixel_x
            self.canvas.create_line(
                pixel_x,
                0,
                pixel_x,
                VIEWPORT_HEIGHT,
                fill=GRID_COLOR,
                tags="grid",
            )
        for row in range(visible_rows):
            tile_y = start_tile_y + row
            pixel_y = tile_y * TILE_SIZE - top_left_pixel_y
            self.canvas.create_line(
                0,
                pixel_y,
                VIEWPORT_WIDTH,
                pixel_y,
                fill=GRID_COLOR,
                tags="grid",
            )

        player_pixel_x = self.position.x * TILE_SIZE - top_left_pixel_x
        player_pixel_y = self.position.y * TILE_SIZE - top_left_pixel_y
        radius = TILE_SIZE * 0.3
        self.canvas.coords(
            self.player_id,
            player_pixel_x - radius,
            player_pixel_y - radius,
            player_pixel_x + radius,
            player_pixel_y + radius,
        )

        bar_width = TILE_SIZE * 0.8
        bar_height = 10
        bar_left = player_pixel_x - bar_width / 2
        bar_right = player_pixel_x + bar_width / 2
        bar_top = player_pixel_y - radius - 20
        bar_bottom = bar_top + bar_height

        health_ratio = max(0.0, min(1.0, self.health / self.max_health))
        fill_right = bar_left + 2 + (bar_width - 4) * health_ratio

        self.canvas.coords(self.health_bar_bg_id, bar_left, bar_top, bar_right, bar_bottom)
        self.canvas.coords(self.health_bar_fill_id, bar_left + 2, bar_top + 2, fill_right, bar_bottom - 2)
        self.canvas.coords(self.health_bar_border_id, bar_left, bar_top, bar_right, bar_bottom)

    def _update_status_ui(self) -> None:
        tile_x = int(self.position.x) % TILE_COUNT
        tile_y = int(self.position.y) % TILE_COUNT
        self.position_label.config(text=f"Position: ({tile_x:03d}, {tile_y:03d})")
        self._update_xp_bar()

    def _update_xp_bar(self) -> None:
        progress = 0.0 if self.xp_to_next_level == 0 else min(1.0, self.xp / self.xp_to_next_level)
        fill_width = 2 + (XP_BAR_WIDTH - 4) * progress
        self.xp_canvas.coords(self.xp_bar_fill, 2, 2, fill_width, XP_BAR_HEIGHT - 2)
        self.xp_canvas.itemconfigure(self.xp_text_id, text=f"XP {self.xp} / {self.xp_to_next_level}")

    def _refresh_inventory_display(self) -> None:
        for index, (_slot, label) in enumerate(self.inventory_slots):
            if index < 4:
                item = self.weapons[index]
            else:
                item = self.abilities[index - 4]
            label.config(text=item if item else "")

    def _update_coin_label(self) -> None:
        self.coin_label.config(text=f"Coins: {self.coins}")

    def _schedule_coin_reward(self) -> None:
        self.root.after(5000, self._grant_survival_coin)

    def _grant_survival_coin(self) -> None:
        if self.game_running:
            self.coins += 1
            self._update_coin_label()
        self._schedule_coin_reward()

    def _schedule_next_frame(self) -> None:
        self.root.after(UPDATE_DELAY_MS, self._game_loop)

    def _game_loop(self) -> None:
        if not self.game_running:
            return
        self._apply_input()
        self._update_position()
        self._update_camera()
        self._render_scene()
        self._update_status_ui()
        self._schedule_next_frame()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    game = SurvivorGame()
    game.run()


if __name__ == "__main__":
    main()
