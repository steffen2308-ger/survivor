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
import random
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

BASE_TILE_SIZE = 64  # pixels per tile at zoom level 1.0
DEFAULT_VIEWPORT_WIDTH = 800
DEFAULT_VIEWPORT_HEIGHT = 600

DEFAULT_CONFIG = {
    "initial_zoom": 1.0,
    "tile_count": 200,
    "max_zoom": 2.5,
    "player": {
        "max_health": 100,
        "initial_health": 100,
        "max_speed": 1.2,
        "initial_speed": 1.2,
    },
}

CONFIG_PATH = Path(__file__).with_name("config.json")
ENEMY_CONFIG_PATH = Path(__file__).with_name("Gegner.json")
LEVEL_CONFIG_PATH = Path(__file__).with_name("Level.json")
MIN_ZOOM = 0.5

ACCELERATION = 0.12
FRICTION = 0.82
SPEED_EPSILON = 0.01
UPDATE_DELAY_MS = 16  # ~60 FPS

CAMERA_RETURN_SPEED = 0.35

BACKGROUND_COLOR = "#0b1016"
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

WATER_DARK = "#0b2f47"
WATER_LIGHT = "#1f4f73"
SHORE_DARK = "#bda36f"
SHORE_LIGHT = "#d8c99b"
FIELD_DARK = "#5a7f35"
FIELD_LIGHT = "#8fad4e"
FOREST_DARK = "#1f4526"
FOREST_LIGHT = "#2f5d30"
URBAN_DARK = "#7b7a72"
URBAN_LIGHT = "#a9a59a"


@dataclass
class PlayerConfig:
    max_health: int
    initial_health: int
    max_speed: float
    initial_speed: float


@dataclass
class GameConfig:
    initial_zoom: float
    tile_count: int
    max_zoom: float
    player: PlayerConfig


@dataclass
class EnemyType:
    name: str
    strength: int
    speed: float
    initial_health: int
    attack_speed: float
    appearance: str | None = None

    @property
    def attack_cooldown(self) -> float:
        if self.attack_speed <= 0:
            return float("inf")
        return 1.0 / self.attack_speed


@dataclass
class SpawnEntry:
    enemy: str
    interval_seconds: float


@dataclass
class SpawnRule:
    min_xp: int
    max_xp: Optional[int]
    spawns: List[SpawnEntry] = field(default_factory=list)

    def matches(self, xp: int) -> bool:
        if xp < self.min_xp:
            return False
        if self.max_xp is None:
            return True
        return xp <= self.max_xp


@dataclass
class Enemy:
    enemy_type: EnemyType
    position: Vector2
    health: float
    last_attack_time: float = field(default_factory=lambda: 0.0)
    canvas_id: Optional[int] = None
    health_bar_id: Optional[int] = None
    health_bar_border_id: Optional[int] = None


