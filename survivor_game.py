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
- Zooming is possible via mouse wheel or +/- keys
- Core map and zoom parameters are configurable via config.json
"""

from __future__ import annotations

import json
import math
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

BASE_TILE_SIZE = 64  # pixels per tile at zoom level 1.0
DEFAULT_VIEWPORT_WIDTH = 800
DEFAULT_VIEWPORT_HEIGHT = 600

DEFAULT_CONFIG = {
    "initial_zoom": 1.0,
    "tile_count": 200,
    "max_zoom": 2.5,
}

CONFIG_PATH = Path(__file__).with_name("config.json")
MIN_ZOOM = 0.5

ACCELERATION = 0.12
MAX_SPEED = 1.2
FRICTION = 0.82
SPEED_EPSILON = 0.01
UPDATE_DELAY_MS = 16  # ~60 FPS

CAMERA_RETURN_SPEED = 0.35

BACKGROUND_COLOR = "#111318"
GRID_COLOR = "#1f2530"
PLAYER_BODY_COLOR = "#2fb875"
PLAYER_BELLY_COLOR = "#1d7b4d"
PLAYER_CREST_COLOR = "#45e09a"
PLAYER_OUTLINE_COLOR = "#0d331e"
PLAYER_EYE_COLOR = "#f8f3d6"
PLAYER_PUPIL_COLOR = "#181c1a"
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

PLAYER_BODY_POINTS: Tuple[Tuple[float, float], ...] = (
    (-0.82, 0.0),
    (-0.58, -0.18),
    (-0.32, -0.32),
    (-0.02, -0.34),
    (0.28, -0.26),
    (0.48, -0.16),
    (0.64, -0.08),
    (0.74, -0.04),
    (0.78, 0.0),
    (0.74, 0.04),
    (0.64, 0.08),
    (0.48, 0.16),
    (0.28, 0.26),
    (-0.02, 0.34),
    (-0.32, 0.32),
    (-0.58, 0.18),
)

PLAYER_BELLY_POINTS: Tuple[Tuple[float, float], ...] = (
    (-0.16, -0.2),
    (0.18, -0.18),
    (0.42, -0.08),
    (0.5, 0.0),
    (0.42, 0.08),
    (0.18, 0.18),
    (-0.16, 0.2),
)

PLAYER_CREST_POINTS: Tuple[Tuple[float, float], ...] = (
    (-0.22, -0.42),
    (0.08, -0.48),
    (0.26, -0.32),
    (-0.02, -0.26),
)

PLAYER_EYE_OFFSET = (0.46, -0.1)
PLAYER_EYE_RADIUS = 0.08
PLAYER_PUPIL_RADIUS = 0.036
PLAYER_SCALE = 0.52
PLAYER_HEALTHBAR_OFFSET = 0.65


@dataclass
class GameConfig:
    initial_zoom: float
    tile_count: int
    max_zoom: float


def load_game_config() -> GameConfig:
    config_data = DEFAULT_CONFIG.copy()
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            raw_config = json.load(config_file)
    except (FileNotFoundError, json.JSONDecodeError):
        raw_config = {}

    if isinstance(raw_config, dict):
        for key in DEFAULT_CONFIG:
            if key in raw_config:
                config_data[key] = raw_config[key]

    try:
        initial_zoom = float(config_data["initial_zoom"])
    except (TypeError, ValueError):
        initial_zoom = DEFAULT_CONFIG["initial_zoom"]

    try:
        max_zoom = float(config_data["max_zoom"])
    except (TypeError, ValueError):
        max_zoom = DEFAULT_CONFIG["max_zoom"]

    max_zoom = max(MIN_ZOOM, max_zoom)
    initial_zoom = max(MIN_ZOOM, min(initial_zoom, max_zoom))

    try:
        tile_count = int(config_data["tile_count"])
    except (TypeError, ValueError):
        tile_count = DEFAULT_CONFIG["tile_count"]

    tile_count = max(1, tile_count)
    return GameConfig(initial_zoom=initial_zoom, tile_count=tile_count, max_zoom=max_zoom)


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
        self.config = load_game_config()
        self.base_tile_size = BASE_TILE_SIZE
        self.tile_count = self.config.tile_count
        self.min_zoom = MIN_ZOOM
        self.max_zoom = max(self.min_zoom, self.config.max_zoom)
        self.zoom = max(self.min_zoom, min(self.config.initial_zoom, self.max_zoom))
        self._update_tile_size()

        self.root = tk.Tk()
        self.root.title("Survivor")
        self.root.configure(bg=BACKGROUND_COLOR)
        self.root.attributes("-fullscreen", True)
        self.root.bind("<Escape>", self._exit_fullscreen)
        self.root.update_idletasks()

        screen_width = self.root.winfo_screenwidth() or DEFAULT_VIEWPORT_WIDTH
        screen_height = self.root.winfo_screenheight() or DEFAULT_VIEWPORT_HEIGHT

        self.canvas = tk.Canvas(
            self.root,
            width=screen_width,
            height=screen_height,
            bg=BACKGROUND_COLOR,
            highlightthickness=0,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.root.bind_all("<MouseWheel>", self._on_mouse_wheel)
        self.root.bind_all("<Button-4>", self._on_mouse_wheel)
        self.root.bind_all("<Button-5>", self._on_mouse_wheel)

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
        self.inventory_slots: List[Tuple[tk.Canvas, int]] = []
        for row in range(2):
            for column in range(4):
                slot_canvas = tk.Canvas(
                    self.inventory_frame,
                    width=56,
                    height=56,
                    bg=BACKGROUND_COLOR,
                    highlightthickness=0,
                )
                slot_canvas.grid(row=row, column=column, padx=4, pady=4)
                slot_canvas.create_rectangle(
                    2,
                    2,
                    54,
                    54,
                    fill=INVENTORY_SLOT_COLOR,
                    outline=INVENTORY_SLOT_BORDER,
                    width=1,
                    stipple="gray50",
                )
                text_id = slot_canvas.create_text(
                    28,
                    28,
                    text="",
                    fill=HUD_TEXT_COLOR,
                    font=("Helvetica", 10, "bold"),
                )
                self.inventory_slots.append((slot_canvas, text_id))

        self.weapons: List[str | None] = [None] * 4
        self.abilities: List[str | None] = [None] * 4
        self._refresh_inventory_display()

        self.velocity = Vector2(0.0, 0.0)
        self.position = Vector2(self.tile_count / 2, self.tile_count / 2)
        self.facing_direction = Vector2(0.0, -1.0)
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

        self.player_body_id = self.canvas.create_polygon(
            0,
            0,
            0,
            0,
            fill=PLAYER_BODY_COLOR,
            outline=PLAYER_OUTLINE_COLOR,
            width=2,
            smooth=True,
            splinesteps=12,
        )
        self.player_belly_id = self.canvas.create_polygon(
            0,
            0,
            0,
            0,
            fill=PLAYER_BELLY_COLOR,
            outline="",
            smooth=True,
            splinesteps=10,
        )
        self.player_crest_id = self.canvas.create_polygon(
            0,
            0,
            0,
            0,
            fill=PLAYER_CREST_COLOR,
            outline="",
            smooth=True,
            splinesteps=8,
        )
        self.player_eye_id = self.canvas.create_oval(0, 0, 0, 0, fill=PLAYER_EYE_COLOR, outline="")
        self.player_pupil_id = self.canvas.create_oval(0, 0, 0, 0, fill=PLAYER_PUPIL_COLOR, outline="")
        self.canvas.tag_raise(self.player_belly_id, self.player_body_id)
        self.canvas.tag_raise(self.player_crest_id, self.player_belly_id)
        self.canvas.tag_raise(self.player_eye_id, self.player_crest_id)
        self.canvas.tag_raise(self.player_pupil_id, self.player_eye_id)
        self.health_bar_bg_id = self.canvas.create_rectangle(0, 0, 0, 0, fill=HEALTH_BAR_BG_COLOR, outline="")
        self.health_bar_fill_id = self.canvas.create_rectangle(0, 0, 0, 0, fill=HEALTH_BAR_FILL_COLOR, outline="")
        self.health_bar_border_id = self.canvas.create_rectangle(0, 0, 0, 0, outline=HUD_TEXT_COLOR, width=1)

        self.intro_overlay = self._create_intro_overlay()

    def _exit_fullscreen(self, _event: tk.Event | None = None) -> None:
        self.root.attributes("-fullscreen", False)

    def _update_tile_size(self) -> None:
        self.tile_size = self.base_tile_size * self.zoom

    def _adjust_zoom(self, delta: float) -> None:
        if delta == 0:
            return
        new_zoom = max(self.min_zoom, min(self.max_zoom, self.zoom + delta))
        if math.isclose(new_zoom, self.zoom, rel_tol=1e-9, abs_tol=1e-9):
            return
        self.zoom = new_zoom
        self._update_tile_size()

    def _on_mouse_wheel(self, event: tk.Event) -> None:  # type: ignore[override]
        direction = 0
        if hasattr(event, "delta") and event.delta:
            direction = 1 if event.delta > 0 else -1
        elif getattr(event, "num", None) in (4, 5):
            direction = 1 if event.num == 4 else -1
        if direction:
            self._adjust_zoom(direction * 0.1)

    def _on_zoom_key(self, event: tk.Event) -> None:  # type: ignore[override]
        keysym = event.keysym.lower()
        if keysym in ("plus", "equal", "kp_add"):
            self._adjust_zoom(0.1)
        elif keysym in ("minus", "kp_subtract", "underscore"):
            self._adjust_zoom(-0.1)

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
        for key in ("plus", "equal", "KP_Add", "minus", "KP_Subtract", "underscore"):
            self.root.bind_all(f"<KeyPress-{key}>", self._on_zoom_key)

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
        tile_size = self.tile_size
        self.camera_position = Vector2(
            (self.camera_position.x - delta_x / tile_size) % self.tile_count,
            (self.camera_position.y - delta_y / tile_size) % self.tile_count,
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
            if normalized.length() > 0.0:
                self.facing_direction = normalized
            self.velocity = (self.velocity + normalized * ACCELERATION).clamp_magnitude(MAX_SPEED)
        else:
            self.velocity = Vector2(self.velocity.x * FRICTION, self.velocity.y * FRICTION)
            if abs(self.velocity.x) < SPEED_EPSILON:
                self.velocity = Vector2(0.0, self.velocity.y)
            if abs(self.velocity.y) < SPEED_EPSILON:
                self.velocity = Vector2(self.velocity.x, 0.0)

    def _update_position(self) -> None:
        new_x = (self.position.x + self.velocity.x) % self.tile_count
        new_y = (self.position.y + self.velocity.y) % self.tile_count
        self.position = Vector2(new_x, new_y)

    def _update_camera(self) -> None:
        if self.camera_manual_override and not self.keys_pressed and self.velocity.length() <= SPEED_EPSILON:
            return
        if self.velocity.length() > SPEED_EPSILON:
            self.camera_manual_override = False
        if self.camera_manual_override:
            self.camera_position = Vector2(
                self.camera_position.x % self.tile_count,
                self.camera_position.y % self.tile_count,
            )
            return
        delta_x = self._wrapped_delta(self.camera_position.x, self.position.x)
        delta_y = self._wrapped_delta(self.camera_position.y, self.position.y)
        self.camera_position = Vector2(
            (self.camera_position.x + delta_x * CAMERA_RETURN_SPEED) % self.tile_count,
            (self.camera_position.y + delta_y * CAMERA_RETURN_SPEED) % self.tile_count,
        )

    def _wrapped_delta(self, current: float, target: float) -> float:
        diff = (target - current + self.tile_count / 2) % self.tile_count - self.tile_count / 2
        return diff

    def _transform_points(
        self,
        base_points: Iterable[Tuple[float, float]],
        angle: float,
        scale: float,
        center_x: float,
        center_y: float,
    ) -> List[float]:
        cos_angle = math.cos(angle)
        sin_angle = math.sin(angle)
        transformed: List[float] = []
        for point_x, point_y in base_points:
            rotated_x = point_x * cos_angle - point_y * sin_angle
            rotated_y = point_x * sin_angle + point_y * cos_angle
            transformed.append(center_x + rotated_x * scale)
            transformed.append(center_y + rotated_y * scale)
        return transformed

    def _transform_point(
        self,
        point: Tuple[float, float],
        angle: float,
        scale: float,
        center_x: float,
        center_y: float,
    ) -> Tuple[float, float]:
        cos_angle = math.cos(angle)
        sin_angle = math.sin(angle)
        base_x, base_y = point
        rotated_x = base_x * cos_angle - base_y * sin_angle
        rotated_y = base_x * sin_angle + base_y * cos_angle
        return center_x + rotated_x * scale, center_y + rotated_y * scale

    def _update_player_sprite(self, center_x: float, center_y: float, tile_size: float) -> None:
        if self.facing_direction.length() == 0.0:
            angle = -math.pi / 2
        else:
            angle = math.atan2(self.facing_direction.y, self.facing_direction.x)
        scale = tile_size * PLAYER_SCALE
        body_coords = self._transform_points(PLAYER_BODY_POINTS, angle, scale, center_x, center_y)
        self.canvas.coords(self.player_body_id, *body_coords)
        belly_coords = self._transform_points(PLAYER_BELLY_POINTS, angle, scale, center_x, center_y)
        self.canvas.coords(self.player_belly_id, *belly_coords)
        crest_coords = self._transform_points(PLAYER_CREST_POINTS, angle, scale, center_x, center_y)
        self.canvas.coords(self.player_crest_id, *crest_coords)

        eye_center_x, eye_center_y = self._transform_point(
            PLAYER_EYE_OFFSET, angle, scale, center_x, center_y
        )
        eye_radius = tile_size * PLAYER_EYE_RADIUS
        self.canvas.coords(
            self.player_eye_id,
            eye_center_x - eye_radius,
            eye_center_y - eye_radius,
            eye_center_x + eye_radius,
            eye_center_y + eye_radius,
        )

        pupil_radius = tile_size * PLAYER_PUPIL_RADIUS
        self.canvas.coords(
            self.player_pupil_id,
            eye_center_x - pupil_radius,
            eye_center_y - pupil_radius,
            eye_center_x + pupil_radius,
            eye_center_y + pupil_radius,
        )

    def _render_scene(self) -> None:
        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        tile_size = self.tile_size

        top_left_pixel_x = self.camera_position.x * tile_size - viewport_width / 2
        top_left_pixel_y = self.camera_position.y * tile_size - viewport_height / 2

        start_tile_x = math.floor(top_left_pixel_x / tile_size)
        start_tile_y = math.floor(top_left_pixel_y / tile_size)

        visible_columns = int(viewport_width / tile_size) + 3
        visible_rows = int(viewport_height / tile_size) + 3

        self.canvas.delete("grid")
        for column in range(visible_columns):
            tile_x = start_tile_x + column
            pixel_x = tile_x * tile_size - top_left_pixel_x
            self.canvas.create_line(
                pixel_x,
                0,
                pixel_x,
                viewport_height,
                fill=GRID_COLOR,
                tags="grid",
            )
        for row in range(visible_rows):
            tile_y = start_tile_y + row
            pixel_y = tile_y * tile_size - top_left_pixel_y
            self.canvas.create_line(
                0,
                pixel_y,
                viewport_width,
                pixel_y,
                fill=GRID_COLOR,
                tags="grid",
            )

        player_pixel_x = self.position.x * tile_size - top_left_pixel_x
        player_pixel_y = self.position.y * tile_size - top_left_pixel_y
        self._update_player_sprite(player_pixel_x, player_pixel_y, tile_size)

        bar_width = tile_size * 0.8
        bar_height = 10
        bar_left = player_pixel_x - bar_width / 2
        bar_right = player_pixel_x + bar_width / 2
        bar_top = player_pixel_y - tile_size * PLAYER_HEALTHBAR_OFFSET - 20
        bar_bottom = bar_top + bar_height

        health_ratio = max(0.0, min(1.0, self.health / self.max_health))
        fill_right = bar_left + 2 + (bar_width - 4) * health_ratio

        self.canvas.coords(self.health_bar_bg_id, bar_left, bar_top, bar_right, bar_bottom)
        self.canvas.coords(self.health_bar_fill_id, bar_left + 2, bar_top + 2, fill_right, bar_bottom - 2)
        self.canvas.coords(self.health_bar_border_id, bar_left, bar_top, bar_right, bar_bottom)

    def _update_status_ui(self) -> None:
        tile_x = int(self.position.x) % self.tile_count
        tile_y = int(self.position.y) % self.tile_count
        self.position_label.config(text=f"Position: ({tile_x:03d}, {tile_y:03d})")
        self._update_xp_bar()

    def _update_xp_bar(self) -> None:
        progress = 0.0 if self.xp_to_next_level == 0 else min(1.0, self.xp / self.xp_to_next_level)
        fill_width = 2 + (XP_BAR_WIDTH - 4) * progress
        self.xp_canvas.coords(self.xp_bar_fill, 2, 2, fill_width, XP_BAR_HEIGHT - 2)
        self.xp_canvas.itemconfigure(self.xp_text_id, text=f"XP {self.xp} / {self.xp_to_next_level}")

    def _refresh_inventory_display(self) -> None:
        for index, (slot_canvas, text_id) in enumerate(self.inventory_slots):
            if index < 4:
                item = self.weapons[index]
            else:
                item = self.abilities[index - 4]
            slot_canvas.itemconfigure(text_id, text=item if item else "")

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