def load_game_config() -> GameConfig:
    config_data = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            raw_config = json.load(config_file)
    except (FileNotFoundError, json.JSONDecodeError):
        raw_config = {}

    if isinstance(raw_config, dict):
        for key, value in raw_config.items():
            if key == "player" and isinstance(value, dict):
                for stat_key, stat_value in value.items():
                    if stat_key in config_data["player"]:
                        config_data["player"][stat_key] = stat_value
            elif key in config_data:
                config_data[key] = value

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
    player_data = config_data["player"]

    try:
        max_health = int(player_data["max_health"])
    except (TypeError, ValueError):
        max_health = DEFAULT_CONFIG["player"]["max_health"]
    max_health = max(1, max_health)

    try:
        initial_health = int(player_data["initial_health"])
    except (TypeError, ValueError):
        initial_health = DEFAULT_CONFIG["player"]["initial_health"]
    initial_health = max(0, min(initial_health, max_health))

    try:
        max_speed = float(player_data["max_speed"])
    except (TypeError, ValueError):
        max_speed = DEFAULT_CONFIG["player"]["max_speed"]
    max_speed = max(0.0, max_speed)

    try:
        initial_speed_value = float(player_data.get("initial_speed", max_speed))
    except (TypeError, ValueError):
        initial_speed_value = DEFAULT_CONFIG["player"]["initial_speed"]
    initial_speed_value = max(0.0, initial_speed_value)

    player_config = PlayerConfig(
        max_health=max_health,
        initial_health=initial_health,
        max_speed=max_speed,
        initial_speed=initial_speed_value,
    )

    return GameConfig(
        initial_zoom=initial_zoom,
        tile_count=tile_count,
        max_zoom=max_zoom,
        player=player_config,
    )


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
        self.player_config = self.config.player
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
        self.position_label.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=76)

        self.coin_label = tk.Label(
            self.root,
            font=("Helvetica", 14, "bold"),
            fg=HUD_TEXT_COLOR,
            bg=BACKGROUND_COLOR,
            text="Coins: 0",
        )
        self.coin_label.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=20)

        self.speed_label = tk.Label(
            self.root,
            font=("Helvetica", 12, "bold"),
            fg=HUD_TEXT_COLOR,
            bg=BACKGROUND_COLOR,
            text="Laufgeschwindigkeit: 0.00 Felder/s",
        )
        self.speed_label.place(relx=1.0, rely=0.0, anchor="ne", x=-20, y=48)

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
        self.mouse_canvas_position: Vector2 | None = None

        self.max_health = max(1, self.player_config.max_health)
        self.health = max(0, min(self.player_config.initial_health, self.max_health))
        self.forward_speed = max(0.0, self.player_config.initial_speed)
        if self.forward_speed <= 0.0:
            self.forward_speed = max(0.0, self.player_config.max_speed)
        self.xp = 0
        self.xp_to_next_level = 100
        self.coins = 0
        self._update_coin_label()
        self._update_xp_bar()
        self.tile_surface_cache: dict[tuple[int, int], tuple[str, str]] = {}
        self.tile_rectangles: List[int] = []

        self.keys_pressed: set[str] = set()
        self.game_running = False

        self.canvas.bind("<ButtonPress-1>", self._on_mouse_press)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_release)
        self.canvas.bind("<Motion>", self._on_mouse_move)

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

        self.enemy_types = self._load_enemy_types()
        self.spawn_rules = self._load_level_rules()
        self.current_spawn_rule: Optional[SpawnRule] = None
        self.enemy_spawn_handles: Dict[int, str] = {}
        self.enemies: List[Enemy] = []
        self.enemy_colors: Dict[str, str] = {
            "zombie": "#4caf50",
            "skeleton": "#d7d7d7",
            "ogre": "#8d6e63",
        }

        self.intro_overlay = self._create_intro_overlay()

    def _exit_fullscreen(self, _event: tk.Event | None = None) -> None:
        self.root.attributes("-fullscreen", False)

    @staticmethod
    def _blend_channel(channel_a: int, channel_b: int, factor: float) -> int:
        return int(round(channel_a + (channel_b - channel_a) * factor))

    @classmethod
    def _blend_colors(cls, color_a: str, color_b: str, factor: float) -> str:
        factor = max(0.0, min(1.0, factor))
        a_r = int(color_a[1:3], 16)
        a_g = int(color_a[3:5], 16)
        a_b = int(color_a[5:7], 16)
        b_r = int(color_b[1:3], 16)
        b_g = int(color_b[3:5], 16)
        b_b = int(color_b[5:7], 16)
        mixed_r = cls._blend_channel(a_r, b_r, factor)
        mixed_g = cls._blend_channel(a_g, b_g, factor)
        mixed_b = cls._blend_channel(a_b, b_b, factor)
        return f"#{mixed_r:02x}{mixed_g:02x}{mixed_b:02x}"

    @staticmethod
    def _noise(x: float, y: float, seed: float = 0.0, scale: float = 1.0) -> float:
        return 0.5 + 0.5 * math.sin((x * scale * 12.9898 + y * scale * 78.233 + seed) * 43758.5453)

    def _get_tile_surface(self, tile_x: int, tile_y: int) -> tuple[str, str]:
        key = (tile_x % self.tile_count, tile_y % self.tile_count)
        cached = self.tile_surface_cache.get(key)
        if cached is not None:
            return cached

        x, y = key
        continental = self._noise(x, y, seed=0.23, scale=0.035)
        detail = self._noise(x, y, seed=7.1, scale=0.16)
        micro = self._noise(x, y, seed=53.0, scale=0.45)

        if continental < 0.18:
            color = self._blend_colors(WATER_DARK, WATER_LIGHT, detail)
            biome = "water"
        elif continental < 0.24:
            color = self._blend_colors(SHORE_DARK, SHORE_LIGHT, detail)
            biome = "shore"
        else:
            vegetation = self._noise(x, y, seed=101.4, scale=0.18)
            if vegetation < 0.34:
                color = self._blend_colors(FOREST_DARK, FOREST_LIGHT, micro)
                biome = "forest"
            elif vegetation < 0.72:
                alternating = (x + y) % 2
                base = FIELD_DARK if alternating == 0 else FIELD_LIGHT
                accent = FIELD_LIGHT if alternating == 0 else FIELD_DARK
                color = self._blend_colors(base, accent, micro * 0.6 + 0.2)
                biome = "field"
            else:
                color = self._blend_colors(URBAN_DARK, URBAN_LIGHT, micro)
                biome = "urban"

        surface = (color, biome)
        self.tile_surface_cache[key] = surface
        return surface

    def _draw_tile_details(
        self,
        tile_x: int,
        tile_y: int,
        pixel_x: float,
        pixel_y: float,
        tile_size: float,
        biome: str,
    ) -> None:
        normalized_x = tile_x % self.tile_count
        normalized_y = tile_y % self.tile_count

        road_value = self._noise(normalized_x, normalized_y, seed=311.0, scale=0.045)
        if biome in {"field", "urban"} and road_value > 0.975:
            orientation = self._noise(normalized_x, normalized_y, seed=512.0, scale=0.2)
            tone = self._blend_colors(
                URBAN_DARK,
                URBAN_LIGHT,
                self._noise(normalized_x, normalized_y, seed=722.0, scale=0.9),
            )
            road_width = max(2.0, tile_size * 0.08)
            if orientation > 0.5:
                y_center = pixel_y + tile_size * (
                    0.2 + 0.6 * self._noise(normalized_x, normalized_y, seed=845.0, scale=0.6)
                )
                self.canvas.create_rectangle(
                    pixel_x,
                    y_center - road_width,
                    pixel_x + tile_size,
                    y_center + road_width,
                    fill=tone,
                    outline="",
                    tags=("detail",),
                )
            else:
                x_center = pixel_x + tile_size * (
                    0.2 + 0.6 * self._noise(normalized_x, normalized_y, seed=912.0, scale=0.6)
                )
                self.canvas.create_rectangle(
                    x_center - road_width,
                    pixel_y,
                    x_center + road_width,
                    pixel_y + tile_size,
                    fill=tone,
                    outline="",
                    tags=("detail",),
                )

        forest_value = self._noise(normalized_x, normalized_y, seed=128.0, scale=0.3)
        if biome == "forest" and forest_value > 0.62:
            tree_count = 1 + int(self._noise(normalized_x, normalized_y, seed=931.0, scale=0.95) * 3)
            tree_radius = max(2.0, tile_size * 0.08)
            for index in range(tree_count):
                offset_seed = 150.0 + index * 12.0
                offset_x = self._noise(normalized_x, normalized_y, seed=offset_seed, scale=0.8) * (
                    tile_size - tree_radius * 2
                )
                offset_y = self._noise(normalized_x, normalized_y, seed=offset_seed + 4.7, scale=0.8) * (
                    tile_size - tree_radius * 2
                )
                center_x = pixel_x + tree_radius + offset_x
                center_y = pixel_y + tree_radius + offset_y
                foliage_color = self._blend_colors(
                    FOREST_LIGHT,
                    FOREST_DARK,
                    self._noise(normalized_x, normalized_y, seed=offset_seed + 2.3, scale=1.0),
                )
                self.canvas.create_oval(
                    center_x - tree_radius,
                    center_y - tree_radius,
                    center_x + tree_radius,
                    center_y + tree_radius,
                    fill=foliage_color,
                    outline="",
                    tags=("detail",),
                )

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

    def _load_enemy_types(self) -> Dict[str, EnemyType]:
        try:
            with ENEMY_CONFIG_PATH.open("r", encoding="utf-8") as enemy_file:
                raw_data = json.load(enemy_file)
        except (FileNotFoundError, json.JSONDecodeError):
            raw_data = {}

        enemy_types: Dict[str, EnemyType] = {}
        if isinstance(raw_data, dict):
            for name, data in raw_data.items():
                if not isinstance(data, dict):
                    continue
                try:
                    strength = int(data.get("strength", 5))
                    speed = float(data.get("speed", 0.5))
                    initial_health = int(data.get("initial_health", 20))
                    attack_speed = float(data.get("attack_speed", 0.2))
                    appearance = data.get("appearance")
                except (TypeError, ValueError):
                    continue
                enemy_types[name] = EnemyType(
                    name=name,
                    strength=max(1, strength),
                    speed=max(0.0, speed),
                    initial_health=max(1, initial_health),
                    attack_speed=max(0.0, attack_speed),
                    appearance=appearance if isinstance(appearance, str) else None,
                )

        if not enemy_types:
            enemy_types = {
                "zombie": EnemyType(
                    name="zombie",
                    strength=8,
                    speed=0.6,
                    initial_health=50,
                    attack_speed=0.1,
                    appearance=None,
                )
            }
        return enemy_types

    def _load_level_rules(self) -> List[SpawnRule]:
        default_rules = [
            SpawnRule(
                min_xp=0,
                max_xp=99,
                spawns=[SpawnEntry(enemy="zombie", interval_seconds=30.0)],
            ),
            SpawnRule(
                min_xp=100,
                max_xp=200,
                spawns=[
                    SpawnEntry(enemy="zombie", interval_seconds=30.0),
                    SpawnEntry(enemy="skeleton", interval_seconds=30.0),
                ],
            ),
            SpawnRule(
                min_xp=201,
                max_xp=None,
                spawns=[
                    SpawnEntry(enemy="zombie", interval_seconds=25.0),
                    SpawnEntry(enemy="skeleton", interval_seconds=20.0),
                    SpawnEntry(enemy="ogre", interval_seconds=45.0),
                ],
            ),
        ]

        try:
            with LEVEL_CONFIG_PATH.open("r", encoding="utf-8") as level_file:
                raw_data = json.load(level_file)
        except (FileNotFoundError, json.JSONDecodeError):
            raw_data = None

        rules: List[SpawnRule] = []
        if isinstance(raw_data, dict):
            entries = raw_data.get("levels")
        else:
            entries = raw_data

        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                try:
                    min_xp = int(entry.get("min_xp", 0))
                except (TypeError, ValueError):
                    continue
                max_xp_raw = entry.get("max_xp")
                max_xp: Optional[int]
                if max_xp_raw is None:
                    max_xp = None
                else:
                    try:
                        max_xp = int(max_xp_raw)
                    except (TypeError, ValueError):
                        max_xp = None
                spawn_list = entry.get("spawns")
                spawn_entries: List[SpawnEntry] = []
                if isinstance(spawn_list, list):
                    for spawn_entry in spawn_list:
                        if not isinstance(spawn_entry, dict):
                            continue
                        enemy_name = spawn_entry.get("enemy")
                        interval_value = spawn_entry.get("interval_seconds")
                        if not isinstance(enemy_name, str):
                            continue
                        try:
                            interval_seconds = float(interval_value)
                        except (TypeError, ValueError):
                            continue
                        if interval_seconds <= 0:
                            continue
                        if enemy_name not in self.enemy_types:
                            continue
                        spawn_entries.append(
                            SpawnEntry(enemy=enemy_name, interval_seconds=interval_seconds)
                        )
                if spawn_entries:
                    rules.append(SpawnRule(min_xp=min_xp, max_xp=max_xp, spawns=spawn_entries))

        if not rules:
            rules = [rule for rule in default_rules if any(
                spawn.enemy in self.enemy_types for spawn in rule.spawns
            )]

        rules.sort(key=lambda rule: rule.min_xp)
        return rules

    def start_game(self) -> None:
        if self.game_running:
            return
        self.intro_overlay.destroy()
        self._setup_bindings()
        self.game_running = True
        self._update_spawn_schedules(force=True)
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
        self._on_mouse_move(event)

    def _on_mouse_drag(self, event: tk.Event) -> None:  # type: ignore[override]
        if not self.camera_dragging or self._last_mouse_position is None:
            return
        self._on_mouse_move(event)
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

    def _on_mouse_move(self, event: tk.Event) -> None:  # type: ignore[override]
        self.mouse_canvas_position = Vector2(event.x, event.y)

    def _update_facing_direction_from_mouse(self) -> None:
        if self.mouse_canvas_position is None:
            return
        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        tile_size = self.tile_size
        top_left_pixel_x = self.camera_position.x * tile_size - viewport_width / 2
        top_left_pixel_y = self.camera_position.y * tile_size - viewport_height / 2
        player_pixel_x = self.position.x * tile_size - top_left_pixel_x
        player_pixel_y = self.position.y * tile_size - top_left_pixel_y
        direction = Vector2(
            self.mouse_canvas_position.x - player_pixel_x,
            self.mouse_canvas_position.y - player_pixel_y,
        )
        if direction.length() > 0.0:
            self.facing_direction = direction.normalize()

    def _movement_speed_factor(self, movement_direction: Vector2) -> float:
        facing_length = self.facing_direction.length()
        if facing_length == 0.0:
            return 1.0
        facing = self.facing_direction.normalize()
        dot_product = facing.x * movement_direction.x + facing.y * movement_direction.y
        dot_product = max(-1.0, min(1.0, dot_product))
        angle = math.acos(dot_product)
        factor = 1.0 - 0.5 * (angle / math.pi)
        return max(0.5, min(1.0, factor))

    def _apply_input(self) -> None:
        self._update_facing_direction_from_mouse()
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
                speed_factor = self._movement_speed_factor(normalized)
                target_speed = self.forward_speed * speed_factor
                if target_speed <= 0.0:
                    self.velocity = Vector2(0.0, 0.0)
                else:
                    accelerated = self.velocity + normalized * ACCELERATION
                    self.velocity = accelerated.clamp_magnitude(target_speed)
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

        required_tiles = visible_rows * visible_columns
        while len(self.tile_rectangles) < required_tiles:
            rect_id = self.canvas.create_rectangle(0, 0, 0, 0, fill=BACKGROUND_COLOR, outline="")
            self.tile_rectangles.append(rect_id)
            self.canvas.tag_lower(rect_id)
        while len(self.tile_rectangles) > required_tiles:
            rect_id = self.tile_rectangles.pop()
            self.canvas.delete(rect_id)

        tile_index = 0
        for row in range(visible_rows):
            tile_y = start_tile_y + row
            pixel_y = tile_y * tile_size - top_left_pixel_y
            for column in range(visible_columns):
                tile_x = start_tile_x + column
                pixel_x = tile_x * tile_size - top_left_pixel_x
                color, _biome = self._get_tile_surface(tile_x, tile_y)
                rect_id = self.tile_rectangles[tile_index]
                tile_index += 1
                self.canvas.coords(
                    rect_id,
                    pixel_x,
                    pixel_y,
                    pixel_x + tile_size,
                    pixel_y + tile_size,
                )
                self.canvas.itemconfigure(rect_id, fill=color)

        player_pixel_x = self.position.x * tile_size - top_left_pixel_x
        player_pixel_y = self.position.y * tile_size - top_left_pixel_y
        self._update_player_sprite(player_pixel_x, player_pixel_y, tile_size)

        for enemy in self.enemies:
            self._update_enemy_canvas(enemy, top_left_pixel_x, top_left_pixel_y, tile_size)

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
        speed_tiles_per_second = self.velocity.length() * (1000.0 / UPDATE_DELAY_MS)
        if speed_tiles_per_second < 0.005:
            speed_tiles_per_second = 0.0
        self.speed_label.config(text=f"Laufgeschwindigkeit: {speed_tiles_per_second:.2f} Felder/s")

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

    def _update_spawn_schedules(self, force: bool = False) -> None:
        active_rule = None
        for rule in self.spawn_rules:
            if rule.matches(self.xp):
                active_rule = rule
                break
        if not force and active_rule is self.current_spawn_rule:
            return
        self._cancel_spawn_handles()
        self.current_spawn_rule = active_rule
        if active_rule is None:
            return
        for entry in active_rule.spawns:
            self._schedule_spawn_entry(entry)

    def _cancel_spawn_handles(self) -> None:
        for handle in list(self.enemy_spawn_handles.values()):
            try:
                self.root.after_cancel(handle)
            except ValueError:
                pass
        self.enemy_spawn_handles.clear()

    def _schedule_spawn_entry(self, entry: SpawnEntry) -> None:
        delay = max(1, int(entry.interval_seconds * 1000))
        handle = self.root.after(delay, lambda e=entry: self._spawn_enemy_from_entry(e))
        self.enemy_spawn_handles[id(entry)] = handle

    def _spawn_enemy_from_entry(self, entry: SpawnEntry) -> None:
        if not self.game_running:
            return
        enemy_type = self.enemy_types.get(entry.enemy)
        if enemy_type is None:
            return
        spawn_position = self._random_spawn_position()
        enemy = Enemy(
            enemy_type=enemy_type,
            position=spawn_position,
            health=enemy_type.initial_health,
        )
        self.enemies.append(enemy)
        self._schedule_spawn_entry(entry)

    def _random_spawn_position(self) -> Vector2:
        attempts = 5
        for _ in range(attempts):
            x = random.uniform(0, self.tile_count)
            y = random.uniform(0, self.tile_count)
            if self._distance_in_tiles(Vector2(x, y), self.position) > 8.0:
                return Vector2(x, y)
        return Vector2(random.uniform(0, self.tile_count), random.uniform(0, self.tile_count))

    def _distance_in_tiles(self, a: Vector2, b: Vector2) -> float:
        delta_x = self._wrapped_delta(a.x, b.x)
        delta_y = self._wrapped_delta(a.y, b.y)
        return math.hypot(delta_x, delta_y)

    def _update_enemy_canvas(
        self,
        enemy: Enemy,
        top_left_pixel_x: float,
        top_left_pixel_y: float,
        tile_size: float,
    ) -> None:
        pixel_x = enemy.position.x * tile_size - top_left_pixel_x
        pixel_y = enemy.position.y * tile_size - top_left_pixel_y
        radius = tile_size * 0.35
        left = pixel_x - radius
        top = pixel_y - radius
        right = pixel_x + radius
        bottom = pixel_y + radius
        color = self.enemy_colors.get(enemy.enemy_type.name, "#ff7043")
        if enemy.canvas_id is None:
            enemy.canvas_id = self.canvas.create_oval(left, top, right, bottom, fill=color, outline="#1b1b1b", width=2)
        else:
            self.canvas.coords(enemy.canvas_id, left, top, right, bottom)
            self.canvas.itemconfigure(enemy.canvas_id, fill=color)

        bar_width = tile_size * 0.6
        bar_height = 6
        bar_left = pixel_x - bar_width / 2
        bar_right = pixel_x + bar_width / 2
        bar_top = top - 10
        bar_bottom = bar_top + bar_height
        health_ratio = 0.0 if enemy.enemy_type.initial_health <= 0 else max(0.0, min(1.0, enemy.health / enemy.enemy_type.initial_health))
        fill_right = bar_left + bar_width * health_ratio
        fill_right = max(bar_left, min(bar_right, fill_right))
        if enemy.health_bar_id is None:
            enemy.health_bar_id = self.canvas.create_rectangle(
                bar_left,
                bar_top,
                fill_right,
                bar_bottom,
                fill="#ff5d62",
                outline="",
            )
        else:
            self.canvas.coords(enemy.health_bar_id, bar_left, bar_top, fill_right, bar_bottom)
        if enemy.health_bar_border_id is None:
            enemy.health_bar_border_id = self.canvas.create_rectangle(
                bar_left,
                bar_top,
                bar_right,
                bar_bottom,
                outline="#1b1b1b",
                width=1,
            )
        else:
            self.canvas.coords(enemy.health_bar_border_id, bar_left, bar_top, bar_right, bar_bottom)
        if enemy.canvas_id is not None:
            self.canvas.tag_raise(enemy.canvas_id)
        if enemy.health_bar_id is not None:
            self.canvas.tag_raise(enemy.health_bar_id)
        if enemy.health_bar_border_id is not None:
            self.canvas.tag_raise(enemy.health_bar_border_id)

    def _remove_enemy(self, enemy: Enemy) -> None:
        if enemy in self.enemies:
            self.enemies.remove(enemy)
        if enemy.canvas_id is not None:
            self.canvas.delete(enemy.canvas_id)
            enemy.canvas_id = None
        if enemy.health_bar_id is not None:
            self.canvas.delete(enemy.health_bar_id)
            enemy.health_bar_id = None
        if enemy.health_bar_border_id is not None:
            self.canvas.delete(enemy.health_bar_border_id)
            enemy.health_bar_border_id = None

    def _update_enemies(self) -> None:
        self._update_spawn_schedules()
        if not self.enemies:
            return
        delta_time = UPDATE_DELAY_MS / 1000.0
        now = time.monotonic()
        for enemy in list(self.enemies):
            direction = Vector2(
                self._wrapped_delta(enemy.position.x, self.position.x),
                self._wrapped_delta(enemy.position.y, self.position.y),
            )
            distance = direction.length()
            if distance > 0.0:
                move_distance = enemy.enemy_type.speed * delta_time
                if move_distance > 0.0:
                    if distance <= move_distance:
                        enemy.position = Vector2(self.position.x, self.position.y)
                    else:
                        step = direction.normalize() * move_distance
                        enemy.position = Vector2(
                            (enemy.position.x + step.x) % self.tile_count,
                            (enemy.position.y + step.y) % self.tile_count,
                        )
            collision_distance = 0.45
            if distance <= collision_distance:
                cooldown = enemy.enemy_type.attack_cooldown
                if now - enemy.last_attack_time >= cooldown:
                    self.health = max(0, self.health - enemy.enemy_type.strength)
                    enemy.last_attack_time = now
            if enemy.health <= 0:
                self._remove_enemy(enemy)

    def _schedule_next_frame(self) -> None:
        self.root.after(UPDATE_DELAY_MS, self._game_loop)

    def _game_loop(self) -> None:
        if not self.game_running:
            return
        self._apply_input()
        self._update_position()
        self._update_camera()
        self._update_enemies()
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
