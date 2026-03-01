import os, sys, json, threading, re, hashlib, shutil
from dataclasses import dataclass, field
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog

try:
    import customtkinter as ctk
    HAS_CTK = True
except Exception:
    ctk = None
    HAS_CTK = False

import requests
from PIL import Image, ImageDraw, ImageFont, ImageTk
from inventory import (
    InventoryItem,
    InventoryMatcher,
    InventoryRequirement,
    InventorySettings,
    InventoryStore,
    STAT_KEYS,
    calculate_stats,
    normalize_nature_name,
    normalize_stat_key,
)


# =========================
# Paths / Config
# =========================
APP_NAME = "ChansEgg"
LOGGER = logging.getLogger("chansegg")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


@dataclass(frozen=True)
class AppPaths:
    runtime_base: Path
    user_base: Path
    runtime_assets_dir: Path
    runtime_data_json: Path
    runtime_filter_json: Path
    runtime_default_sprite: Path
    runtime_braces_dir: Path
    runtime_type_icon_dir: Path
    runtime_locales_dir: Path
    user_cache_dir: Path
    user_config_dir: Path
    user_data_dir: Path
    user_assets_dir: Path
    user_sprite_cache_dir: Path
    user_pokeapi_cache_dir: Path
    user_type_icon_cache_dir: Path
    user_braces_dir: Path
    user_type_icon_dir: Path
    user_locales_dir: Path
    user_data_json: Path
    user_filter_json: Path
    user_default_sprite: Path
    config_path: Path


def get_runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_user_base_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / "AppData" / "Local" / APP_NAME


def build_app_paths() -> AppPaths:
    runtime_base = get_runtime_base_dir()
    user_base = get_user_base_dir()
    runtime_assets_dir = runtime_base / "assets"
    user_cache_dir = user_base / "cache"
    user_config_dir = user_base / "config"
    user_data_dir = user_base / "data"
    user_assets_dir = user_base / "assets"
    return AppPaths(
        runtime_base=runtime_base,
        user_base=user_base,
        runtime_assets_dir=runtime_assets_dir,
        runtime_data_json=runtime_base / "pokemon.json",
        runtime_filter_json=runtime_base / "pokemmo_species.json",
        runtime_default_sprite=runtime_assets_dir / "default.png",
        runtime_braces_dir=runtime_assets_dir / "braces",
        runtime_type_icon_dir=runtime_assets_dir / "type_icons",
        runtime_locales_dir=runtime_base / "locales",
        user_cache_dir=user_cache_dir,
        user_config_dir=user_config_dir,
        user_data_dir=user_data_dir,
        user_assets_dir=user_assets_dir,
        user_sprite_cache_dir=user_cache_dir / "sprites",
        user_pokeapi_cache_dir=user_cache_dir / "pokeapi",
        user_type_icon_cache_dir=user_cache_dir / "type_icons",
        user_braces_dir=user_cache_dir / "braces",
        user_type_icon_dir=user_assets_dir / "type_icons",
        user_locales_dir=user_base / "locales",
        user_data_json=user_data_dir / "pokemon.json",
        user_filter_json=user_data_dir / "pokemmo_species.json",
        user_default_sprite=user_assets_dir / "default.png",
        config_path=user_config_dir / "theme.json",
    )


def _copy_if_missing(src: Path, dst: Path) -> None:
    if not src.exists() or dst.exists():
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    except Exception as exc:
        print(f"[Paths] cannot copy {src} -> {dst}: {exc}")


def _copytree_if_missing(src: Path, dst: Path) -> None:
    if not src.exists() or dst.exists():
        return
    try:
        shutil.copytree(src, dst)
    except Exception as exc:
        print(f"[Paths] cannot copytree {src} -> {dst}: {exc}")


def ensure_user_dirs_and_migrate(paths: AppPaths) -> None:
    for p in (
        paths.user_base,
        paths.user_cache_dir,
        paths.user_config_dir,
        paths.user_data_dir,
        paths.user_assets_dir,
        paths.user_sprite_cache_dir,
        paths.user_pokeapi_cache_dir,
        paths.user_type_icon_cache_dir,
        paths.user_braces_dir,
        paths.user_type_icon_dir,
        paths.user_locales_dir,
    ):
        p.mkdir(parents=True, exist_ok=True)

    # Seed user files from bundled runtime resources when available.
    _copy_if_missing(paths.runtime_data_json, paths.user_data_json)
    _copy_if_missing(paths.runtime_filter_json, paths.user_filter_json)
    _copy_if_missing(paths.runtime_default_sprite, paths.user_default_sprite)
    _copytree_if_missing(paths.runtime_type_icon_dir, paths.user_type_icon_dir)
    _copytree_if_missing(paths.runtime_braces_dir, paths.user_braces_dir)
    _copytree_if_missing(paths.runtime_locales_dir, paths.user_locales_dir)

    # Legacy migration from previous writable app layout.
    legacy_base = Path(__file__).resolve().parent
    if legacy_base != paths.user_base:
        _copy_if_missing(legacy_base / "config" / "theme.json", paths.config_path)
        _copytree_if_missing(legacy_base / "cache" / "sprites", paths.user_sprite_cache_dir)
        _copytree_if_missing(legacy_base / "cache" / "pokeapi", paths.user_pokeapi_cache_dir)
        _copytree_if_missing(legacy_base / "cache" / "type_icons", paths.user_type_icon_cache_dir)
        _copytree_if_missing(legacy_base / "assets" / "type_icons", paths.user_type_icon_dir)
        _copytree_if_missing(legacy_base / "assets" / "braces", paths.user_braces_dir)
        _copy_if_missing(legacy_base / "pokemon.json", paths.user_data_json)
        _copy_if_missing(legacy_base / "pokemmo_species.json", paths.user_filter_json)
        _copy_if_missing(legacy_base / "assets" / "default.png", paths.user_default_sprite)

    print(f"[Paths] runtime_base={paths.runtime_base}")
    print(f"[Paths] user_base={paths.user_base}")
    print("[Paths] write_targets=LOCALAPPDATA only")


APP_PATHS = build_app_paths()
ensure_user_dirs_and_migrate(APP_PATHS)

APP_DIR = str(APP_PATHS.runtime_base)  # kept for compatibility
RUNTIME_BASE_DIR = str(APP_PATHS.runtime_base)
USER_BASE_DIR = str(APP_PATHS.user_base)
RUNTIME_ASSETS_DIR = str(APP_PATHS.runtime_assets_dir)
RUNTIME_DATA_JSON_PATH = str(APP_PATHS.runtime_data_json)
RUNTIME_FILTER_PATH = str(APP_PATHS.runtime_filter_json)
RUNTIME_DEFAULT_SPRITE_PATH = str(APP_PATHS.runtime_default_sprite)
RUNTIME_BRACES_DIR = str(APP_PATHS.runtime_braces_dir)
RUNTIME_TYPE_ICON_DIR = str(APP_PATHS.runtime_type_icon_dir)
RUNTIME_LOCALES_DIR = str(APP_PATHS.runtime_locales_dir)

DATA_JSON_PATH = str(APP_PATHS.user_data_json)
POKEMMO_SPECIES_PATH = str(APP_PATHS.user_filter_json)
CONFIG_DIR = str(APP_PATHS.user_config_dir)
THEME_CONFIG_PATH = str(APP_PATHS.config_path)
SPRITE_CACHE_DIR = str(APP_PATHS.user_sprite_cache_dir)
POKEAPI_CACHE_DIR = str(APP_PATHS.user_pokeapi_cache_dir)
ASSETS_DIR = str(APP_PATHS.user_assets_dir)
BRACES_DIR = str(APP_PATHS.user_braces_dir)
TYPE_ICON_DIR = str(APP_PATHS.user_type_icon_dir)
TYPE_ICON_CACHE_DIR = str(APP_PATHS.user_type_icon_cache_dir)
DEFAULT_SPRITE_PATH = str(APP_PATHS.user_default_sprite)
LOCALES_DIR = str(APP_PATHS.user_locales_dir)
APP_VERSION = "1.0.1"
UPDATER_CONFIG_PATH = os.path.join(CONFIG_DIR, "updater.json")
UI_CONFIG_PATH = os.path.join(CONFIG_DIR, "ui.json")
INVENTORY_JSON_PATH = os.path.join(str(APP_PATHS.user_data_dir), "inventory.json")
INVENTORY_SETTINGS_PATH = os.path.join(CONFIG_DIR, "inventory_settings.json")

STATS = ["HP", "Atk", "Def", "SpA", "SpD", "Spe"]

# Braces
BRACE_COST = 10_000
EVERSTONE_COST = 2_000
POKEBALL_COST = 200
GENDER_SELECTION_COST = 5_000

# Servicio de crianza (gratis según el usuario)
BREED_SERVICE_COST = 0

# Costos de género (según las reglas del usuario)
GENDER_COST_50_50 = {"M": 5_000, "F": 5_000}
GENDER_COST_75_25 = {"M": 9_000, "F": 21_000}
GENDER_COST_87_5_12_5 = {"M": 5_000, "F": 21_000}

POKEAPI_SPECIES_LIST = "https://pokeapi.co/api/v2/pokemon-species?limit=2000"
POKEAPI_SPECIES_BY_ID = "https://pokeapi.co/api/v2/pokemon-species/{id}/"
POKEAPI_POKEMON_BY_ID = "https://pokeapi.co/api/v2/pokemon/{id}/"
POKEAPI_POKEMON_ENCOUNTERS = "https://pokeapi.co/api/v2/pokemon/{id}/encounters"

# Sprite raw by ID
RAW_SPRITE_URL = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{id}.png"
POKEAPI_ITEM_BY_NAME = "https://pokeapi.co/api/v2/item/{name}/"

NATURE_NONE = "Ninguna (Aleatoria)"
NATURE_OPTIONS = [
    NATURE_NONE,
    "Hardy (Fuerte) [Neutral]",
    "Lonely (Huraña) +Atk -Def",
    "Brave (Audaz) +Atk -Spe",
    "Adamant (Firme) +Atk -SpA",
    "Naughty (Pícara) +Atk -SpD",
    "Bold (Osada) +Def -Atk",
    "Docile (Dócil) [Neutral]",
    "Relaxed (Plácida) +Def -Spe",
    "Impish (Agitada) +Def -SpA",
    "Lax (Floja) +Def -SpD",
    "Timid (Miedosa) +Spe -Atk",
    "Hasty (Activa) +Spe -Def",
    "Serious (Seria) [Neutral]",
    "Jolly (Alegre) +Spe -SpA",
    "Naive (Ingenua) +Spe -SpD",
    "Modest (Modesta) +SpA -Atk",
    "Mild (Afable) +SpA -Def",
    "Quiet (Mansa) +SpA -Spe",
    "Bashful (Tímida) [Neutral]",
    "Rash (Alocada) +SpA -SpD",
    "Calm (Calmada) +SpD -Atk",
    "Gentle (Amable) +SpD -Def",
    "Sassy (Grosera) +SpD -Spe",
    "Careful (Cauta) +SpD -SpA",
    "Quirky (Rara) [Neutral]",
]

IV_COLORS = {
    "HP": "#5EE173",
    "Atk": "#FF5C5C",
    "Def": "#FF9F43",
    "SpA": "#60A5FA",
    "SpD": "#A78BFA",
    "Spe": "#FF79C6",
}

TYPE_COLORS = {
    "normal": "#A8A77A",
    "fire": "#EE8130",
    "water": "#6390F0",
    "electric": "#F7D02C",
    "grass": "#7AC74C",
    "ice": "#96D9D6",
    "fighting": "#C22E28",
    "poison": "#A33EA1",
    "ground": "#8B6B3F",
    "flying": "#A98FF3",
    "psychic": "#F95587",
    "bug": "#A6B91A",
    "rock": "#B6A136",
    "ghost": "#735797",
    "dragon": "#6F35FC",
    "dark": "#705746",
    "steel": "#B7B7CE",
    "fairy": "#D685AD",
}

TYPE_NAMES_LOCALIZED = {
    "es": {
        "normal": "Normal",
        "fire": "Fuego",
        "water": "Agua",
        "electric": "Eléctrico",
        "grass": "Planta",
        "ice": "Hielo",
        "fighting": "Lucha",
        "poison": "Veneno",
        "ground": "Tierra",
        "flying": "Volador",
        "psychic": "Psíquico",
        "bug": "Bicho",
        "rock": "Roca",
        "ghost": "Fantasma",
        "dragon": "Dragón",
        "dark": "Siniestro",
        "steel": "Acero",
        "fairy": "Hada",
    },
    "en": {
        "normal": "Normal",
        "fire": "Fire",
        "water": "Water",
        "electric": "Electric",
        "grass": "Grass",
        "ice": "Ice",
        "fighting": "Fighting",
        "poison": "Poison",
        "ground": "Ground",
        "flying": "Flying",
        "psychic": "Psychic",
        "bug": "Bug",
        "rock": "Rock",
        "ghost": "Ghost",
        "dragon": "Dragon",
        "dark": "Dark",
        "steel": "Steel",
        "fairy": "Fairy",
    },
    "zh": {
        "normal": "一般",
        "fire": "火",
        "water": "水",
        "electric": "电",
        "grass": "草",
        "ice": "冰",
        "fighting": "格斗",
        "poison": "毒",
        "ground": "地面",
        "flying": "飞行",
        "psychic": "超能力",
        "bug": "虫",
        "rock": "岩石",
        "ghost": "幽灵",
        "dragon": "龙",
        "dark": "恶",
        "steel": "钢",
        "fairy": "妖精",
    },
}

PALETTES = {
    "Morada": ["#522566", "#7A3A8E", "#AD74C3", "#EADFF0", "#F8EDFB"],
    "Verde oscuro": ["#051F20", "#173831", "#235347", "#8CB79B", "#DBF0DD"],
    "Marron/Beige": ["#472825", "#96786F", "#D3AB80", "#FDE4BC", "#FFF4E2"],
    "Azul": ["#0B1F3A", "#1E3A5F", "#2E5D8A", "#75AADB", "#E2F0FF"],
    "Roja": ["#3A0B0B", "#6E1F1F", "#A63A3A", "#E48C8C", "#FFE8E8"],
}


# =========================
# Models
# =========================
@dataclass
class PokemonEntry:
    id: int
    name: str


@dataclass
class BreedingRequest:
    pokemon: PokemonEntry
    desired_31: Dict[str, bool]
    desired_nature: str = NATURE_NONE
    keep_nature: bool = False


@dataclass
class GenderPlanLayer:
    label: str
    count: int
    need_m: int
    need_f: int
    selectable: bool


@dataclass
class BreedingNode:
    ivs: Tuple[str, ...]
    gender: str = "M"
    has_nature: bool = False
    item: Optional[str] = None  # stat name or "EVERSTONE"
    is_nature_branch: bool = False
    branch_role: str = "primary"  # nature | nature_donor | primary
    cost_gender: int = 0
    cost_ball: int = POKEBALL_COST
    is_base: bool = False
    tree_id: int = 0
    slot: int = 0
    is_fusion_donor: bool = False
    fusion_level: int = 0


@dataclass
class BreedingPlan:
    k: int
    parents_needed: int
    breeds_needed: int
    braces_needed: int
    braces_cost: int
    braces_by_level: List[Tuple[str, int]] = field(default_factory=list)
    extra_breeds_nature: int = 0
    everstone_cost: int = 0
    nature_selected: bool = False
    desired_nature: str = NATURE_NONE
    gender_layers: List[GenderPlanLayer] = field(default_factory=list)
    gender_selections: Dict[str, int] = field(default_factory=dict)
    gender_cost_total: int = 0
    balls_used: int = 0
    balls_cost: int = 0
    total_cost: int = 0
    levels: List[Tuple[str, int]] = field(default_factory=list)
    level_nodes: List[Tuple[str, List[str]]] = field(default_factory=list)
    node_layers: List[List[BreedingNode]] = field(default_factory=list)
    connections: List[Tuple[Tuple[int, int], Tuple[int, int]]] = field(default_factory=list)
    everstone_uses: int = 0
    notes: List[str] = field(default_factory=list)


@dataclass
class ThemeConfig:
    palette: str = "Verde oscuro"
    mode: str = "dark"  # dark | light


@dataclass
class PaletteDefinition:
    name: str
    tones: List[str]


@dataclass
class UIConfig:
    language: str = "es"


class ThemeManager:
    def __init__(self, config_path: str = THEME_CONFIG_PATH):
        self.config_path = config_path

    @staticmethod
    def _hex_to_rgb(color: str) -> Tuple[int, int, int]:
        c = color.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)

    @staticmethod
    def _rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
        r, g, b = rgb
        return f"#{max(0,min(255,r)):02X}{max(0,min(255,g)):02X}{max(0,min(255,b)):02X}"

    @classmethod
    def _mix(cls, c1: str, c2: str, ratio: float) -> str:
        r1, g1, b1 = cls._hex_to_rgb(c1)
        r2, g2, b2 = cls._hex_to_rgb(c2)
        r = int(r1 * (1.0 - ratio) + r2 * ratio)
        g = int(g1 * (1.0 - ratio) + g2 * ratio)
        b = int(b1 * (1.0 - ratio) + b2 * ratio)
        return cls._rgb_to_hex((r, g, b))

    def load(self) -> ThemeConfig:
        if not os.path.exists(self.config_path):
            cfg = ThemeConfig()
            self.save(cfg)
            return cfg
        try:
            with open(self.config_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            palette = data.get("palette", ThemeConfig.palette)
            mode = data.get("mode", ThemeConfig.mode)
            if palette not in PALETTES:
                palette = ThemeConfig.palette
            if mode not in ("dark", "light"):
                mode = ThemeConfig.mode
            return ThemeConfig(palette=palette, mode=mode)
        except Exception as exc:
            print(f"[ThemeManager] invalid theme config: {exc}")
            return ThemeConfig()

    def save(self, cfg: ThemeConfig) -> None:
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"palette": cfg.palette, "mode": cfg.mode}, f, ensure_ascii=False, indent=2)

    def build_theme(self, cfg: ThemeConfig) -> Dict[str, str]:
        tones = PALETTES.get(cfg.palette, PALETTES["Verde oscuro"])
        t1, t2, t3, t4, t5 = tones
        if cfg.mode == "dark":
            # Strong readability in dark mode with palette-derived accents.
            bg = self._mix("#0B0F16", t1, 0.24)
            panel = self._mix("#121A26", t2, 0.26)
            panel_alt = self._mix("#162131", t3, 0.26)
            fg = "#EDF3FB"
            muted = self._mix("#B7C2D2", t4, 0.20)
            border = self._mix("#44556B", t3, 0.30)
            entry_bg = self._mix(panel, bg, 0.46)
            canvas_bg = self._mix(bg, "#070A0F", 0.38)
            grid = self._mix(border, canvas_bg, 0.58)
            accent = self._mix(self._mix(t3, t4, 0.55), "#E6EEF9", 0.20)
            node_fill = self._mix(panel_alt, "#23354C", 0.28)
            nature_fill = self._mix(self._mix(t1, t3, 0.56), "#7B4B1B", 0.32)
            node_shadow = self._mix(canvas_bg, "#000000", 0.46)
            edge_pure = self._mix(self._mix(t3, t4, 0.50), "#D7E4F7", 0.16)
            edge_fusion = self._mix(self._mix(t2, t4, 0.56), "#D7E4F7", 0.20)
            edge_nature = self._mix(self._mix(t1, t3, 0.56), "#E9D3A3", 0.18)
        else:
            # Strong readability in light mode, avoiding washed-out white surfaces.
            bg = self._mix("#F0F4FA", t5, 0.26)
            panel = self._mix("#E7EDF6", t4, 0.30)
            panel_alt = self._mix("#DEE6F2", t3, 0.24)
            fg = "#13243A"
            muted = self._mix("#5A6C84", t2, 0.14)
            border = self._mix("#A9B9CD", t3, 0.30)
            entry_bg = self._mix("#FFFFFF", t5, 0.08)
            canvas_bg = self._mix("#F4F8FF", t5, 0.22)
            grid = self._mix("#C3D1E6", t3, 0.26)
            accent = self._mix(self._mix(t2, t3, 0.48), "#1B3858", 0.20)
            node_fill = self._mix("#FFFFFF", panel_alt, 0.36)
            nature_fill = self._mix(self._mix(t4, t5, 0.48), "#ECD3B4", 0.30)
            node_shadow = self._mix(panel_alt, "#6E7E95", 0.24)
            edge_pure = self._mix(self._mix(t3, t2, 0.54), "#31597E", 0.18)
            edge_fusion = self._mix(self._mix(t2, t4, 0.52), "#2D4F73", 0.18)
            edge_nature = self._mix(self._mix(t1, t3, 0.52), "#8A6336", 0.18)

        return {
            "bg": bg,
            "panel": panel,
            "panel_alt": panel_alt,
            "fg": fg,
            "muted": muted,
            "border": border,
            "entry_bg": entry_bg,
            "entry_fg": fg,
            "listbox_bg": entry_bg,
            "listbox_fg": fg,
            "listbox_sel_bg": accent,
            "listbox_sel_fg": "#081018" if cfg.mode == "light" else "#F8FAFF",
            "canvas_bg": canvas_bg,
            "grid": grid,
            "node_fill": node_fill,
            "nature_fill": nature_fill,
            "node_shadow": node_shadow,
            "edge_pure": edge_pure,
            "edge_fusion": edge_fusion,
            "edge_nature": edge_nature,
            "iv_off_bg": self._mix(entry_bg, panel, 0.25),
            "iv_off_fg": muted,
            "accent": accent,
            "text_box_bg": entry_bg,
            "text_box_fg": fg,
            "info_tab_bg": self._mix(panel_alt, bg, 0.10),
            "info_tab_active_bg": self._mix(accent, panel, 0.22),
            "info_tab_fg": fg,
            "info_table_header_bg": self._mix(panel_alt, accent, 0.16),
            "info_table_row_bg": self._mix(entry_bg, panel, 0.08),
            "info_table_row_alt_bg": self._mix(entry_bg, panel_alt, 0.12),
            "info_bar_bg": self._mix(entry_bg, panel, 0.20),
        }


class I18nManager:
    SUPPORTED = ("es", "en", "zh")

    def __init__(self, user_locales_dir: str = LOCALES_DIR, runtime_locales_dir: str = RUNTIME_LOCALES_DIR, config_path: str = UI_CONFIG_PATH):
        self.user_locales_dir = user_locales_dir
        self.runtime_locales_dir = runtime_locales_dir
        self.config_path = config_path
        self._cache: Dict[str, Dict[str, str]] = {}

    def load_ui_config(self) -> UIConfig:
        if not os.path.exists(self.config_path):
            cfg = UIConfig()
            self.save_ui_config(cfg)
            return cfg
        try:
            with open(self.config_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            lang = str(data.get("language", "es")).strip().lower()
            if lang not in self.SUPPORTED:
                lang = "en"
            return UIConfig(language=lang)
        except Exception as exc:
            LOGGER.debug("Invalid UI config at %s: %s", self.config_path, exc)
            return UIConfig(language="en")

    def save_ui_config(self, cfg: UIConfig) -> None:
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump({"language": cfg.language}, f, ensure_ascii=False, indent=2)

    def _load_lang(self, lang: str) -> Dict[str, str]:
        if lang in self._cache:
            return self._cache[lang]
        candidates = [
            os.path.join(self.runtime_locales_dir, f"{lang}.json"),
            os.path.join(self.user_locales_dir, f"{lang}.json"),
        ]
        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                flat = {str(k): str(v) for k, v in (data or {}).items()}
                self._cache[lang] = flat
                return flat
            except Exception as exc:
                LOGGER.debug("Invalid locale file %s: %s", path, exc)
        self._cache[lang] = {}
        return self._cache[lang]

    def t(self, lang: str, key: str, **kwargs) -> str:
        primary = self._load_lang(lang).get(key, "")
        if not primary:
            primary = self._load_lang("en").get(key, key)
        try:
            return primary.format(**kwargs)
        except Exception:
            return primary


# =========================
# Data layer (pokemon.json con id + name)
# =========================
class PokemonRepository:
    """
    pokemon.json:
    {
      "pokemon": [{"id": 1, "name": "bulbasaur"}, ...]
    }
    """
    DEFAULT_EXCLUDE_IDS = sorted({
        # No-criables / especiales (Gen 1-5) y legendarios/mythicals comunes no breed.
        30, 31, 144, 145, 146, 150, 151, 172, 173, 174, 175, 201, 236, 238, 239, 240,
        243, 244, 245, 249, 250, 251, 298, 360, 377, 378, 379, 380, 381, 382, 383, 384,
        385, 386, 406, 433, 438, 439, 440, 446, 447, 458, 480, 481, 482, 483, 484, 485,
        486, 487, 488, 489, 490, 491, 492, 493, 494, 638, 639, 640, 641, 642, 643, 644,
        645, 646, 647, 648, 649,
    })

    def __init__(
        self,
        path: str = DATA_JSON_PATH,
        pokemmo_filter_path: str = POKEMMO_SPECIES_PATH,
        runtime_path: str = RUNTIME_DATA_JSON_PATH,
        runtime_filter_path: str = RUNTIME_FILTER_PATH,
    ):
        self.path = path
        self.pokemmo_filter_path = pokemmo_filter_path
        self.runtime_path = runtime_path
        self.runtime_filter_path = runtime_filter_path
        self.items: List[PokemonEntry] = []

    def load(self) -> List[PokemonEntry]:
        local_items = self._load_local()
        if local_items:
            self.items = sorted(self._apply_pokemmo_filter(local_items), key=lambda e: e.name.lower())
            return self.items
        print("[Repo] pokemon.json missing/empty, bootstrapping from PokeAPI...")
        try:
            items = self._bootstrap_from_pokeapi()
            if not items:
                raise RuntimeError("PokeAPI returned empty species list")
            self.items = sorted(self._apply_pokemmo_filter(items), key=lambda e: e.name.lower())
            self.save(self.items)
            print(f"[Repo] bootstrapped {len(self.items)} species")
            return self.items
        except Exception as exc:
            print(f"[Repo] bootstrap failed: {exc}")
            raise RuntimeError(
                "No se pudieron cargar Pokemon desde PokeAPI y pokemon.json esta vacio. "
                "Verifica internet o usa pokemon.json local."
            ) from exc
    def _load_local(self) -> List[PokemonEntry]:
        source_path = self.path if os.path.exists(self.path) else self.runtime_path
        if not source_path or not os.path.exists(source_path):
            return []
        try:
            with open(source_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            print(f"[Repo] invalid pokemon.json at {source_path}: {exc}")
            raise RuntimeError(f"pokemon.json invalido: {exc}") from exc
        arr = data.get("pokemon", [])
        out: List[PokemonEntry] = []
        for x in arr:
            try:
                out.append(PokemonEntry(int(x["id"]), str(x["name"])))
            except Exception:
                continue
        return out
    def save(self, items: List[PokemonEntry]) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"pokemon": [{"id": p.id, "name": p.name} for p in items]}, f, ensure_ascii=False, indent=2)

    def _bootstrap_from_pokeapi(self) -> List[PokemonEntry]:
        r = requests.get(POKEAPI_SPECIES_LIST, timeout=20)
        r.raise_for_status()
        results = r.json().get("results", [])

        out: List[PokemonEntry] = []
        for it in results:
            name = it.get("name")
            url = it.get("url", "")
            m = re.search(r"/pokemon-species/(\d+)/", url)
            if name and m:
                out.append(PokemonEntry(id=int(m.group(1)), name=name))
        return out

    def _ensure_default_pokemmo_filter(self) -> None:
        if os.path.exists(self.pokemmo_filter_path):
            return
        if self.runtime_filter_path and os.path.exists(self.runtime_filter_path):
            try:
                os.makedirs(os.path.dirname(self.pokemmo_filter_path), exist_ok=True)
                shutil.copy2(self.runtime_filter_path, self.pokemmo_filter_path)
                return
            except Exception as exc:
                print(f"[Repo] failed to copy runtime filter to user path: {exc}")
        allowed = list(range(1, 650))  # Gen1..Gen5 base
        payload = {
            "version": 1,
            "notes": "Base Pokemmo allowlist (Gen1-5). Edita exclude_ids/allowed_ids si necesitas ajustar species.",
            "allowed_ids": allowed,
            "exclude_ids": self.DEFAULT_EXCLUDE_IDS,
        }
        try:
            os.makedirs(os.path.dirname(self.pokemmo_filter_path), exist_ok=True)
            with open(self.pokemmo_filter_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[Repo] failed to create {self.pokemmo_filter_path}: {exc}")

    def _load_pokemmo_filter(self) -> Tuple[set, set]:
        self._ensure_default_pokemmo_filter()
        try:
            with open(self.pokemmo_filter_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            allowed = {int(x) for x in data.get("allowed_ids", [])}
            excluded = {int(x) for x in data.get("exclude_ids", [])}
            return allowed, excluded
        except Exception as exc:
            print(f"[Repo] invalid pokemmo filter, using defaults: {exc}")
            return set(range(1, 650)), set(self.DEFAULT_EXCLUDE_IDS)

    def _apply_pokemmo_filter(self, items: List[PokemonEntry]) -> List[PokemonEntry]:
        allowed, excluded = self._load_pokemmo_filter()
        filtered = [p for p in items if p.id in allowed and p.id not in excluded]
        if not filtered:
            print("[Repo] warning: pokemmo filter returned 0 items; fallback to original list")
            return items
        return filtered

Repo = PokemonRepository


# =========================
# Species info (gender_rate)
# =========================
class SpeciesInfoService:
    """
    PokeAPI species: gender_rate (0..8) en octavos de hembra, -1 genderless.
    """
    VERSION_GROUP_TO_VERSIONS = {
        "black-white": {"black", "white"},
    }
    STAT_ORDER = {
        "hp": 0,
        "attack": 1,
        "defense": 2,
        "special-attack": 3,
        "special-defense": 4,
        "speed": 5,
    }
    STAT_NAME_MAP = {
        "hp": "HP",
        "attack": "Atk",
        "defense": "Def",
        "special-attack": "SpA",
        "special-defense": "SpD",
        "speed": "Spe",
    }
    MOVE_METHOD_LABELS = {
        "level-up": "Level",
        "egg": "Egg",
        "machine": "TM/HM",
        "tutor": "Tutor",
    }
    VERSION_REGION_HINT = {
        "red": "Kanto",
        "blue": "Kanto",
        "yellow": "Kanto",
        "gold": "Johto",
        "silver": "Johto",
        "crystal": "Johto",
        "ruby": "Hoenn",
        "sapphire": "Hoenn",
        "emerald": "Hoenn",
        "firered": "Kanto",
        "leafgreen": "Kanto",
        "diamond": "Sinnoh",
        "pearl": "Sinnoh",
        "platinum": "Sinnoh",
        "heartgold": "Johto",
        "soulsilver": "Johto",
        "black": "Teselia",
        "white": "Teselia",
        "black-2": "Teselia",
        "white-2": "Teselia",
    }

    def __init__(self):
        self._cache: Dict[int, int] = {}
        self._species_payload: Dict[int, dict] = {}
        self._types_cache: Dict[int, List[str]] = {}
        self._pokemon_payload: Dict[int, dict] = {}
        self._detail_cache: Dict[Tuple[int, str, str], dict] = {}
        self._url_payload_cache: Dict[str, dict] = {}
        self._move_payload_cache: Dict[str, dict] = {}
        self._encounter_cache: Dict[Tuple[int, str], List[dict]] = {}
        self._evolution_cache: Dict[Tuple[int, str], List[List[dict]]] = {}
        self._location_cache: Dict[str, str] = {}
        self._machine_item_cache: Dict[str, str] = {}

    @staticmethod
    def _pretty_name(name: str) -> str:
        if not name:
            return "—"
        return name.replace("-", " ").title()

    @staticmethod
    def _localized_payload_name(payload: dict, language: str, fallback: str = "—") -> str:
        lang = (language or "en").strip().lower()
        if lang == "zh":
            order = ("zh-Hans", "zh-Hant", "zh", "en", "es")
        elif lang == "es":
            order = ("es", "en", "zh-Hans", "zh-Hant")
        else:
            order = ("en", "es", "zh-Hans", "zh-Hant")
        names = payload.get("names", []) or []
        for wanted in order:
            wanted_l = wanted.lower()
            for row in names:
                row_lang = str((row.get("language", {}) or {}).get("name", "")).strip().lower()
                if row_lang != wanted_l:
                    continue
                n = str(row.get("name", "") or "").strip()
                if n:
                    return n
        return fallback

    @staticmethod
    def _extract_id_from_url(url: str) -> Optional[int]:
        if not url:
            return None
        m = re.search(r"/(\d+)/?$", url)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    @staticmethod
    def _safe_int(v, default: int = 0) -> int:
        try:
            return int(v)
        except Exception:
            return default

    def _fetch_json_url(self, url: str) -> dict:
        if not url:
            return {}
        cached = self._url_payload_cache.get(url)
        if cached is not None:
            return cached
        cache_key = hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json"
        cache_path = os.path.join(POKEAPI_CACHE_DIR, cache_key)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._url_payload_cache[url] = data
                return data
            except Exception as exc:
                print(f"[SpeciesInfoService] invalid cache {cache_path}: {exc}")
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception as exc:
            print(f"[SpeciesInfoService] cannot write cache {cache_path}: {exc}")
        self._url_payload_cache[url] = data
        return data

    def _get_species_payload(self, species_id: int) -> dict:
        if species_id in self._species_payload:
            return self._species_payload[species_id]
        r = requests.get(POKEAPI_SPECIES_BY_ID.format(id=species_id), timeout=20)
        r.raise_for_status()
        data = r.json()
        self._species_payload[species_id] = data
        return data

    def get_gender_rate(self, species_id: int) -> int:
        if species_id in self._cache:
            return self._cache[species_id]
        data = self._get_species_payload(species_id)
        gr = int(data.get("gender_rate", -1))
        self._cache[species_id] = gr
        return gr

    def get_egg_groups(self, species_id: int) -> List[str]:
        data = self._get_species_payload(species_id)
        groups = data.get("egg_groups", [])
        return [g.get("name", "").title() for g in groups if g.get("name")]

    def get_types(self, species_id: int) -> List[str]:
        if species_id in self._types_cache:
            return self._types_cache[species_id]
        data = self._get_pokemon_payload(species_id)
        ordered = sorted(data.get("types", []), key=lambda t: t.get("slot", 99))
        out = [x.get("type", {}).get("name", "") for x in ordered if x.get("type", {}).get("name")]
        self._types_cache[species_id] = out
        return out

    def _get_pokemon_payload(self, species_id: int) -> dict:
        if species_id in self._pokemon_payload:
            return self._pokemon_payload[species_id]
        r = requests.get(POKEAPI_POKEMON_BY_ID.format(id=species_id), timeout=20)
        r.raise_for_status()
        data = r.json()
        self._pokemon_payload[species_id] = data
        return data

    def _versions_for_group(self, version_group: str) -> set:
        return set(self.VERSION_GROUP_TO_VERSIONS.get(version_group, {version_group}))

    def _get_flavor_text(self, species: dict, language: str = "en") -> str:
        entries = species.get("flavor_text_entries", []) or []
        lang = (language or "en").strip().lower()
        if lang == "zh":
            order = ("zh-hans", "zh-hant", "zh", "en", "es")
        elif lang == "es":
            order = ("es", "en", "zh-hans", "zh-hant")
        else:
            order = ("en", "es", "zh-hans", "zh-hant")
        for wanted_lang in order:
            for row in entries:
                row_lang = str((row.get("language", {}) or {}).get("name", "")).strip().lower()
                if row_lang != wanted_lang:
                    continue
                raw = (row.get("flavor_text", "") or "").replace("\n", " ").replace("\f", " ").strip()
                if raw:
                    return raw
        return "—"

    def _build_ev_yield(self, stats: List[dict]) -> str:
        parts: List[str] = []
        for s in stats:
            ev = self._safe_int(s.get("effort", 0), 0)
            if ev <= 0:
                continue
            parts.append(f"+{ev} {s.get('name', '—')}")
        return ", ".join(parts) if parts else "—"

    def _get_move_payload(self, move_url: str) -> dict:
        if not move_url:
            return {}
        if move_url in self._move_payload_cache:
            return self._move_payload_cache[move_url]
        data = self._fetch_json_url(move_url)
        self._move_payload_cache[move_url] = data
        return data

    def _get_machine_item_name(self, machine_url: str) -> str:
        if not machine_url:
            return ""
        if machine_url in self._machine_item_cache:
            return self._machine_item_cache[machine_url]
        item_name = ""
        try:
            payload = self._fetch_json_url(machine_url)
            item_name = (payload.get("item", {}) or {}).get("name", "") or ""
        except Exception as exc:
            print(f"[SpeciesInfoService] machine payload failed for {machine_url}: {exc}")
        self._machine_item_cache[machine_url] = item_name
        return item_name

    def _build_moves(self, pokemon: dict, version_group: str, language: str = "en") -> List[dict]:
        rows: List[dict] = []
        seen = set()
        move_entries: List[Tuple[str, str, List[dict]]] = []
        for m in pokemon.get("moves", []) or []:
            vg_details = [
                det
                for det in (m.get("version_group_details", []) or [])
                if det.get("version_group", {}).get("name", "") == version_group
            ]
            if not vg_details:
                continue
            move_name = m.get("move", {}).get("name", "")
            move_url = m.get("move", {}).get("url", "")
            move_entries.append((move_name, move_url, vg_details))

        payload_by_url: Dict[str, dict] = {}
        unique_urls = sorted({url for _, url, _ in move_entries if url})
        if unique_urls:
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(self._get_move_payload, url): url for url in unique_urls}
                for fut in as_completed(futures):
                    url = futures[fut]
                    try:
                        payload_by_url[url] = fut.result()
                    except Exception as exc:
                        payload_by_url[url] = {}
                        print(f"[SpeciesInfoService] move payload failed for {url}: {exc}")

        # Resolve machine item names (needed to split MT/MO).
        machine_item_by_url: Dict[str, str] = {}
        machine_urls: set = set()
        for _, move_url, vg_details in move_entries:
            if not any((d.get("move_learn_method", {}) or {}).get("name", "") == "machine" for d in vg_details):
                continue
            mp = payload_by_url.get(move_url, {}) or {}
            for mach in mp.get("machines", []) or []:
                vg = (mach.get("version_group", {}) or {}).get("name", "")
                if vg != version_group:
                    continue
                mu = (mach.get("machine", {}) or {}).get("url", "")
                if mu:
                    machine_urls.add(mu)
        if machine_urls:
            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = {executor.submit(self._get_machine_item_name, mu): mu for mu in sorted(machine_urls)}
                for fut in as_completed(futures):
                    mu = futures[fut]
                    try:
                        machine_item_by_url[mu] = fut.result() or ""
                    except Exception:
                        machine_item_by_url[mu] = ""

        for raw_move_name, move_url, vg_details in move_entries:
            move_payload = payload_by_url.get(move_url, {})
            move_name = self._localized_payload_name(
                move_payload,
                language=language,
                fallback=self._pretty_name(raw_move_name),
            )
            move_type = move_payload.get("type", {}).get("name", "")
            power = move_payload.get("power")
            pp = move_payload.get("pp")
            accuracy = move_payload.get("accuracy")
            machine_items: List[str] = []
            for mach in move_payload.get("machines", []) or []:
                vg = (mach.get("version_group", {}) or {}).get("name", "")
                if vg != version_group:
                    continue
                mu = (mach.get("machine", {}) or {}).get("url", "")
                if not mu:
                    continue
                item_name = machine_item_by_url.get(mu, "")
                if item_name:
                    machine_items.append(item_name)
            machine_item = machine_items[0] if machine_items else ""

            for det in vg_details:
                method_key = det.get("move_learn_method", {}).get("name", "") or "other"
                level = self._safe_int(det.get("level_learned_at", 0), 0)
                method_label = self.MOVE_METHOD_LABELS.get(method_key, self._pretty_name(method_key))
                learn_bucket = "other"
                if method_key == "level-up":
                    learn_bucket = "level"
                    method_level = f"Lv. {level}"
                elif method_key == "egg":
                    learn_bucket = "egg"
                    method_level = "Egg"
                elif method_key == "machine":
                    is_hm = machine_item.lower().startswith("hm")
                    learn_bucket = "hm" if is_hm else "tm"
                    method_label = "HM" if is_hm else "TM"
                    method_level = method_label
                elif method_key == "tutor":
                    learn_bucket = "tutor"
                    method_level = "Tutor"
                else:
                    method_level = method_label
                row_key = (
                    method_key,
                    level,
                    move_name,
                    move_type,
                    power if power is not None else -1,
                    pp if pp is not None else -1,
                    accuracy if accuracy is not None else -1,
                )
                if row_key in seen:
                    continue
                seen.add(row_key)
                rows.append(
                    {
                        "method_key": method_key,
                        "method_label": method_label,
                        "method_level": method_level,
                        "level": level,
                        "name": move_name,
                        "type": self._pretty_name(move_type) if move_type else "—",
                        "raw_type": (move_type or "").lower(),
                        "type_icon_key": (move_type or "").lower(),
                        "power": power if power is not None else "—",
                        "pp": pp if pp is not None else "—",
                        "accuracy": accuracy if accuracy is not None else "—",
                        "learn_bucket": learn_bucket,
                        "version": version_group,
                        "machine_item": machine_item,
                    }
                )
        order = {"level": 0, "egg": 1, "tm": 2, "hm": 3, "tutor": 4, "other": 9}
        rows.sort(key=lambda r: (order.get(r.get("learn_bucket", "other"), 9), r.get("level", 0), r.get("name", "")))
        return rows

    def _region_from_version_name(self, version_name: str) -> str:
        if not version_name:
            return "—"
        return self.VERSION_REGION_HINT.get(version_name, "—")

    def _get_region_for_location_area(self, location_area_url: str, version_name: str = "") -> str:
        if not location_area_url:
            return self._region_from_version_name(version_name)
        if location_area_url in self._location_cache:
            cached = self._location_cache[location_area_url]
            if cached == "—":
                return self._region_from_version_name(version_name)
            return cached
        region_label = "—"
        try:
            area_payload = self._fetch_json_url(location_area_url)
            location_url = area_payload.get("location", {}).get("url", "")
            if location_url:
                location_payload = self._fetch_json_url(location_url)
                region_name = location_payload.get("region", {}).get("name", "")
                region_label = self._pretty_name(region_name) if region_name else "—"
        except Exception as exc:
            print(f"[SpeciesInfoService] location region failed for {location_area_url}: {exc}")
        self._location_cache[location_area_url] = region_label
        if region_label == "—":
            return self._region_from_version_name(version_name)
        return region_label

    def _build_encounter_rows(self, payload: List[dict], versions_filter: Optional[set], fallback_flag: bool) -> List[dict]:
        rows: List[dict] = []
        seen = set()
        for area in payload or []:
            area_name = self._pretty_name(area.get("location_area", {}).get("name", ""))
            area_url = area.get("location_area", {}).get("url", "")
            for vd in area.get("version_details", []) or []:
                version_name = vd.get("version", {}).get("name", "")
                if versions_filter is not None and version_name not in versions_filter:
                    continue
                region_name = self._get_region_for_location_area(area_url, version_name=version_name)
                max_chance = self._safe_int(vd.get("max_chance", 0), 0)
                for enc in vd.get("encounter_details", []) or []:
                    method = self._pretty_name(enc.get("method", {}).get("name", ""))
                    min_lvl = self._safe_int(enc.get("min_level", 0), 0)
                    max_lvl = self._safe_int(enc.get("max_level", 0), 0)
                    levels = f"{min_lvl}" if min_lvl == max_lvl else f"{min_lvl}-{max_lvl}"
                    chance = self._safe_int(enc.get("chance", max_chance), max_chance)
                    row_key = (method, region_name, self._pretty_name(version_name), area_name, levels, chance)
                    if row_key in seen:
                        continue
                    seen.add(row_key)
                    rows.append(
                        {
                            "method": method or "—",
                            "region": region_name or "—",
                            "version": self._pretty_name(version_name) if version_name else "—",
                            "location": area_name or "—",
                            "levels": levels,
                            "chance": f"{chance}%",
                            "is_fallback": fallback_flag,
                        }
                    )
        rows.sort(key=lambda x: (x.get("region", ""), x.get("version", ""), x.get("location", ""), x.get("method", "")))
        return rows

    def _get_encounters(self, species_id: int, version_group: str) -> List[dict]:
        key = (species_id, version_group)
        if key in self._encounter_cache:
            return self._encounter_cache[key]
        versions = self._versions_for_group(version_group)
        try:
            r = requests.get(POKEAPI_POKEMON_ENCOUNTERS.format(id=species_id), timeout=20)
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:
            print(f"[SpeciesInfoService] encounters failed for #{species_id}: {exc}")
            self._encounter_cache[key] = []
            return []
        rows = self._build_encounter_rows(payload, versions_filter=versions, fallback_flag=False)
        if not rows:
            rows = self._build_encounter_rows(payload, versions_filter=None, fallback_flag=True)
        self._encounter_cache[key] = rows
        return rows

    def _format_evolution_trigger(self, detail: dict, language: str = "en") -> str:
        if not detail:
            return "—"
        lang = (language or "en").strip().lower()
        evo_i18n = {
            "es": {
                "lvl": "Nv. {n}",
                "use": "Usar {v}",
                "holding": "Sosteniendo {v}",
                "happiness": "Felicidad {n}+",
                "know": "Con {v}",
                "at": "En {v}",
                "trade": "Intercambio",
                "shed": "Espacio + Pokeball",
            },
            "en": {
                "lvl": "Lv. {n}",
                "use": "Use {v}",
                "holding": "Holding {v}",
                "happiness": "Happiness {n}+",
                "know": "Knows {v}",
                "at": "At {v}",
                "trade": "Trade",
                "shed": "Space + Pokeball",
            },
            "zh": {
                "lvl": "Lv. {n}",
                "use": "使用 {v}",
                "holding": "携带 {v}",
                "happiness": "亲密度 {n}+",
                "know": "已学会 {v}",
                "at": "在 {v}",
                "trade": "通信交换",
                "shed": "空位 + 精灵球",
            },
        }
        tr = evo_i18n.get(lang, evo_i18n["en"])
        # PokeAPI often returns null in nested fields (item, held_item, etc.).
        # Always normalize to dict before .get("name").
        min_level = detail.get("min_level")
        if min_level:
            return tr["lvl"].format(n=min_level)
        item = (detail.get("item") or {}).get("name")
        if item:
            return tr["use"].format(v=self._pretty_name(item))
        held_item = (detail.get("held_item") or {}).get("name")
        if held_item:
            return tr["holding"].format(v=self._pretty_name(held_item))
        min_happiness = detail.get("min_happiness")
        if min_happiness:
            return tr["happiness"].format(n=min_happiness)
        known_move = (detail.get("known_move") or {}).get("name")
        if known_move:
            return tr["know"].format(v=self._pretty_name(known_move))
        location = (detail.get("location") or {}).get("name")
        if location:
            return tr["at"].format(v=self._pretty_name(location))
        time_of_day = detail.get("time_of_day", "")
        if time_of_day:
            return self._pretty_name(time_of_day)
        trigger = (detail.get("trigger") or {}).get("name", "")
        if trigger == "trade":
            return tr["trade"]
        if trigger == "shed":
            return tr["shed"]
        if trigger:
            return self._pretty_name(trigger)
        return "—"

    def _get_evolution_paths(self, species_id: int, species_payload: dict, language: str = "en") -> List[List[dict]]:
        cache_key = (species_id, (language or "en").strip().lower())
        if cache_key in self._evolution_cache:
            return self._evolution_cache[cache_key]
        chain_url = (species_payload.get("evolution_chain") or {}).get("url", "")
        if not chain_url:
            base = [[{"species_id": species_id, "name": self._pretty_name(species_payload.get("name", "")), "trigger_text": ""}]]
            self._evolution_cache[cache_key] = base
            return base
        try:
            chain_payload = self._fetch_json_url(chain_url)
        except Exception as exc:
            print(f"[SpeciesInfoService] evolution chain failed for #{species_id}: {exc}")
            base = [[{"species_id": species_id, "name": self._pretty_name(species_payload.get("name", "")), "trigger_text": ""}]]
            self._evolution_cache[cache_key] = base
            return base

        paths: List[List[dict]] = []

        def walk(node: dict, incoming_trigger: str, current: List[dict]) -> None:
            species_obj = node.get("species", {}) or {}
            sid = self._extract_id_from_url(species_obj.get("url", "")) or 0
            step = {
                "species_id": sid,
                "name": self._pretty_name(species_obj.get("name", "")),
                "trigger_text": incoming_trigger,
            }
            next_current = current + [step]
            evolves = node.get("evolves_to", []) or []
            if not evolves:
                paths.append(next_current)
                return
            for child in evolves:
                details = child.get("evolution_details", []) or [{}]
                trigger_texts = [self._format_evolution_trigger(d, language=language) for d in details if d]
                trigger = " / ".join([t for t in trigger_texts if t and t != "—"]) or "Evolves"
                walk(child, trigger, next_current)

        root = chain_payload.get("chain", {}) or {}
        walk(root, "", [])

        if not paths:
            paths = [[{"species_id": species_id, "name": self._pretty_name(species_payload.get("name", "")), "trigger_text": ""}]]
        self._evolution_cache[cache_key] = paths
        return paths

    def get_pokemon_details(self, species_id: int, version_group: str = "black-white", language: str = "en") -> dict:
        lang = (language or "en").strip().lower()
        key = (species_id, version_group, lang)
        if key in self._detail_cache:
            return self._detail_cache[key]

        species = self._get_species_payload(species_id)
        pokemon = self._get_pokemon_payload(species_id)
        stats = []
        for s in sorted(pokemon.get("stats", []), key=lambda x: self.STAT_ORDER.get(x.get("stat", {}).get("name", ""), 99)):
            raw = s.get("stat", {}).get("name", "")
            stats.append(
                {
                    "raw": raw,
                    "name": self.STAT_NAME_MAP.get(raw, raw.upper().replace("-", " ")),
                    "value": self._safe_int(s.get("base_stat", 0), 0),
                    "effort": self._safe_int(s.get("effort", 0), 0),
                }
            )

        abilities = []
        for a in sorted(pokemon.get("abilities", []), key=lambda x: x.get("slot", 99)):
            abilities.append(
                {
                    "name": self._pretty_name(a.get("ability", {}).get("name", "")),
                    "hidden": bool(a.get("is_hidden", False)),
                }
            )

        moves = self._build_moves(pokemon, version_group, language=lang)
        level_moves = sorted({(m["level"], m["name"]) for m in moves if m["method_key"] == "level-up"}, key=lambda x: (x[0], x[1]))
        egg_moves = sorted({m["name"] for m in moves if m["method_key"] == "egg"})
        machine_moves = sorted({m["name"] for m in moves if m["method_key"] == "machine"})
        encounters = self._get_encounters(species_id, version_group)
        evolution_chain = self._get_evolution_paths(species_id, species, language=lang)
        sites_fallback_used = any(bool(x.get("is_fallback")) for x in encounters)

        hidden_ability = "—"
        regular_abilities: List[str] = []
        for a in abilities:
            if a.get("hidden"):
                hidden_ability = a.get("name", "—")
            else:
                regular_abilities.append(a.get("name", "—"))
        summary = {
            "name": self._pretty_name(species.get("name", "")),
            "id": species_id,
            "types": self.get_types(species_id),
            "egg_groups": self.get_egg_groups(species_id),
            "flavor_text": self._get_flavor_text(species, language=lang),
            "height_m": (self._safe_int(pokemon.get("height", 0), 0) / 10.0),
            "weight_kg": (self._safe_int(pokemon.get("weight", 0), 0) / 10.0),
            "capture_rate": self._safe_int(species.get("capture_rate", 0), 0),
            "ev_yield": self._build_ev_yield(stats),
            "abilities": ", ".join(regular_abilities) if regular_abilities else "—",
            "hidden_ability": hidden_ability,
            "info_version_group": version_group,
            "sites_fallback_used": sites_fallback_used,
        }

        out = {
            # Compat con la versión anterior
            "id": species_id,
            "name": summary["name"],
            "types": summary["types"],
            "stats": stats,
            "abilities": abilities,
            "moves_level": level_moves,
            "moves_egg": egg_moves,
            "moves_machine": machine_moves,
            "egg_groups": summary["egg_groups"],
            # Nuevo payload enriquecido
            "summary": summary,
            "moves": moves,
            "encounters": encounters,
            "evolution_chain": evolution_chain,
        }
        self._detail_cache[key] = out
        return out

    @staticmethod
    def classify_gender_cost(gender_rate: int) -> Tuple[str, Dict[str, int]]:
        """
        Devuelve (label_ratio, costos_por_sexo)
        """
        if gender_rate == -1:
            return ("Sin género", {"M": 0, "F": 0})

        female = gender_rate / 8.0
        male = 1.0 - female

        if abs(female - 0.5) < 1e-9:
            return ("50/50", GENDER_COST_50_50)
        if abs(female - 0.25) < 1e-9:
            return ("75/25", GENDER_COST_75_25)  # 75% M, 25% F
        if abs(female - 0.125) < 1e-9:
            return ("87.5/12.5", GENDER_COST_87_5_12_5)

        # Otros ratios: tratar como 50/50 por defecto
        return (f"{male*100:.1f}/{female*100:.1f}", GENDER_COST_50_50)


# =========================
# Sprite service (raw by ID + cache)
# =========================
class SpriteService:
    def __init__(
        self,
        cache_dir: str = SPRITE_CACHE_DIR,
        default_path: str = DEFAULT_SPRITE_PATH,
        runtime_default_path: str = RUNTIME_DEFAULT_SPRITE_PATH,
    ):
        self.cache_dir = cache_dir
        self.default_path = default_path
        self.runtime_default_path = runtime_default_path

    def get_default_path(self) -> str:
        if self.runtime_default_path and os.path.exists(self.runtime_default_path):
            return self.runtime_default_path
        return self.default_path

    def get_sprite_path(self, pokedex_id: int) -> str:
        cached = os.path.join(self.cache_dir, f"{pokedex_id}.png")
        if os.path.exists(cached):
            return cached

        url = RAW_SPRITE_URL.format(id=pokedex_id)
        try:
            r = requests.get(url, timeout=20)
            r.raise_for_status()
            os.makedirs(self.cache_dir, exist_ok=True)
            with open(cached, "wb") as f:
                f.write(r.content)
            return cached
        except Exception as exc:
            print(f"[SpriteService] Failed to download sprite {pokedex_id} from {url}: {exc}")
            return self.get_default_path()


class TypeIconService:
    def __init__(
        self,
        assets_dir: str = TYPE_ICON_DIR,
        cache_dir: str = TYPE_ICON_CACHE_DIR,
        runtime_assets_dir: str = RUNTIME_TYPE_ICON_DIR,
    ):
        self.assets_dir = assets_dir
        self.cache_dir = cache_dir
        self.runtime_assets_dir = runtime_assets_dir
        os.makedirs(self.assets_dir, exist_ok=True)
        os.makedirs(self.cache_dir, exist_ok=True)
        self._photo_cache: Dict[Tuple[str, int, int], ImageTk.PhotoImage] = {}

    @staticmethod
    def _normalize(type_key: str) -> str:
        return (type_key or "").strip().lower().replace(" ", "-")

    def _asset_path(self, type_key: str) -> Optional[str]:
        t = self._normalize(type_key)
        if not t:
            return None
        for ext in ("png", "webp", "jpg", "jpeg"):
            for base in (self.assets_dir, self.runtime_assets_dir):
                if not base:
                    continue
                p = os.path.join(base, f"{t}.{ext}")
                if os.path.exists(p):
                    return p
        return None

    def _cache_path(self, type_key: str, size: Tuple[int, int]) -> str:
        t = self._normalize(type_key) or "unknown"
        w, h = size
        return os.path.join(self.cache_dir, f"{t}_{w}x{h}.png")

    def _generate_badge(self, type_key: str, size: Tuple[int, int], out_path: str) -> str:
        w, h = size
        bg = TYPE_COLORS.get(self._normalize(type_key), "#6B7280")
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        dr = ImageDraw.Draw(img)
        radius = max(3, min(7, h // 3))
        dr.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=bg, outline=(30, 30, 30, 220), width=1)
        txt = (type_key or "?").strip().upper()
        txt = txt[:3] if len(txt) > 3 else txt
        try:
            font = ImageFont.load_default()
            tw = dr.textlength(txt, font=font)
            th = 8
            dr.text(((w - tw) / 2, (h - th) / 2), txt, fill=(255, 255, 255, 245), font=font)
        except Exception:
            pass
        try:
            img.save(out_path)
        except Exception as exc:
            print(f"[TypeIconService] failed saving generated icon {out_path}: {exc}")
        return out_path

    def _resolve_icon_path(self, type_key: str, size: Tuple[int, int]) -> Optional[str]:
        if not type_key:
            return None
        local = self._asset_path(type_key)
        if local:
            return local
        cpath = self._cache_path(type_key, size)
        if os.path.exists(cpath):
            return cpath
        return self._generate_badge(type_key, size, cpath)

    def get_icon(self, type_key: str, size: Tuple[int, int] = (42, 18)) -> Optional[ImageTk.PhotoImage]:
        t = self._normalize(type_key)
        if not t:
            return None
        w, h = size
        cache_key = (t, int(w), int(h))
        if cache_key in self._photo_cache:
            return self._photo_cache[cache_key]
        path = self._resolve_icon_path(t, (w, h))
        if not path:
            return None
        try:
            img = Image.open(path).convert("RGBA").resize((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._photo_cache[cache_key] = photo
            return photo
        except Exception as exc:
            print(f"[TypeIconService] failed loading icon {path}: {exc}")
            return None


class BraceSpriteService:
    ITEM_BY_STAT = {
        "HP": "power-weight",
        "Atk": "power-bracer",
        "Def": "power-belt",
        "SpA": "power-lens",
        "SpD": "power-band",
        "Spe": "power-anklet",
    }

    def __init__(self, braces_dir: str = BRACES_DIR, runtime_braces_dir: str = RUNTIME_BRACES_DIR):
        self.braces_dir = braces_dir
        self.runtime_braces_dir = runtime_braces_dir

    def get_everstone_path(self) -> Optional[str]:
        local_path = os.path.join(self.braces_dir, "everstone.png")
        if os.path.exists(local_path):
            return local_path
        runtime_path = os.path.join(self.runtime_braces_dir, "everstone.png") if self.runtime_braces_dir else ""
        if runtime_path and os.path.exists(runtime_path):
            return runtime_path
        try:
            r = requests.get(POKEAPI_ITEM_BY_NAME.format(name="everstone"), timeout=20)
            r.raise_for_status()
            sprite_url = r.json().get("sprites", {}).get("default")
            if not sprite_url:
                return None
            img_r = requests.get(sprite_url, timeout=20)
            img_r.raise_for_status()
            os.makedirs(self.braces_dir, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(img_r.content)
            return local_path
        except Exception as exc:
            print(f"[BraceSpriteService] Failed to fetch everstone: {exc}")
            return None

    def get_icon_path(self, stat: str) -> Optional[str]:
        item_name = self.ITEM_BY_STAT.get(stat)
        if not item_name:
            return None
        local_path = os.path.join(self.braces_dir, f"{stat.lower()}.png")
        if os.path.exists(local_path):
            return local_path
        runtime_path = os.path.join(self.runtime_braces_dir, f"{stat.lower()}.png") if self.runtime_braces_dir else ""
        if runtime_path and os.path.exists(runtime_path):
            return runtime_path
        try:
            r = requests.get(POKEAPI_ITEM_BY_NAME.format(name=item_name), timeout=20)
            r.raise_for_status()
            sprite_url = r.json().get("sprites", {}).get("default")
            if not sprite_url:
                return None
            img_r = requests.get(sprite_url, timeout=20)
            img_r.raise_for_status()
            os.makedirs(self.braces_dir, exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(img_r.content)
            return local_path
        except Exception as exc:
            print(f"[BraceSpriteService] Failed to fetch {stat}/{item_name}: {exc}")
            return None


# =========================
# Breeding engine (capas + braces + género)
# =========================
class BreedingEngine:
    """
    Capas para k IVs:
      level L tiene 2^(k-L) nodos, donde L=1..k
      (1x31 = base, kx31 = final)

    Cruces = 2^(k-1) - 1
    Braces = sum_{i=2..k} i * 2^(k-i)
    """
    @staticmethod
    def _node_sort_key(node: BreedingNode) -> Tuple[int, ...]:
        stat_order = {s: i for i, s in enumerate(STATS)}
        return tuple(stat_order.get(s, 999) for s in node.ivs)

    def _build_pure_layers(self, selected_stats: List[str]) -> List[List[BreedingNode]]:
        k = len(selected_stats)
        if k <= 0:
            return []
        top = [BreedingNode(ivs=tuple(selected_stats), is_nature_branch=False, branch_role="primary")]
        layers_desc: List[List[BreedingNode]] = [top]  # kx31, (k-1)x31, ... 1x31

        curr = top
        for _ in range(k, 1, -1):
            parents: List[BreedingNode] = []
            for child in curr:
                ivs = list(child.ivs)
                left = tuple(ivs[:-1])
                right = tuple(ivs[1:])
                parents.append(BreedingNode(ivs=left, is_nature_branch=False, branch_role="primary"))
                parents.append(BreedingNode(ivs=right, is_nature_branch=False, branch_role="primary"))
            layers_desc.append(parents)
            curr = parents

        # Convert to ascending layers: 1x31 .. kx31
        return list(reversed(layers_desc))

    def _insert_subtree_into_layers(
        self,
        layers: List[List[BreedingNode]],
        root_ivs: Tuple[str, ...],
        tree_id: int,
        branch_role: str,
    ) -> Tuple[int, int]:
        def rec(ivs: Tuple[str, ...], slot: int) -> Tuple[int, int]:
            layer_idx = len(ivs) - 1
            node = BreedingNode(
                ivs=ivs,
                gender="M" if slot % 2 == 0 else "H",
                is_nature_branch=False,
                branch_role=branch_role,
                tree_id=tree_id,
                slot=slot,
            )
            idx = len(layers[layer_idx])
            layers[layer_idx].append(node)
            key = (layer_idx, idx)
            if len(ivs) <= 1:
                return key
            rec(tuple(ivs[:-1]), slot * 2)
            rec(tuple(ivs[1:]), slot * 2 + 1)
            return key

        return rec(root_ivs, 0)

    def _build_node_layers(self, selected_stats: List[str], nature_selected: bool) -> List[List[BreedingNode]]:
        k = len(selected_stats)
        if k <= 0:
            return []

        if not nature_selected:
            pure_layers = self._build_pure_layers(selected_stats)
            for layer in pure_layers:
                for i, n in enumerate(layer):
                    n.gender = "M" if i % 2 == 0 else "H"
                    n.branch_role = "primary"
                    n.tree_id = 1
                    n.slot = i
            return pure_layers

        # Nature mode:
        # - Keep a full primary tree.
        # - Keep separate donor trees for intermediate NATU rounds (2..k-1).
        # - Final NATU round uses primary final (kx31) as donor.
        layers: List[List[BreedingNode]] = [[] for _ in range(k)]

        # Nature spine (one node per level).
        for l in range(1, k + 1):
            layers[l - 1].append(
                BreedingNode(
                    ivs=tuple(selected_stats[:l]),
                    gender="M",
                    has_nature=True,
                    is_nature_branch=True,
                    branch_role="nature",
                    tree_id=-1,
                    slot=0,
                )
            )

        # Primary pure tree (tree_id=1).
        primary_root = self._insert_subtree_into_layers(
            layers=layers,
            root_ivs=tuple(selected_stats),
            tree_id=1,
            branch_role="primary",
        )
        layers[primary_root[0]][primary_root[1]].is_fusion_donor = True
        layers[primary_root[0]][primary_root[1]].fusion_level = k

        # Separate intermediate donor trees (tree_id >= 2).
        for level in range(2, k):
            donor_root = self._insert_subtree_into_layers(
                layers=layers,
                root_ivs=tuple(selected_stats[:level]),
                tree_id=level,
                branch_role="nature_donor",
            )
            layers[donor_root[0]][donor_root[1]].is_fusion_donor = True
            layers[donor_root[0]][donor_root[1]].fusion_level = level

        return layers

    def _connect_layers_and_assign_items(
        self, layers: List[List[BreedingNode]], nature_selected: bool
    ) -> Tuple[List[Tuple[Tuple[int, int], Tuple[int, int]]], List[Tuple[str, int]], int]:
        connections: List[Tuple[Tuple[int, int], Tuple[int, int]]] = []
        braces_by_level_count: Dict[int, int] = {}
        everstone_uses = 0

        if not nature_selected:
            for layer_idx in range(len(layers) - 1):
                parents = layers[layer_idx]
                children = layers[layer_idx + 1]
                for child_idx in range(len(children)):
                    ia = 2 * child_idx
                    ib = ia + 1
                    if ib >= len(parents):
                        continue
                    pa = parents[ia]
                    pb = parents[ib]
                    common = set(pa.ivs).intersection(pb.ivs)

                    for pidx, p in ((ia, pa), (ib, pb)):
                        unique = sorted([s for s in p.ivs if s not in common], key=lambda s: STATS.index(s))
                        p.item = unique[0] if unique else p.ivs[-1]
                        braces_by_level_count[layer_idx] = braces_by_level_count.get(layer_idx, 0) + 1
                        connections.append(((layer_idx, pidx), (layer_idx + 1, child_idx)))
            braces_by_level: List[Tuple[str, int]] = []
            for layer_idx in range(len(layers) - 1):
                label = f"{layer_idx + 1}x31"
                braces_by_level.append((label, braces_by_level_count.get(layer_idx, 0)))
            return connections, braces_by_level, everstone_uses

        # Nature mode:
        # 1) Connect all pure trees independently (primary + donor trees).
        for layer_idx in range(len(layers) - 1):
            child_lookup: Dict[Tuple[int, int], int] = {}
            for cidx, cnode in enumerate(layers[layer_idx + 1]):
                if cnode.is_nature_branch or cnode.tree_id <= 0:
                    continue
                child_lookup[(cnode.tree_id, cnode.slot)] = cidx

            sibling_groups: Dict[Tuple[int, int], List[Tuple[int, BreedingNode]]] = {}
            for pidx, pnode in enumerate(layers[layer_idx]):
                if pnode.is_nature_branch or pnode.tree_id <= 0:
                    continue
                sibling_groups.setdefault((pnode.tree_id, pnode.slot // 2), []).append((pidx, pnode))

            for (tree_id, parent_slot), plist in sibling_groups.items():
                child_idx = child_lookup.get((tree_id, parent_slot))
                if child_idx is None or len(plist) < 2:
                    continue
                plist.sort(key=lambda x: x[1].slot)
                pa_idx, pa = plist[0]
                pb_idx, pb = plist[1]
                common = set(pa.ivs).intersection(pb.ivs)
                for pidx, p in ((pa_idx, pa), (pb_idx, pb)):
                    unique = sorted([s for s in p.ivs if s not in common], key=lambda s: STATS.index(s))
                    p.item = unique[0] if unique else (p.ivs[-1] if p.ivs else None)
                    p.gender = "M" if p.slot % 2 == 0 else "H"
                    braces_by_level_count[layer_idx] = braces_by_level_count.get(layer_idx, 0) + 1
                    connections.append(((layer_idx, pidx), (layer_idx + 1, child_idx)))

        # 2) Nature spine + fusion donor per level.
        for level in range(2, len(layers) + 1):
            parent_layer_idx = level - 2
            child_layer_idx = level - 1

            parent_nature_idx = next(
                (i for i, n in enumerate(layers[parent_layer_idx]) if n.is_nature_branch),
                None,
            )
            child_nature_idx = next(
                (i for i, n in enumerate(layers[child_layer_idx]) if n.is_nature_branch),
                None,
            )
            if parent_nature_idx is None or child_nature_idx is None:
                continue

            nature_parent = layers[parent_layer_idx][parent_nature_idx]
            nature_child = layers[child_layer_idx][child_nature_idx]
            nature_parent.item = "EVERSTONE"
            nature_parent.gender = "M"
            everstone_uses += 1
            connections.append(((parent_layer_idx, parent_nature_idx), (child_layer_idx, child_nature_idx)))

            donor_idx = next(
                (
                    i
                    for i, n in enumerate(layers[child_layer_idx])
                    if n.is_fusion_donor and n.fusion_level == level
                ),
                None,
            )
            if donor_idx is not None:
                donor = layers[child_layer_idx][donor_idx]
                donor.gender = "H"
                missing_stats = [s for s in nature_child.ivs if s not in nature_parent.ivs]
                need = missing_stats[0] if missing_stats else (nature_child.ivs[-1] if nature_child.ivs else None)
                if need:
                    donor.item = need
                    braces_by_level_count[child_layer_idx] = braces_by_level_count.get(child_layer_idx, 0) + 1
                # donor merges in same layer into NATU child.
                connections.append(((child_layer_idx, donor_idx), (child_layer_idx, child_nature_idx)))
            nature_child.has_nature = True

        braces_by_level: List[Tuple[str, int]] = []
        for layer_idx in range(len(layers)):
            label = f"{layer_idx + 1}x31"
            braces_by_level.append((label, braces_by_level_count.get(layer_idx, 0)))
        return connections, braces_by_level, everstone_uses

    def build_plan(self, req: BreedingRequest, gender_costs: Dict[str, int], ratio_label: str) -> BreedingPlan:
        k = sum(1 for v in req.desired_31.values() if v)
        selected_stats = [s for s in STATS if req.desired_31.get(s, False)]
        nature_selected = bool(req.desired_nature and req.desired_nature != NATURE_NONE)

        if k <= 0:
            return BreedingPlan(
                k=0, parents_needed=0, breeds_needed=0, braces_needed=0, braces_cost=0,
                extra_breeds_nature=0, everstone_cost=0, nature_selected=nature_selected, desired_nature=req.desired_nature,
                total_cost=0,
                levels=[("Sin IVs", 1)],
                level_nodes=[("Sin IVs", ["-"])],
                node_layers=[],
                connections=[],
                everstone_uses=0,
                notes=["Selecciona al menos 1 IV a 31."]
            )

        node_layers = self._build_node_layers(selected_stats, nature_selected)
        connections, braces_by_level, everstone_uses = self._connect_layers_and_assign_items(node_layers, nature_selected)
        levels: List[Tuple[str, int]] = [(f"{i+1}x31", len(layer)) for i, layer in enumerate(node_layers)]
        level_nodes: List[Tuple[str, List[str]]] = [
            (f"{i+1}x31", ["+".join(n.ivs) for n in layer]) for i, layer in enumerate(node_layers)
        ]

        # Track only nodes that are truly part of the graph.
        active_by_layer: Dict[int, set] = {i: set() for i in range(len(node_layers))}
        for (pl, pi), (cl, ci) in connections:
            active_by_layer[pl].add(pi)
            active_by_layer[cl].add(ci)
        if node_layers and not active_by_layer[0]:
            active_by_layer[0].add(0)
        source_nodes = {(pl, pi) for (pl, pi), _ in connections}

        # Plan de género por capa (base/intermedia/final)
        gender_layers: List[GenderPlanLayer] = []
        selections = {"M": 0, "F": 0}

        total_braces = 0
        total_everstones = 0
        total_gender_fees = 0
        total_balls = 0
        braces_by_level_count: Dict[str, int] = {}

        for layer_idx, layer in enumerate(node_layers):
            active_indices = sorted(active_by_layer.get(layer_idx, set()))
            if not active_indices:
                continue

            is_base_layer = layer_idx == 0
            is_final_layer = layer_idx == len(node_layers) - 1
            need_m = 0
            need_f = 0

            for node_idx in active_indices:
                node = layer[node_idx]
                node.is_base = is_base_layer
                node.cost_ball = 0 if is_base_layer else POKEBALL_COST
                node.cost_gender = 0
                node_is_source = (layer_idx, node_idx) in source_nodes

                # 1) Item cost
                if node_is_source:
                    if node.item == "EVERSTONE":
                        total_everstones += 1
                    elif node.item in STATS:
                        total_braces += 1
                        lvl_label = f"{layer_idx + 1}x31"
                        braces_by_level_count[lvl_label] = braces_by_level_count.get(lvl_label, 0) + 1

                # 2) Ball cost (every egg, non-base)
                if node.cost_ball > 0:
                    total_balls += 1

                # 3) Gender selection fee for breeding-capable eggs only
                if not is_base_layer and node_is_source:
                    node.cost_gender = gender_costs.get(node.gender, GENDER_SELECTION_COST)
                    total_gender_fees += node.cost_gender
                    if node.gender == "M":
                        need_m += 1
                        selections["M"] += 1
                    else:
                        need_f += 1
                        selections["F"] += 1
                elif is_base_layer:
                    if node.gender == "M":
                        need_m += 1
                    else:
                        need_f += 1

            label = f"{layer_idx + 1}x31"
            if is_base_layer:
                gender_layers.append(GenderPlanLayer(f"{label} (base)", len(active_indices), need_m, need_f, selectable=False))
            elif is_final_layer:
                gender_layers.append(GenderPlanLayer(f"{label} (final)", len(active_indices), 0, 0, selectable=False))
            else:
                gender_layers.append(GenderPlanLayer(f"{label} (huevos)", len(active_indices), need_m, need_f, selectable=True))

        braces_by_level = [(f"{i+1}x31", braces_by_level_count.get(f"{i+1}x31", 0)) for i in range(len(node_layers))]
        braces_needed = total_braces
        braces_cost = total_braces * BRACE_COST
        everstone_uses = total_everstones
        everstone_cost = total_everstones * EVERSTONE_COST
        gender_cost_total = total_gender_fees
        balls_used = total_balls
        balls_cost = total_balls * POKEBALL_COST
        parents_needed = len(active_by_layer.get(0, set()))
        breeds_needed = total_balls
        extra_breed_nature = 0
        total_breeds = breeds_needed
        total_cost = braces_cost + gender_cost_total + everstone_cost + balls_cost + (total_breeds * BREED_SERVICE_COST)

        notes = [
            "Cada cruce consume a ambos padres y solo queda el huevo.",
            "Braces: 2 por cruce; si un padre lleva naturaleza, usa Everstone en lugar de brace.",
            f"Género (según species): ratio {ratio_label}.",
            "Base (1x31) NO puede seleccionar género con NPC: se requieren M/H necesarios.",
            "En capas intermedias se selecciona el género del huevo para garantizar parejas.",
            f"Insumos: {balls_used} Pokéballs usadas."
        ]
        if nature_selected:
            notes.append(f"Naturaleza fijada desde base y propagada con Piedra Eterna (+${EVERSTONE_COST:,} por uso).")

        return BreedingPlan(
            k=k,
            parents_needed=parents_needed,
            breeds_needed=breeds_needed,
            braces_needed=braces_needed,
            braces_cost=braces_cost,
            braces_by_level=braces_by_level,
            extra_breeds_nature=extra_breed_nature,
            everstone_cost=everstone_cost,
            nature_selected=nature_selected,
            desired_nature=req.desired_nature,
            gender_layers=gender_layers,
            gender_selections=selections,
            gender_cost_total=gender_cost_total,
            balls_used=balls_used,
            balls_cost=balls_cost,
            total_cost=total_cost,
            levels=levels,
            level_nodes=level_nodes,
            node_layers=node_layers,
            connections=connections,
            everstone_uses=everstone_uses,
            notes=notes
        )


# =========================
# UI Theme
# =========================
class DarkTheme:
    BG = "#111318"
    PANEL = "#151A21"
    FG = "#E6E6E6"
    MUTED = "#9AA4B2"
    BORDER = "#2A3340"


# =========================
# App
# =========================
BaseTkApp = ctk.CTk if HAS_CTK else tk.Tk


class App(BaseTkApp):
    def __init__(self):
        super().__init__()
        self._use_ctk = bool(HAS_CTK)
        if not self._use_ctk:
            LOGGER.warning("customtkinter not installed. Falling back to Tk widgets.")
        self.i18n = I18nManager()
        self.ui_cfg = self.i18n.load_ui_config()
        self._lang = self.ui_cfg.language if self.ui_cfg.language in I18nManager.SUPPORTED else "en"
        self._ui_font_family = self._resolve_ui_font_family(self._lang)
        self.title(f"ChansEgg v{APP_VERSION}")
        # Set an initial geometry and a minimum size
        self.geometry("1150x680")
        # Set a minimum size to avoid UI breakage on small windows
        self.wm_minsize(920, 600)
        self.theme_manager = ThemeManager()
        self.theme_cfg = self.theme_manager.load()
        self.theme = self.theme_manager.build_theme(self.theme_cfg)
        if self._use_ctk:
            ctk.set_appearance_mode("Dark" if self.theme_cfg.mode == "dark" else "Light")
            ctk.set_default_color_theme("blue")
            self.configure(fg_color=self.theme["bg"])
        else:
            self.configure(bg=self.theme["bg"])

        self.repo = Repo()
        self.species_info = SpeciesInfoService()
        self.sprites = SpriteService()
        self.type_icons = TypeIconService()
        self.brace_sprites = BraceSpriteService()
        self.engine = BreedingEngine()
        self.inventory_store = InventoryStore(INVENTORY_JSON_PATH, INVENTORY_SETTINGS_PATH)
        self.inventory_matcher = InventoryMatcher()
        self.inventory_items: List[InventoryItem] = self.inventory_store.load_items()
        self.inventory_settings: InventorySettings = self.inventory_store.load_settings()
        self._last_inventory_report = None

        self.items: List[PokemonEntry] = []
        self.filtered: List[PokemonEntry] = []

        self.search_var = tk.StringVar()
        self.nature_var = tk.StringVar(value=NATURE_NONE)
        self.theme_palette_var = tk.StringVar(value=self.theme_cfg.palette)
        self.theme_mode_var = tk.StringVar(value=self.theme_cfg.mode)
        self.language_var = tk.StringVar(value=self._lang.upper())
        self.keep_nature = tk.BooleanVar(value=False)  # reserved for future
        self.compatible_var = tk.BooleanVar(value=False)
        self.iv_vars: Dict[str, tk.BooleanVar] = {s: tk.BooleanVar(value=False) for s in STATS}

        self.selected: Optional[PokemonEntry] = None
        self._sprite_img: Optional[ImageTk.PhotoImage] = None
        self._brace_icons: Dict[str, ImageTk.PhotoImage] = {}
        self._everstone_icon: Optional[ImageTk.PhotoImage] = None
        self._name_type_text_var = tk.StringVar(value="—")
        self._egg_groups_var = tk.StringVar(value="")
        self._zoom_scale: float = 1.0
        self._selection_generation_id: int = 0
        self._zoom_min: float = 0.45
        self._zoom_max: float = 2.8
        self._is_panning: bool = False
        self._view_state: Dict[str, float] = {"x_frac": 0.0, "y_frac": 0.0, "zoom": 1.0}
        self._left_visible = True
        self._right_visible = True
        self._iv_buttons: Dict[str, tk.Button] = {}
        self._info_window: Optional[tk.Toplevel] = None
        self._info_species_id: Optional[int] = None
        self._info_header_var = tk.StringVar(value="")
        self._info_status_var = tk.StringVar(value="")
        self._info_active_tab: str = "datos"
        self._info_tab_frames: Dict[str, tk.Frame] = {}
        self._info_tab_buttons: Dict[str, tk.Button] = {}
        self._info_tab_rendered: Dict[str, bool] = {}
        self._info_content_frame: Optional[tk.Frame] = None
        self._info_status_label: Optional[tk.Label] = None
        self._info_move_filter_var = tk.StringVar(value="level")
        self._info_moves_rows: List[dict] = []
        self._info_moves_by_bucket: Dict[str, List[dict]] = {}
        self._info_move_section_trees: Dict[str, ttk.Treeview] = {}
        self._info_sites_tree: Optional[ttk.Treeview] = None
        self._info_details: Optional[dict] = None
        self._info_images: List[ImageTk.PhotoImage] = []
        self._info_loading_label: Optional[tk.Label] = None
        self._last_plan: Optional[BreedingPlan] = None
        self._last_render_meta: Optional[Dict[str, object]] = None
        self._resize_after_id: Optional[str] = None
        self._recompute_after_id: Optional[str] = None
        self._recompute_debounce_ms: int = 180
        self._render_generation_id: int = 0
        self._render_inflight: bool = False
        self._graph_tag = "graph"
        self._status_var = tk.StringVar(value=f"v{APP_VERSION}")
        self._app_icon_img: Optional[ImageTk.PhotoImage] = None
        self._inventory_window = None
        self._inventory_canvas = None
        self._inventory_box_label_var = tk.StringVar(value="Box 1")
        self._inventory_selected_item_id: Optional[str] = None
        self._inventory_box_index: int = 0
        self._inventory_slots_per_box: int = 40
        self._inventory_cols: int = 8
        self._inventory_rows: int = 5
        self._inventory_slot_size: int = 84
        self._inventory_drag: Dict[str, object] = {}
        self._inventory_images: Dict[str, ImageTk.PhotoImage] = {}
        self._inventory_form_vars: Dict[str, object] = {}
        self._inventory_price_vars: Dict[int, tk.StringVar] = {}
        self._inventory_stats_vars: Dict[str, tk.StringVar] = {}

        self._setup_style()
        self._apply_app_icon()
        self._build_layout()
        self._apply_theme(refresh_canvas=False)
        self._apply_language()
        self._show_default_sprite()
        self._load_brace_icons_async()
        self._load_data_async()

    def t(self, key: str, **kwargs) -> str:
        return self.i18n.t(self._lang, key, **kwargs)

    def _localize_type_name(self, type_key: str) -> str:
        key = (type_key or "").strip().lower()
        if not key:
            return "—"
        lang_map = TYPE_NAMES_LOCALIZED.get(self._lang, TYPE_NAMES_LOCALIZED["en"])
        return lang_map.get(key, TYPE_NAMES_LOCALIZED["en"].get(key, key.title()))

    def _resolve_ui_font_family(self, lang: str) -> str:
        if lang == "zh":
            preferred = ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "SimHei", "Segoe UI")
        else:
            preferred = ("Segoe UI", "Roboto", "Arial", "Microsoft YaHei")
        try:
            families = set(tkfont.families(self))
            for fam in preferred:
                if fam in families:
                    return fam
        except Exception:
            pass
        return "Segoe UI"

    def _set_status(self, key_or_text: str, *, is_key: bool = False, **kwargs) -> None:
        text = self.t(key_or_text, **kwargs) if is_key else key_or_text
        self._status_var.set(text)

    def _apply_app_icon(self) -> None:
        ico_candidates = [
            os.path.join(RUNTIME_ASSETS_DIR, "chansegg.ico"),
            os.path.join(ASSETS_DIR, "chansegg.ico"),
        ]
        for ico in ico_candidates:
            if not os.path.exists(ico):
                continue
            try:
                self.iconbitmap(ico)
                return
            except Exception:
                pass

        png_candidates = [
            os.path.join(RUNTIME_ASSETS_DIR, "chansegg.png"),
            os.path.join(ASSETS_DIR, "chansegg.png"),
        ]
        for png in png_candidates:
            if not os.path.exists(png):
                continue
            try:
                img = Image.open(png).convert("RGBA").resize((32, 32), Image.LANCZOS)
                self._app_icon_img = ImageTk.PhotoImage(img)
                self.iconphoto(False, self._app_icon_img)
                return
            except Exception:
                pass

    # ---------- Styling ----------
    def _setup_style(self):
        style = ttk.Style(self)
        base_font = self._ui_font_family
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure(".", background=self.theme["bg"], foreground=self.theme["fg"], fieldbackground=self.theme["panel"], font=(base_font, 10))
        style.configure("Panel.TFrame", background=self.theme["panel"])
        style.configure("Toolbar.TFrame", background=self.theme["panel_alt"])

        style.configure(
            "Header.TLabel",
            background=self.theme["panel"],
            foreground=self.theme["accent"],
            font=(base_font, 14, "bold"),
        )
        style.configure(
            "CostTitle.TLabel",
            background=self.theme["panel"],
            foreground=self.theme["fg"],
            font=(base_font, 14, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background=self.theme["panel"],
            foreground=self.theme["muted"],
            font=(base_font, 9, "italic"),
        )

        style.configure("Toolbar.TButton", padding=(12, 6), font=(base_font, 10, "bold"))
        style.map(
            "Toolbar.TButton",
            background=[("active", self.theme["accent"]), ("pressed", self.theme["border"])],
            foreground=[("active", self.theme["fg"])],
        )

        style.configure("TButton", padding=(10, 5), font=(base_font, 10))
        style.map(
            "TButton",
            background=[("active", self.theme["accent"]), ("pressed", self.theme["border"])],
            foreground=[("active", self.theme["fg"])]
        )

        style.configure(
            "TEntry",
            fieldbackground=self.theme["entry_bg"],
            foreground=self.theme["entry_fg"],
            bordercolor=self.theme["border"],
            padding=4,
            font=(base_font, 10),
        )

        style.configure(
            "Nature.TCombobox",
            fieldbackground=self.theme["entry_bg"],
            foreground=self.theme["entry_fg"],
            background=self.theme["panel"],
            arrowcolor=self.theme["fg"],
            bordercolor=self.theme["border"],
            font=(base_font, 10)
        )
        style.map(
            "Nature.TCombobox",
            fieldbackground=[("readonly", self.theme["entry_bg"])],
            selectbackground=[("readonly", self.theme["accent"])],
            selectforeground=[("readonly", self.theme["fg"])],
        )

        style.configure(
            "Info.Treeview",
            background=self.theme["info_table_row_bg"],
            fieldbackground=self.theme["info_table_row_bg"],
            foreground=self.theme["fg"],
            bordercolor=self.theme["border"],
            rowheight=28,
            font=(base_font, 9),
        )
        style.map(
            "Info.Treeview",
            background=[("selected", self.theme["accent"])],
            foreground=[("selected", self.theme["fg"])],
        )

        style.configure(
            "Info.Treeview.Heading",
            background=self.theme["info_table_header_bg"],
            foreground=self.theme["fg"],
            relief="flat",
            font=(base_font, 10, "bold"),
        )

    def _on_theme_palette_selected(self, _event=None):
        palette = self.theme_palette_var.get().strip()
        if palette not in PALETTES:
            return
        self.theme_cfg.palette = palette
        self.theme = self.theme_manager.build_theme(self.theme_cfg)
        self.theme_manager.save(self.theme_cfg)
        self._apply_theme(refresh_canvas=True)

    def _toggle_theme_mode(self):
        self.theme_cfg.mode = "light" if self.theme_cfg.mode == "dark" else "dark"
        self.theme_mode_var.set(self.theme_cfg.mode)
        self.theme = self.theme_manager.build_theme(self.theme_cfg)
        self.theme_manager.save(self.theme_cfg)
        self._apply_theme(refresh_canvas=True)

    def _on_language_selected(self, _event=None):
        lang = self.language_var.get().strip().lower()
        if lang not in I18nManager.SUPPORTED:
            lang = "en"
        if lang == self._lang:
            return
        self._lang = lang
        self.ui_cfg.language = lang
        self.i18n.save_ui_config(self.ui_cfg)
        self._ui_font_family = self._resolve_ui_font_family(lang)
        self._apply_language()

    def _apply_theme(self, refresh_canvas: bool = True):
        if self._use_ctk:
            ctk.set_appearance_mode("Dark" if self.theme_cfg.mode == "dark" else "Light")
            self.configure(fg_color=self.theme["bg"])
        else:
            self.configure(bg=self.theme["bg"])
        self._setup_style()

        if hasattr(self, "root_container"):
            try:
                self.root_container.configure(fg_color=self.theme["panel"])
            except Exception:
                self.root_container.configure(style="Panel.TFrame")
        if hasattr(self, "toolbar"):
            try:
                self.toolbar.configure(fg_color=self.theme["panel_alt"])
            except Exception:
                self.toolbar.configure(style="Toolbar.TFrame")
        if hasattr(self, "left"):
            try:
                self.left.configure(fg_color=self.theme["panel"])
            except Exception:
                self.left.configure(style="Panel.TFrame")
        if hasattr(self, "center"):
            try:
                self.center.configure(fg_color=self.theme["panel"])
            except Exception:
                self.center.configure(style="Panel.TFrame")
        if hasattr(self, "right"):
            try:
                self.right.configure(fg_color=self.theme["panel"])
            except Exception:
                self.right.configure(style="Panel.TFrame")

        if hasattr(self, "listbox"):
            self.listbox.configure(
                bg=self.theme["listbox_bg"],
                fg=self.theme["listbox_fg"],
                highlightbackground=self.theme["border"],
                selectbackground=self.theme["listbox_sel_bg"],
                selectforeground=self.theme["listbox_sel_fg"],
            )
        if hasattr(self, "sprite_label"):
            self.sprite_label.configure(bg=self.theme["panel"])
        if hasattr(self, "_sprite_slot"):
            self._sprite_slot.configure(bg=self.theme["panel"])
        if hasattr(self, "type_dot"):
            self.type_dot.configure(bg=self.theme["panel"])
        if hasattr(self, "_sprite_frame"):
            try:
                self._sprite_frame.configure(fg_color=self.theme["panel"])
            except Exception:
                try:
                    self._sprite_frame.configure(style="Panel.TFrame")
                except Exception:
                    pass
        if hasattr(self, "_sprite_name_row"):
            try:
                self._sprite_name_row.configure(fg_color=self.theme["panel"])
            except Exception:
                try:
                    self._sprite_name_row.configure(style="Panel.TFrame")
                except Exception:
                    pass
        if hasattr(self, "nature_combo"):
            try:
                self.nature_combo.configure(style="Nature.TCombobox")
            except Exception:
                self.nature_combo.configure(
                    fg_color=self.theme["entry_bg"],
                    text_color=self.theme["fg"],
                    button_color=self.theme["panel_alt"],
                    dropdown_fg_color=self.theme["panel"],
                    dropdown_text_color=self.theme["fg"],
                )
        if hasattr(self, "canvas"):
            self.canvas.configure(bg=self.theme["canvas_bg"], highlightbackground=self.theme["border"])
        if hasattr(self, "gender_box"):
            try:
                self.gender_box.configure(
                    bg=self.theme["text_box_bg"],
                    fg=self.theme["text_box_fg"],
                    insertbackground=self.theme["fg"],
                    highlightbackground=self.theme["border"],
                )
            except Exception:
                self.gender_box.configure(
                    fg_color=self.theme["text_box_bg"],
                    text_color=self.theme["text_box_fg"],
                    border_color=self.theme["border"],
                )
        if hasattr(self, "notes_box"):
            try:
                self.notes_box.configure(
                    bg=self.theme["text_box_bg"],
                    fg=self.theme["text_box_fg"],
                    insertbackground=self.theme["fg"],
                    highlightbackground=self.theme["border"],
                )
            except Exception:
                self.notes_box.configure(
                    fg_color=self.theme["text_box_bg"],
                    text_color=self.theme["text_box_fg"],
                    border_color=self.theme["border"],
                )
        if hasattr(self, "cost_details"):
            try:
                self.cost_details.configure(text_color=self.theme["fg"])
            except Exception:
                try:
                    self.cost_details.configure(foreground=self.theme["fg"])
                except Exception:
                    pass
        if hasattr(self, "theme_mode_btn"):
            self.theme_mode_btn.configure(text=self.t("toolbar.mode", mode=("Dark" if self.theme_cfg.mode == "dark" else "Light")))
        if self._use_ctk:
            ctk_widgets = [
                "toggle_left_btn",
                "toggle_right_btn",
                "inventory_btn",
                "theme_mode_btn",
                "info_btn",
                "compatible_cb",
            ]
            for wn in ctk_widgets:
                w = getattr(self, wn, None)
                if w is None:
                    continue
                try:
                    w.configure(
                        fg_color=self.theme["panel_alt"],
                        hover_color=self.theme["accent"],
                        text_color=self.theme["fg"],
                    )
                except Exception:
                    pass
            for wn in ("language_combo", "theme_palette_combo", "nature_combo"):
                w = getattr(self, wn, None)
                if w is None:
                    continue
                try:
                    w.configure(
                        fg_color=self.theme["entry_bg"],
                        text_color=self.theme["fg"],
                        button_color=self.theme["panel_alt"],
                        button_hover_color=self.theme["accent"],
                        dropdown_fg_color=self.theme["panel"],
                        dropdown_text_color=self.theme["fg"],
                    )
                except Exception:
                    pass
            for wn in (
                "_left_header_label",
                "_center_header_label",
                "_right_header_label",
                "_right_gender_header_label",
                "_right_notes_header_label",
                "name_label",
            ):
                w = getattr(self, wn, None)
                if w is None:
                    continue
                try:
                    w.configure(text_color=self.theme["accent"])
                except Exception:
                    pass
            for wn in ("lang_label", "theme_label", "egg_groups_label", "status_label"):
                w = getattr(self, wn, None)
                if w is None:
                    continue
                try:
                    w.configure(text_color=self.theme["muted"])
                except Exception:
                    pass

        self._refresh_iv_toggle_styles()
        if self._info_window and self._info_window.winfo_exists():
            self._apply_info_window_theme()
        if self._inventory_window and self._inventory_window.winfo_exists():
            try:
                self._inventory_window.configure(bg=self.theme["panel"])
            except Exception:
                pass
            if self._inventory_canvas is not None:
                try:
                    self._inventory_canvas.configure(
                        bg=self.theme["entry_bg"],
                        highlightbackground=self.theme["border"],
                    )
                except Exception:
                    pass
            notes_widget = self._inventory_form_vars.get("notes_widget") if self._inventory_form_vars else None
            if notes_widget is not None:
                try:
                    notes_widget.configure(
                        bg=self.theme["entry_bg"],
                        fg=self.theme["fg"],
                        insertbackground=self.theme["fg"],
                        highlightbackground=self.theme["border"],
                    )
                except Exception:
                    pass
            if hasattr(self, "_inventory_detail_sprite_label"):
                try:
                    self._inventory_detail_sprite_label.configure(bg=self.theme["panel"])
                except Exception:
                    pass
            self._inventory_draw_box()

        if refresh_canvas:
            if self.selected:
                # Recompose current sprite against new panel color immediately.
                self._load_sprite_async(self.selected.id, self._selection_generation_id)
                self._request_recompute(reason="theme")
            else:
                self._render_empty()

    def _apply_language(self):
        self.title(self.t("app.title", version=APP_VERSION))
        self.language_var.set(self._lang.upper())
        self._setup_style()
        if hasattr(self, "toggle_left_btn"):
            self.toggle_left_btn.configure(text=(self.t("toolbar.hide_selection") if self._left_visible else self.t("toolbar.show_selection")))
        if hasattr(self, "toggle_right_btn"):
            self.toggle_right_btn.configure(text=(self.t("toolbar.hide_costs") if self._right_visible else self.t("toolbar.show_costs")))
        if hasattr(self, "inventory_btn"):
            self.inventory_btn.configure(text=self.t("toolbar.inventory"))
        if hasattr(self, "theme_mode_btn"):
            self.theme_mode_btn.configure(text=self.t("toolbar.mode", mode=("Dark" if self.theme_cfg.mode == "dark" else "Light")))
        if hasattr(self, "lang_label"):
            self.lang_label.configure(text=self.t("toolbar.language"))
        if hasattr(self, "theme_label"):
            self.theme_label.configure(text=self.t("toolbar.theme"))
        if hasattr(self, "_left_header_label"):
            self._left_header_label.configure(text=self.t("left.selection"))
        if hasattr(self, "_pokemon_label"):
            self._pokemon_label.configure(text=self.t("left.pokemon"))
        if hasattr(self, "_ivs_header_label"):
            self._ivs_header_label.configure(text=self.t("left.ivs"))
        if hasattr(self, "_nature_header_label"):
            self._nature_header_label.configure(text=self.t("left.nature"))
        if hasattr(self, "info_btn"):
            self.info_btn.configure(text=self.t("left.info"))
        if hasattr(self, "compatible_cb"):
            self.compatible_cb.configure(text=self.t("left.compatible"))
        if hasattr(self, "_center_header_label"):
            self._center_header_label.configure(text=self.t("center.layers"))
        if hasattr(self, "_right_header_label"):
            self._right_header_label.configure(text=self.t("right.costs"))
        if hasattr(self, "_right_gender_header_label"):
            self._right_gender_header_label.configure(text=self.t("right.gender_plan"))
        if hasattr(self, "_right_notes_header_label"):
            self._right_notes_header_label.configure(text=self.t("right.notes"))
        for btn in self._iv_buttons.values():
            try:
                btn.configure(font=(self._ui_font_family, 9, "bold"))
            except Exception:
                pass
        if not self.selected:
            self._egg_groups_var.set(self.t("left.egg_groups", groups="—"))
        if hasattr(self, "status_label"):
            self.status_label.configure(font=(self._ui_font_family, 9))
        if self._info_window and self._info_window.winfo_exists():
            self._build_info_window_texts()
            self._apply_info_window_theme()
            if self._info_species_id:
                self._set_info_loading(self.t("info.loading"))
                self._load_info_async(self._info_species_id)
        if self._inventory_window and self._inventory_window.winfo_exists():
            self._inventory_window.destroy()
            self._inventory_window = None
            self._open_inventory_window()
        if self.selected:
            self._request_recompute(reason="language")
        else:
            self._set_status("status.ready", is_key=True, version=APP_VERSION)

    # ---------- Layout ----------
    def _build_layout(self):
        if self._use_ctk:
            root = ctk.CTkFrame(self, fg_color=self.theme["panel"], corner_radius=10)
        else:
            root = ttk.Frame(self, style="Panel.TFrame")
        root.pack(fill="both", expand=True, padx=12, pady=12)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        self.root_container = root

        if self._use_ctk:
            self.toolbar = ctk.CTkFrame(root, fg_color=self.theme["panel_alt"], corner_radius=8)
        else:
            self.toolbar = ttk.Frame(root, style="Toolbar.TFrame")
        self.toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.toolbar.columnconfigure(0, weight=0)
        self.toolbar.columnconfigure(1, weight=0)
        self.toolbar.columnconfigure(2, weight=0)
        self.toolbar.columnconfigure(3, weight=1)
        self.toolbar.columnconfigure(4, weight=0)
        self.toolbar.columnconfigure(5, weight=0)
        self.toolbar.columnconfigure(6, weight=0)
        self.toolbar.columnconfigure(7, weight=0)
        self.toolbar.columnconfigure(8, weight=0)

        if self._use_ctk:
            self.toggle_left_btn = ctk.CTkButton(self.toolbar, text=self.t("toolbar.hide_selection"), command=self._toggle_left_panel, width=130)
        else:
            self.toggle_left_btn = ttk.Button(
                self.toolbar, text=self.t("toolbar.hide_selection"), style="Toolbar.TButton", command=self._toggle_left_panel
            )
        self.toggle_left_btn.grid(row=0, column=0, padx=(8, 6), pady=8, sticky="w")
        if self._use_ctk:
            self.toggle_right_btn = ctk.CTkButton(self.toolbar, text=self.t("toolbar.hide_costs"), command=self._toggle_right_panel, width=120)
        else:
            self.toggle_right_btn = ttk.Button(
                self.toolbar, text=self.t("toolbar.hide_costs"), style="Toolbar.TButton", command=self._toggle_right_panel
            )
        self.toggle_right_btn.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="w")
        if self._use_ctk:
            self.inventory_btn = ctk.CTkButton(self.toolbar, text=self.t("toolbar.inventory"), command=self._open_inventory_window, width=120)
        else:
            self.inventory_btn = ttk.Button(
                self.toolbar, text=self.t("toolbar.inventory"), style="Toolbar.TButton", command=self._open_inventory_window
            )
        self.inventory_btn.grid(row=0, column=2, padx=(0, 8), pady=8, sticky="w")

        if self._use_ctk:
            self.lang_label = ctk.CTkLabel(self.toolbar, text=self.t("toolbar.language"))
        else:
            self.lang_label = ttk.Label(self.toolbar, text=self.t("toolbar.language"), style="Muted.TLabel")
        self.lang_label.grid(row=0, column=3, padx=(0, 6), sticky="e")
        if self._use_ctk:
            self.language_combo = ctk.CTkComboBox(
                self.toolbar,
                variable=self.language_var,
                values=["ES", "EN", "ZH"],
                width=70,
                command=lambda _v: self._on_language_selected(),
            )
        else:
            self.language_combo = ttk.Combobox(
                self.toolbar,
                textvariable=self.language_var,
                values=["ES", "EN", "ZH"],
                state="readonly",
                width=6,
                style="Nature.TCombobox",
            )
        self.language_combo.grid(row=0, column=4, padx=(0, 10), pady=8, sticky="e")
        if not self._use_ctk:
            self.language_combo.bind("<<ComboboxSelected>>", self._on_language_selected)

        if self._use_ctk:
            self.theme_label = ctk.CTkLabel(self.toolbar, text=self.t("toolbar.theme"))
        else:
            self.theme_label = ttk.Label(self.toolbar, text=self.t("toolbar.theme"), style="Muted.TLabel")
        self.theme_label.grid(row=0, column=5, padx=(0, 6), sticky="e")
        if self._use_ctk:
            self.theme_palette_combo = ctk.CTkComboBox(
                self.toolbar,
                variable=self.theme_palette_var,
                values=list(PALETTES.keys()),
                width=170,
                command=lambda _v: self._on_theme_palette_selected(),
            )
        else:
            self.theme_palette_combo = ttk.Combobox(
                self.toolbar,
                textvariable=self.theme_palette_var,
                values=list(PALETTES.keys()),
                state="readonly",
                width=16,
                style="Nature.TCombobox",
            )
        self.theme_palette_combo.grid(row=0, column=6, padx=(0, 6), pady=8, sticky="e")
        if not self._use_ctk:
            self.theme_palette_combo.bind("<<ComboboxSelected>>", self._on_theme_palette_selected)
        if self._use_ctk:
            self.theme_mode_btn = ctk.CTkButton(
                self.toolbar,
                text=self.t("toolbar.mode", mode=("Dark" if self.theme_cfg.mode == "dark" else "Light")),
                command=self._toggle_theme_mode,
                width=120,
            )
        else:
            self.theme_mode_btn = ttk.Button(
                self.toolbar,
                text=self.t("toolbar.mode", mode=("Dark" if self.theme_cfg.mode == "dark" else "Light")),
                style="Toolbar.TButton",
                command=self._toggle_theme_mode,
            )
        self.theme_mode_btn.grid(row=0, column=7, padx=(0, 8), pady=8, sticky="e")

        if self._use_ctk:
            main = ctk.CTkFrame(root, fg_color=self.theme["panel"], corner_radius=0)
        else:
            main = ttk.Frame(root, style="Panel.TFrame")
        main.grid(row=1, column=0, sticky="nsew")
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=4)
        main.columnconfigure(2, weight=3)
        main.rowconfigure(0, weight=1)
        self.main_grid = main

        if self._use_ctk:
            self.left = ctk.CTkFrame(main, fg_color=self.theme["panel"], corner_radius=8)
            self.center = ctk.CTkFrame(main, fg_color=self.theme["panel"], corner_radius=8)
            self.right = ctk.CTkFrame(main, fg_color=self.theme["panel"], corner_radius=8)
        else:
            self.left = ttk.Frame(main, style="Panel.TFrame")
            self.center = ttk.Frame(main, style="Panel.TFrame")
            self.right = ttk.Frame(main, style="Panel.TFrame")
        self.left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        self.center.grid(row=0, column=1, sticky="nsew", padx=(0, 10))
        self.right.grid(row=0, column=2, sticky="nsew")

        self._build_left()
        self._build_center()
        self._build_right()

        if self._use_ctk:
            self.status_label = ctk.CTkLabel(root, textvariable=self._status_var, anchor="w")
        else:
            self.status_label = ttk.Label(root, textvariable=self._status_var, style="Muted.TLabel")
        self.status_label.grid(row=2, column=0, sticky="ew", pady=(6, 0), padx=(2, 2))
        self._update_panel_layout()

    def _toggle_left_panel(self):
        self._left_visible = not self._left_visible
        self._update_panel_layout()

    def _toggle_right_panel(self):
        self._right_visible = not self._right_visible
        self._update_panel_layout()

    def _update_panel_layout(self):
        if self._left_visible:
            self.left.grid()
        else:
            self.left.grid_remove()
        if self._right_visible:
            self.right.grid()
        else:
            self.right.grid_remove()

        left_w = 3 if self._left_visible else 0
        right_w = 3 if self._right_visible else 0
        center_w = 10 if (not self._left_visible and not self._right_visible) else (6 if (self._left_visible ^ self._right_visible) else 4)
        self.main_grid.columnconfigure(0, weight=left_w)
        self.main_grid.columnconfigure(1, weight=center_w)
        self.main_grid.columnconfigure(2, weight=right_w)
        self.toggle_left_btn.configure(text=(self.t("toolbar.hide_selection") if self._left_visible else self.t("toolbar.show_selection")))
        self.toggle_right_btn.configure(text=(self.t("toolbar.hide_costs") if self._right_visible else self.t("toolbar.show_costs")))

    # ---------- Left panel ----------
    def _build_left(self):
        p = self.left
        p.columnconfigure(0, weight=1)
        if self._use_ctk:
            self._left_header_label = ctk.CTkLabel(p, text=self.t("left.selection"), anchor="w", font=(self._ui_font_family, 22, "bold"), text_color=self.theme["accent"])
        else:
            self._left_header_label = ttk.Label(p, text=self.t("left.selection"), style="Header.TLabel")
        self._left_header_label.grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))

        # Search entry with Enter binding
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        if self._use_ctk:
            entry = ctk.CTkEntry(p, textvariable=self.search_var)
        else:
            entry = ttk.Entry(p, textvariable=self.search_var)
        entry.grid(row=1, column=0, sticky="ew", padx=12)
        # Bind Enter key to auto select the first result
        entry.bind("<Return>", lambda e: self._select_first_result())
        entry.bind("<KP_Enter>", lambda e: self._select_first_result())

        if self._use_ctk:
            self._pokemon_label = ctk.CTkLabel(p, text=self.t("left.pokemon"), anchor="w")
        else:
            self._pokemon_label = ttk.Label(p, text=self.t("left.pokemon"), style="Muted.TLabel")
        self._pokemon_label.grid(row=2, column=0, sticky="w", padx=12, pady=(10, 2))

        # Listbox inside a frame with scrollbar
        if self._use_ctk:
            lb_frame = ctk.CTkFrame(p, fg_color=self.theme["panel"], corner_radius=8)
        else:
            lb_frame = ttk.Frame(p, style="Panel.TFrame")
        lb_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 10))
        lb_frame.columnconfigure(0, weight=1)
        lb_frame.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            lb_frame, height=12,
            bg=self.theme["listbox_bg"], fg=self.theme["listbox_fg"],
            highlightthickness=1, highlightbackground=self.theme["border"],
            selectbackground=self.theme["listbox_sel_bg"], selectforeground=self.theme["listbox_sel_fg"]
        )
        self.listbox.grid(row=0, column=0, sticky="nsew")
        self.listbox.bind("<<ListboxSelect>>", lambda e: self._on_select())
        sb = ttk.Scrollbar(lb_frame, orient="vertical", command=self.listbox.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.listbox.config(yscrollcommand=sb.set)

        # Sprite frame
        if self._use_ctk:
            sprite_frame = ctk.CTkFrame(p, fg_color=self.theme["panel"], corner_radius=8)
        else:
            sprite_frame = ttk.Frame(p, style="Panel.TFrame")
        sprite_frame.grid(row=4, column=0, sticky="ew", padx=12, pady=(0, 10))
        self._sprite_frame = sprite_frame
        sprite_frame.columnconfigure(1, weight=1)
        sprite_slot = tk.Frame(sprite_frame, bg=self.theme["panel"], width=108, height=108, highlightthickness=0, bd=0)
        sprite_slot.grid(row=0, column=0, rowspan=2, padx=(0, 10), pady=6, sticky="nw")
        sprite_slot.grid_propagate(False)
        self._sprite_slot = sprite_slot
        self.sprite_label = tk.Label(sprite_slot, bg=self.theme["panel"], bd=0, highlightthickness=0)
        self.sprite_label.place(relx=0.5, rely=0.5, anchor="center")
        if self._use_ctk:
            name_row = ctk.CTkFrame(sprite_frame, fg_color=self.theme["panel"], corner_radius=0)
        else:
            name_row = ttk.Frame(sprite_frame, style="Panel.TFrame")
        name_row.grid(row=0, column=1, sticky="w")
        self._sprite_name_row = name_row
        name_row.columnconfigure(1, weight=1)
        self.type_dot = tk.Canvas(name_row, width=10, height=10, bg=self.theme["panel"], highlightthickness=0)
        self.type_dot.grid(row=0, column=0, padx=(0, 6))
        self.type_dot_id = self.type_dot.create_oval(1, 1, 9, 9, fill="#444", outline="#444")
        if self._use_ctk:
            self.name_label = ctk.CTkLabel(
                name_row,
                textvariable=self._name_type_text_var,
                anchor="w",
                font=(self._ui_font_family, 20, "bold"),
                text_color=self.theme["accent"],
                width=360,
            )
        else:
            self.name_label = ttk.Label(name_row, textvariable=self._name_type_text_var, style="Header.TLabel")
        self.name_label.grid(row=0, column=1, sticky="w")
        if self._use_ctk:
            self.info_btn = ctk.CTkButton(sprite_frame, text=self.t("left.info"), command=self._open_pokemon_info_window, width=80)
        else:
            self.info_btn = ttk.Button(sprite_frame, text=self.t("left.info"), command=self._open_pokemon_info_window)
        self.info_btn.grid(row=0, column=2, sticky="e", padx=(8, 0))
        if self._use_ctk:
            self.egg_groups_label = ctk.CTkLabel(sprite_frame, textvariable=self._egg_groups_var, anchor="w")
        else:
            self.egg_groups_label = ttk.Label(sprite_frame, textvariable=self._egg_groups_var, style="Muted.TLabel")
        self.egg_groups_label.grid(row=1, column=1, columnspan=2, sticky="w")

        # IV toggles
        if self._use_ctk:
            self._ivs_header_label = ctk.CTkLabel(p, text=self.t("left.ivs"), anchor="w", font=(self._ui_font_family, 22, "bold"), text_color=self.theme["accent"])
        else:
            self._ivs_header_label = ttk.Label(p, text=self.t("left.ivs"), style="Header.TLabel")
        self._ivs_header_label.grid(row=5, column=0, sticky="w", padx=12, pady=(8, 6))
        if self._use_ctk:
            iv_grid = ctk.CTkFrame(p, fg_color=self.theme["panel"], corner_radius=0)
        else:
            iv_grid = ttk.Frame(p, style="Panel.TFrame")
        iv_grid.grid(row=6, column=0, sticky="ew", padx=12)
        self._build_iv_toggles(iv_grid)

        if self._use_ctk:
            self._nature_header_label = ctk.CTkLabel(p, text=self.t("left.nature"), anchor="w", font=(self._ui_font_family, 22, "bold"), text_color=self.theme["accent"])
        else:
            self._nature_header_label = ttk.Label(p, text=self.t("left.nature"), style="Header.TLabel")
        self._nature_header_label.grid(row=7, column=0, sticky="w", padx=12, pady=(10, 4))
        if self._use_ctk:
            self.nature_combo = ctk.CTkComboBox(
                p,
                variable=self.nature_var,
                values=NATURE_OPTIONS,
                command=lambda _v: self._request_recompute(reason="nature"),
            )
        else:
            self.nature_combo = ttk.Combobox(
                p, textvariable=self.nature_var, values=NATURE_OPTIONS, state="readonly", style="Nature.TCombobox"
            )
        self.nature_combo.grid(row=8, column=0, sticky="ew", padx=12, pady=(0, 10))
        if not self._use_ctk:
            self.nature_combo.bind("<<ComboboxSelected>>", lambda e: self._request_recompute(reason="nature"))
        if self._use_ctk:
            self.compatible_cb = ctk.CTkCheckBox(p, text=self.t("left.compatible"), variable=self.compatible_var, command=lambda: self._request_recompute(reason="compatible"))
        else:
            self.compatible_cb = ttk.Checkbutton(p, text=self.t("left.compatible"), variable=self.compatible_var, command=lambda: self._request_recompute(reason="compatible"))
        self.compatible_cb.grid(row=9, column=0, sticky="w", padx=12, pady=(0, 10))

        p.rowconfigure(3, weight=1)

    def _build_iv_toggles(self, parent: ttk.Frame):
        for i, stat in enumerate(STATS):
            if self._use_ctk:
                btn = ctk.CTkButton(
                    parent,
                    text=stat,
                    command=lambda s=stat: self._on_iv_toggle(s),
                    corner_radius=8,
                    height=30,
                    font=(self._ui_font_family, 12, "bold"),
                )
            else:
                btn = tk.Button(
                    parent,
                    text=stat,
                    relief="flat",
                    bd=0,
                    padx=10,
                    pady=6,
                    cursor="hand2",
                    command=lambda s=stat: self._on_iv_toggle(s),
                    font=(self._ui_font_family, 9, "bold"),
                )
            btn.grid(row=i // 3, column=i % 3, sticky="ew", padx=4, pady=4)
            parent.columnconfigure(i % 3, weight=1)
            self._iv_buttons[stat] = btn
            self._set_iv_toggle_visual(stat, self.iv_vars[stat].get())

    def _set_iv_toggle_visual(self, stat: str, enabled: bool):
        btn = self._iv_buttons.get(stat)
        if not btn:
            return
        if enabled:
            bg = IV_COLORS.get(stat, self.theme["accent"])
            fg = "#081018" if self.theme_cfg.mode == "light" else "#EAF2FF"
            active_bg = bg
            active_fg = fg
        else:
            bg = self.theme["iv_off_bg"]
            fg = self.theme["iv_off_fg"]
            active_bg = self.theme["panel_alt"]
            active_fg = self.theme["fg"]
        if self._use_ctk:
            btn.configure(
                fg_color=bg,
                text_color=fg,
                hover_color=active_bg,
                border_color=self.theme["border"],
                border_width=1,
            )
        else:
            btn.configure(
                bg=bg,
                fg=fg,
                activebackground=active_bg,
                activeforeground=active_fg,
                highlightthickness=1,
                highlightbackground=self.theme["border"],
                highlightcolor=self.theme["accent"],
            )

    def _refresh_iv_toggle_styles(self):
        for stat in STATS:
            self._set_iv_toggle_visual(stat, self.iv_vars[stat].get())

    def _on_iv_toggle(self, stat: str):
        var = self.iv_vars[stat]
        var.set(not var.get())
        self._set_iv_toggle_visual(stat, var.get())
        self._request_recompute(reason=f"iv:{stat}")

    # ---------- Center panel ----------
    def _build_center(self):
        p = self.center
        p.columnconfigure(0, weight=1)
        p.rowconfigure(1, weight=1)
        self._center_header_label = ttk.Label(p, text=self.t("center.layers"), style="Header.TLabel")
        self._center_header_label.grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        self.canvas = tk.Canvas(p, bg=self.theme["canvas_bg"], highlightthickness=1, highlightbackground=self.theme["border"])
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<ButtonPress-1>", self._on_canvas_press)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<Motion>", self._on_canvas_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<MouseWheel>", self._on_canvas_mousewheel)  # Windows / macOS
        self.canvas.bind("<Button-4>", self._on_canvas_mousewheel)    # Linux up
        self.canvas.bind("<Button-5>", self._on_canvas_mousewheel)    # Linux down

    # ---------- Right panel ----------
    def _build_right(self):
        p = self.right
        p.columnconfigure(0, weight=1)
        p.rowconfigure(7, weight=1)
        if self._use_ctk:
            self._right_header_label = ctk.CTkLabel(p, text=self.t("right.costs"), anchor="w", font=(self._ui_font_family, 22, "bold"), text_color=self.theme["accent"])
        else:
            self._right_header_label = ttk.Label(p, text=self.t("right.costs"), style="Header.TLabel")
        self._right_header_label.grid(row=0, column=0, sticky="w", padx=12, pady=(12, 6))
        if self._use_ctk:
            self.cost_title = ctk.CTkLabel(p, text="—", anchor="w", font=(self._ui_font_family, 20, "bold"), text_color=self.theme["fg"])
        else:
            self.cost_title = ttk.Label(p, text="—", style="CostTitle.TLabel")
        self.cost_title.grid(row=1, column=0, sticky="w", padx=12)
        if self._use_ctk:
            self.cost_details = ctk.CTkLabel(p, text="", justify="left", anchor="w", text_color=self.theme["fg"])
        else:
            self.cost_details = ttk.Label(p, text="", justify="left")
        self.cost_details.grid(row=2, column=0, sticky="w", padx=12, pady=(6, 10))
        if self._use_ctk:
            self._right_gender_header_label = ctk.CTkLabel(p, text=self.t("right.gender_plan"), anchor="w", font=(self._ui_font_family, 22, "bold"), text_color=self.theme["accent"])
        else:
            self._right_gender_header_label = ttk.Label(p, text=self.t("right.gender_plan"), style="Header.TLabel")
        self._right_gender_header_label.grid(row=3, column=0, sticky="w", padx=12, pady=(8, 6))
        if self._use_ctk:
            self.gender_box = ctk.CTkTextbox(p, height=180)
        else:
            self.gender_box = tk.Text(
                p, height=10, wrap="word",
                bg=self.theme["text_box_bg"], fg=self.theme["text_box_fg"],
                insertbackground=self.theme["fg"],
                highlightthickness=1, highlightbackground=self.theme["border"]
            )
        self.gender_box.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 10))
        if self._use_ctk:
            self._right_notes_header_label = ctk.CTkLabel(p, text=self.t("right.notes"), anchor="w", font=(self._ui_font_family, 22, "bold"), text_color=self.theme["accent"])
        else:
            self._right_notes_header_label = ttk.Label(p, text=self.t("right.notes"), style="Header.TLabel")
        self._right_notes_header_label.grid(row=6, column=0, sticky="w", padx=12, pady=(8, 6))
        if self._use_ctk:
            self.notes_box = ctk.CTkTextbox(p, height=220)
        else:
            self.notes_box = tk.Text(
                p, height=10, wrap="word",
                bg=self.theme["text_box_bg"], fg=self.theme["text_box_fg"],
                insertbackground=self.theme["fg"],
                highlightthickness=1, highlightbackground=self.theme["border"]
            )
        self.notes_box.grid(row=7, column=0, sticky="nsew", padx=12, pady=(0, 12))

    # ---------- Data load ----------
    def _load_data_async(self):
        def task():
            try:
                items = self.repo.load()
                self.items = items
                self.filtered = items[:]
                self.after(0, self._refresh_list)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(self.t("dialog.error"), str(e)))
        threading.Thread(target=task, daemon=True).start()

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for p in self.filtered[:6000]:
            self.listbox.insert(tk.END, p.name)
        if self.filtered:
            self._select_first_result()
        else:
            self.selected = None
            self._name_type_text_var.set("—")
            self._egg_groups_var.set(self.t("left.egg_groups", groups="—"))
            self._show_default_sprite()
            self._render_empty()

    def _apply_filter(self):
        q = self.search_var.get().strip().lower()
        if not q:
            self.filtered = self.items[:]
        else:
            self.filtered = [p for p in self.items if q in p.name.lower()]
        self._refresh_list()

    def _select_first_result(self):
        if not self.filtered or self.listbox.size() == 0:
            return
        # Clear existing selection and select first item
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(0)
        self.listbox.activate(0)
        self.listbox.see(0)
        self._on_select()

    # ---------- Selection ----------
    def _on_select(self):
        sel = self.listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.filtered):
            return
        entry = self.filtered[idx]
        self.selected = entry
        self._selection_generation_id += 1
        sel_gen = self._selection_generation_id
        self._name_type_text_var.set(f"{entry.name} (#{entry.id})")
        self._egg_groups_var.set(self.t("left.egg_groups_loading"))
        self.type_dot.itemconfig(self.type_dot_id, fill="#444", outline="#444")
        self._load_sprite_async(entry.id, sel_gen)
        self._load_species_meta_async(entry.id, entry.name, sel_gen)
        self._request_recompute(reason="select")

    def _open_inventory_window(self):
        return self._open_inventory_window_pc()

    # ---------- Inventory PC Box ----------
    def _open_inventory_window_pc(self):
        if self._inventory_window and self._inventory_window.winfo_exists():
            self._inventory_window.lift()
            self._inventory_window.focus_set()
            self._inventory_draw_box()
            return

        win = tk.Toplevel(self)
        win.title(self.t("inventory.title"))
        win.geometry("1240x760")
        win.minsize(1080, 640)
        win.configure(bg=self.theme["panel"])
        win.protocol("WM_DELETE_WINDOW", lambda: setattr(self, "_inventory_window", None) or win.destroy())
        self._inventory_window = win

        root = ttk.Frame(win, style="Panel.TFrame")
        root.pack(fill="both", expand=True, padx=10, pady=10)
        root.columnconfigure(0, weight=5)
        root.columnconfigure(1, weight=3)
        root.rowconfigure(1, weight=1)

        header = ttk.Frame(root, style="Panel.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Button(header, text="<", width=3, command=self._inventory_prev_box).pack(side="left")
        ttk.Label(header, textvariable=self._inventory_box_label_var, style="Header.TLabel").pack(side="left", padx=(6, 10))
        ttk.Button(header, text=">", width=3, command=self._inventory_next_box).pack(side="left", padx=(0, 10))
        ttk.Button(header, text=self.t("inventory.btn.import"), command=self._inventory_import_pc).pack(side="left", padx=(0, 6))
        ttk.Button(header, text=self.t("inventory.btn.export"), command=self._inventory_export_pc).pack(side="left")

        left = ttk.Frame(root, style="Panel.TFrame")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(0, weight=1)

        canvas = tk.Canvas(left, bg=self.theme["entry_bg"], highlightthickness=1, highlightbackground=self.theme["border"])
        canvas.grid(row=0, column=0, sticky="nsew")
        ysb = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        ysb.grid(row=0, column=1, sticky="ns")
        xsb = ttk.Scrollbar(left, orient="horizontal", command=canvas.xview)
        xsb.grid(row=1, column=0, sticky="ew")
        canvas.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        canvas.bind("<ButtonPress-1>", self._inventory_on_canvas_press)
        canvas.bind("<B1-Motion>", self._inventory_on_canvas_motion)
        canvas.bind("<ButtonRelease-1>", self._inventory_on_canvas_release)
        self._inventory_canvas = canvas

        right = ttk.Frame(root, style="Panel.TFrame")
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self._inventory_form_vars = {
            "id": tk.StringVar(value=""),
            "species": tk.StringVar(value=""),
            "species_id_label": tk.StringVar(value="—"),
            "gender": tk.StringVar(value="U"),
            "nature": tk.StringVar(value=""),
            "level": tk.StringVar(value=str(self.inventory_settings.default_level)),
            "ball": tk.StringVar(value=""),
            "price": tk.StringVar(value="0"),
            "egg_groups": tk.StringVar(value="—"),
        }
        iv_vars: Dict[str, tk.IntVar] = {s: tk.IntVar(value=0) for s in STAT_KEYS}
        self._inventory_form_vars["ivs"] = iv_vars

        notebook = ttk.Notebook(right)
        notebook.grid(row=0, column=0, sticky="nsew")
        tab_data = ttk.Frame(notebook, style="Panel.TFrame")
        tab_stats = ttk.Frame(notebook, style="Panel.TFrame")
        tab_ivs = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(tab_data, text=self.t("inventory.tab.data"))
        notebook.add(tab_stats, text=self.t("inventory.tab.stats"))
        notebook.add(tab_ivs, text=self.t("inventory.tab.ivs"))

        tab_data.columnconfigure(0, weight=1)
        tab_data.rowconfigure(18, weight=1)

        preview = tk.Frame(tab_data, bg=self.theme["panel"])
        preview.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 6))
        preview.columnconfigure(1, weight=1)
        self._inventory_detail_img = None
        self._inventory_detail_sprite_label = tk.Label(preview, bg=self.theme["panel"], bd=0, highlightthickness=0)
        self._inventory_detail_sprite_label.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        self._inventory_species_id_label = ttk.Label(preview, textvariable=self._inventory_form_vars["species_id_label"], style="Muted.TLabel")
        self._inventory_species_id_label.grid(row=0, column=1, sticky="w")

        ttk.Label(tab_data, text=self.t("inventory.col.species"), style="Muted.TLabel").grid(row=2, column=0, sticky="w", padx=8, pady=(0, 2))
        species_combo = ttk.Combobox(tab_data, textvariable=self._inventory_form_vars["species"], values=[x.name for x in self.items], style="Nature.TCombobox")
        species_combo.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 6))
        species_combo.bind("<<ComboboxSelected>>", lambda _e: self._inventory_on_species_changed())

        ttk.Label(tab_data, text=self.t("inventory.col.gender"), style="Muted.TLabel").grid(row=4, column=0, sticky="w", padx=8, pady=(0, 2))
        gw = ttk.Frame(tab_data, style="Panel.TFrame")
        gw.grid(row=5, column=0, sticky="w", padx=8, pady=(0, 6))
        ttk.Radiobutton(gw, text="M", variable=self._inventory_form_vars["gender"], value="M").pack(side="left")
        ttk.Radiobutton(gw, text="F", variable=self._inventory_form_vars["gender"], value="F").pack(side="left", padx=(8, 0))
        ttk.Radiobutton(gw, text="U", variable=self._inventory_form_vars["gender"], value="U").pack(side="left", padx=(8, 0))

        ttk.Label(tab_data, text=self.t("left.nature"), style="Muted.TLabel").grid(row=6, column=0, sticky="w", padx=8, pady=(0, 2))
        ncombo = ttk.Combobox(tab_data, textvariable=self._inventory_form_vars["nature"], values=[""] + NATURE_OPTIONS, style="Nature.TCombobox")
        ncombo.grid(row=7, column=0, sticky="ew", padx=8, pady=(0, 6))
        ncombo.bind("<<ComboboxSelected>>", lambda _e: self._inventory_refresh_stats())

        ttk.Label(tab_data, text=self.t("inventory.level"), style="Muted.TLabel").grid(row=8, column=0, sticky="w", padx=8, pady=(0, 2))
        lvl = ttk.Entry(tab_data, textvariable=self._inventory_form_vars["level"])
        lvl.grid(row=9, column=0, sticky="ew", padx=8, pady=(0, 6))
        lvl.bind("<KeyRelease>", lambda _e: self._inventory_refresh_stats())

        ttk.Label(tab_data, text=self.t("inventory.col.ball"), style="Muted.TLabel").grid(row=10, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Entry(tab_data, textvariable=self._inventory_form_vars["ball"]).grid(row=11, column=0, sticky="ew", padx=8, pady=(0, 6))
        ttk.Label(tab_data, text=self.t("inventory.col.price"), style="Muted.TLabel").grid(row=12, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Entry(tab_data, textvariable=self._inventory_form_vars["price"]).grid(row=13, column=0, sticky="ew", padx=8, pady=(0, 6))
        ttk.Label(tab_data, text=self.t("inventory.col.egg_groups"), style="Muted.TLabel").grid(row=14, column=0, sticky="w", padx=8, pady=(0, 2))
        ttk.Label(tab_data, textvariable=self._inventory_form_vars["egg_groups"]).grid(row=15, column=0, sticky="w", padx=8, pady=(0, 6))
        ttk.Label(tab_data, text=self.t("inventory.col.notes"), style="Muted.TLabel").grid(row=16, column=0, sticky="w", padx=8, pady=(0, 2))
        notes_widget = tk.Text(tab_data, height=5, wrap="word", bg=self.theme["entry_bg"], fg=self.theme["fg"], insertbackground=self.theme["fg"], highlightthickness=1, highlightbackground=self.theme["border"])
        notes_widget.grid(row=18, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._inventory_form_vars["notes_widget"] = notes_widget

        ttk.Label(tab_ivs, text=self.t("inventory.iv_hint"), style="Muted.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 4))
        iv_rows = [("hp", "HP"), ("atk", "Atk"), ("def", "Def"), ("spa", "SpA"), ("spd", "SpD"), ("spe", "Spe")]
        for i, (k, lbl) in enumerate(iv_rows):
            ttk.Label(tab_ivs, text=lbl).grid(row=i + 1, column=0, sticky="w", padx=8, pady=4)
            sp = tk.Spinbox(tab_ivs, from_=0, to=31, textvariable=iv_vars[k], width=6, command=self._inventory_refresh_stats)
            sp.grid(row=i + 1, column=1, sticky="w", padx=4, pady=4)
            sp.bind("<KeyRelease>", lambda _e: self._inventory_refresh_stats())

        self._inventory_stats_vars = {k: tk.StringVar(value="0") for k in ("hp", "atk", "def", "spa", "spd", "spe", "total")}
        ttk.Label(tab_stats, text=self.t("inventory.stats_title"), style="Muted.TLabel").grid(row=0, column=0, sticky="w", padx=8, pady=(8, 6))
        for i, (k, lbl) in enumerate(iv_rows):
            ttk.Label(tab_stats, text=f"{lbl}:").grid(row=i + 1, column=0, sticky="w", padx=8, pady=3)
            ttk.Label(tab_stats, textvariable=self._inventory_stats_vars[k], style="Header.TLabel").grid(row=i + 1, column=1, sticky="w", padx=4, pady=3)
        ttk.Label(tab_stats, text=self.t("info.stats.total") + ":").grid(row=8, column=0, sticky="w", padx=8, pady=(8, 4))
        ttk.Label(tab_stats, textvariable=self._inventory_stats_vars["total"], style="Header.TLabel").grid(row=8, column=1, sticky="w", padx=4, pady=(8, 4))

        actions = ttk.Frame(right, style="Panel.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        ttk.Button(actions, text=self.t("inventory.btn.save"), command=self._inventory_save_current).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text=self.t("inventory.btn.duplicate"), command=self._inventory_duplicate_current).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text=self.t("inventory.btn.delete"), command=self._inventory_delete_current).pack(side="left")

        prices_box = ttk.Frame(right, style="Panel.TFrame")
        prices_box.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Label(prices_box, text=self.t("inventory.price_title"), style="Muted.TLabel").grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 6))
        self._inventory_price_vars = {}
        for i in range(1, 7):
            ttk.Label(prices_box, text=f"{i}x31").grid(row=i, column=0, sticky="w")
            var = tk.StringVar(value=str(self.inventory_settings.estimated_buy_price_by_iv_count.get(i, 0)))
            self._inventory_price_vars[i] = var
            ttk.Entry(prices_box, textvariable=var, width=10).grid(row=i, column=1, sticky="w", padx=(4, 10))
        self._inventory_default_level_var = tk.StringVar(value=str(self.inventory_settings.default_level))
        ttk.Label(prices_box, text=self.t("inventory.default_level"), style="Muted.TLabel").grid(row=7, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(prices_box, textvariable=self._inventory_default_level_var, width=10).grid(row=7, column=1, sticky="w", padx=(4, 10), pady=(6, 0))
        ttk.Button(prices_box, text=self.t("inventory.btn.save_prices"), command=self._inventory_save_prices_pc).grid(row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))

        self._inventory_sync_box_count()
        self._inventory_clear_editor()
        self._inventory_draw_box()

    def _inventory_sync_box_count(self):
        max_box = max([0] + [int(x.box_index or 0) for x in self.inventory_items])
        self.inventory_settings.boxes_count = max(1, max_box + 1)
        if self._inventory_box_index >= self.inventory_settings.boxes_count:
            self._inventory_box_index = self.inventory_settings.boxes_count - 1
        self._inventory_box_label_var.set(
            self.t(
                "inventory.box_label",
                current=(self._inventory_box_index + 1),
                total=self.inventory_settings.boxes_count,
            )
        )

    def _inventory_items_in_box(self, box_index: int) -> List[InventoryItem]:
        return sorted([x for x in self.inventory_items if int(x.box_index or 0) == int(box_index)], key=lambda x: int(x.slot_index if x.slot_index is not None else -1))

    def _inventory_slot_to_xy(self, slot: int) -> Tuple[int, int]:
        col = slot % self._inventory_cols
        row = slot // self._inventory_cols
        pad = 12
        return pad + col * self._inventory_slot_size, pad + row * self._inventory_slot_size

    def _inventory_xy_to_slot(self, x: float, y: float) -> Optional[int]:
        pad = 12
        rel_x = x - pad
        rel_y = y - pad
        if rel_x < 0 or rel_y < 0:
            return None
        col = int(rel_x // self._inventory_slot_size)
        row = int(rel_y // self._inventory_slot_size)
        if col < 0 or col >= self._inventory_cols or row < 0 or row >= self._inventory_rows:
            return None
        slot = row * self._inventory_cols + col
        return slot if 0 <= slot < self._inventory_slots_per_box else None

    def _inventory_get_item_by_id(self, item_id: str) -> Optional[InventoryItem]:
        return next((x for x in self.inventory_items if x.id == item_id), None)

    def _inventory_get_item_at_slot(self, box_index: int, slot_index: int) -> Optional[InventoryItem]:
        for it in self.inventory_items:
            if int(it.box_index or 0) == int(box_index) and int(it.slot_index) == int(slot_index):
                return it
        return None

    def _inventory_first_free_slot(self, box_index: int) -> int:
        occupied = {int(x.slot_index) for x in self.inventory_items if int(x.box_index or 0) == int(box_index) and int(x.slot_index) >= 0}
        for s in range(self._inventory_slots_per_box):
            if s not in occupied:
                return s
        return -1

    def _inventory_draw_box(self):
        c = self._inventory_canvas
        if c is None:
            return
        self._inventory_sync_box_count()
        c.delete("all")
        self._inventory_images.clear()
        width = 24 + self._inventory_cols * self._inventory_slot_size
        height = 24 + self._inventory_rows * self._inventory_slot_size
        c.configure(scrollregion=(0, 0, width, height))
        for slot in range(self._inventory_slots_per_box):
            x, y = self._inventory_slot_to_xy(slot)
            x1 = x + self._inventory_slot_size - 8
            y1 = y + self._inventory_slot_size - 8
            c.create_rectangle(x, y, x1, y1, outline=self.theme["border"], fill=self.theme["panel_alt"], tags=("slot", f"slot:{slot}"))

        for it in self._inventory_items_in_box(self._inventory_box_index):
            slot = int(it.slot_index)
            if slot < 0 or slot >= self._inventory_slots_per_box:
                continue
            x, y = self._inventory_slot_to_xy(slot)
            x1 = x + self._inventory_slot_size - 8
            y1 = y + self._inventory_slot_size - 8
            outline = self.theme["accent"] if it.id == self._inventory_selected_item_id else self.theme["border"]
            c.create_rectangle(x + 2, y + 2, x1 - 2, y1 - 2, outline=outline, width=2 if it.id == self._inventory_selected_item_id else 1, fill=self.theme["entry_bg"], tags=("inv_item", f"item:{it.id}", f"slot:{slot}"))
            photo = self._load_sprite_photo(int(it.species_id), (52, 52), allow_download=True) if it.species_id else None
            if photo is not None:
                self._inventory_images[it.id] = photo
                c.create_image((x + x1) // 2, y + 30, image=photo, tags=("inv_item", f"item:{it.id}", f"slot:{slot}"))
            else:
                c.create_text((x + x1) // 2, y + 30, text="?", fill=self.theme["fg"], font=(self._ui_font_family, 14, "bold"), tags=("inv_item", f"item:{it.id}", f"slot:{slot}"))
            c.create_text((x + x1) // 2, y1 - 26, text=(it.species_name or "?")[:10], fill=self.theme["fg"], font=(self._ui_font_family, 8, "bold"), tags=("inv_item", f"item:{it.id}", f"slot:{slot}"))
            c.create_text((x + x1) // 2, y1 - 12, text=f"{it.iv_count_31()}x31", fill=self.theme["muted"], font=(self._ui_font_family, 7), tags=("inv_item", f"item:{it.id}", f"slot:{slot}"))

    def _inventory_create_item_at_slot(self, slot: int):
        species = self.selected if self.selected else (self.items[0] if self.items else None)
        species_id = int(species.id) if species else None
        species_name = species.name if species else ""
        egg_groups = []
        if species_id:
            try:
                egg_groups = self.species_info.get_egg_groups(species_id)
            except Exception:
                egg_groups = []
        item = InventoryItem.create()
        item.species_id = species_id
        item.species_name = species_name
        item.gender = "U"
        item.nature = ""
        item.level = int(self.inventory_settings.default_level or 50)
        item.ivs = {k: 0 for k in STAT_KEYS}
        item.egg_groups = egg_groups
        item.ball = ""
        item.price_paid = 0
        item.notes = ""
        item.box_index = self._inventory_box_index
        item.slot_index = slot
        item.sprite_cache_key = str(species_id or "")
        self.inventory_items.append(item)
        self.inventory_store.save_items(self.inventory_items)
        self._inventory_selected_item_id = item.id
        self._inventory_load_editor(item)
        self._inventory_draw_box()
        if self.selected:
            self._request_recompute(reason="inventory")

    def _inventory_on_canvas_press(self, event):
        c = self._inventory_canvas
        if c is None:
            return
        slot = self._inventory_xy_to_slot(c.canvasx(event.x), c.canvasy(event.y))
        if slot is None:
            return
        item = self._inventory_get_item_at_slot(self._inventory_box_index, slot)
        if item is None:
            self._inventory_create_item_at_slot(slot)
            return
        self._inventory_selected_item_id = item.id
        self._inventory_load_editor(item)
        self._inventory_draw_box()
        self._inventory_drag = {
            "item_id": item.id,
            "source_slot": slot,
            "start_x": c.canvasx(event.x),
            "start_y": c.canvasy(event.y),
            "ghost": None,
            "moved": False,
        }

    def _inventory_on_canvas_motion(self, event):
        c = self._inventory_canvas
        if c is None:
            return
        drag = self._inventory_drag or {}
        if not drag.get("item_id"):
            return
        x = c.canvasx(event.x)
        y = c.canvasy(event.y)
        sx = float(drag.get("start_x", x))
        sy = float(drag.get("start_y", y))
        if abs(x - sx) + abs(y - sy) < 6:
            return
        drag["moved"] = True
        ghost = drag.get("ghost")
        if ghost is None:
            ghost = c.create_rectangle(
                x - 20, y - 20, x + 20, y + 20,
                outline=self.theme["accent"], width=2, dash=(3, 2), tags=("drag_ghost",)
            )
            drag["ghost"] = ghost
        else:
            c.coords(ghost, x - 20, y - 20, x + 20, y + 20)
        self._inventory_drag = drag

    def _inventory_on_canvas_release(self, event):
        c = self._inventory_canvas
        if c is None:
            return
        drag = self._inventory_drag or {}
        item_id = drag.get("item_id")
        if not item_id:
            self._inventory_drag = {}
            return
        ghost = drag.get("ghost")
        if ghost is not None:
            c.delete(ghost)
        moved = bool(drag.get("moved"))
        source_slot = int(drag.get("source_slot", -1))
        target_slot = self._inventory_xy_to_slot(c.canvasx(event.x), c.canvasy(event.y))

        if moved and target_slot is not None and source_slot >= 0 and target_slot != source_slot:
            src_item = self._inventory_get_item_by_id(item_id)
            dst_item = self._inventory_get_item_at_slot(self._inventory_box_index, target_slot)
            if src_item is not None:
                src_item.slot_index = target_slot
                src_item.box_index = self._inventory_box_index
                if dst_item is not None and dst_item.id != src_item.id:
                    dst_item.slot_index = source_slot
                    dst_item.box_index = self._inventory_box_index
                self.inventory_store.save_items(self.inventory_items)
                if self.selected:
                    self._request_recompute(reason="inventory")
        self._inventory_drag = {}
        self._inventory_draw_box()

    def _inventory_species_id_from_name(self, species_name: str) -> Optional[int]:
        name = (species_name or "").strip().lower()
        if not name:
            return None
        for p in self.items:
            if p.name.lower() == name:
                return int(p.id)
        return None

    def _inventory_on_species_changed(self):
        fv = self._inventory_form_vars
        species_name = str(fv["species"].get() or "").strip().lower()
        pid = self._inventory_species_id_from_name(species_name)
        fv["species_id_label"].set(f"#{pid}" if pid else "—")
        egg_groups = []
        if pid:
            try:
                egg_groups = self.species_info.get_egg_groups(pid)
            except Exception:
                egg_groups = []
        fv["egg_groups"].set(", ".join(egg_groups) if egg_groups else "—")
        self._inventory_update_detail_sprite(pid)
        self._inventory_refresh_stats()

    def _inventory_update_detail_sprite(self, species_id: Optional[int]):
        lbl = getattr(self, "_inventory_detail_sprite_label", None)
        if lbl is None:
            return
        photo = self._load_sprite_photo(
            int(species_id),
            (96, 96),
            allow_download=True,
            compose_bg=self.theme["panel"],
        ) if species_id else None
        self._inventory_detail_img = photo
        if photo is not None:
            lbl.configure(image=photo)
        else:
            lbl.configure(image="")

    def _inventory_load_editor(self, item: InventoryItem):
        fv = self._inventory_form_vars
        fv["id"].set(item.id)
        fv["species"].set(item.species_name or "")
        fv["species_id_label"].set(f"#{int(item.species_id)}" if item.species_id else "—")
        fv["gender"].set(item.gender if item.gender in ("M", "F", "U") else "U")
        fv["nature"].set(item.nature or "")
        fv["level"].set(str(item.level or self.inventory_settings.default_level))
        fv["ball"].set(item.ball or "")
        fv["price"].set(str(int(item.price_paid or 0)))
        fv["egg_groups"].set(", ".join(item.egg_groups or []) if item.egg_groups else "—")
        iv_vars = fv.get("ivs", {})
        for k in STAT_KEYS:
            if k in iv_vars:
                iv_vars[k].set(int(item.ivs.get(k, 0)))
        notes_widget = fv.get("notes_widget")
        if notes_widget is not None:
            notes_widget.delete("1.0", tk.END)
            notes_widget.insert(tk.END, item.notes or "")
        self._inventory_update_detail_sprite(item.species_id)
        self._inventory_refresh_stats()

    def _inventory_clear_editor(self):
        fv = self._inventory_form_vars
        if not fv:
            return
        fv["id"].set("")
        fv["species"].set("")
        fv["species_id_label"].set("—")
        fv["gender"].set("U")
        fv["nature"].set("")
        fv["level"].set(str(int(self.inventory_settings.default_level or 50)))
        fv["ball"].set("")
        fv["price"].set("0")
        fv["egg_groups"].set("—")
        iv_vars = fv.get("ivs", {})
        for k in STAT_KEYS:
            if k in iv_vars:
                iv_vars[k].set(0)
        notes_widget = fv.get("notes_widget")
        if notes_widget is not None:
            notes_widget.delete("1.0", tk.END)
        self._inventory_update_detail_sprite(None)
        for k in ("hp", "atk", "def", "spa", "spd", "spe", "total"):
            if k in self._inventory_stats_vars:
                self._inventory_stats_vars[k].set("0")

    def _inventory_collect_form_item(self) -> Optional[InventoryItem]:
        fv = self._inventory_form_vars
        raw_id = str(fv["id"].get() or "").strip()
        species_name = str(fv["species"].get() or "").strip().lower()
        species_id = self._inventory_species_id_from_name(species_name)
        try:
            level = max(1, min(100, int(str(fv["level"].get() or "50").strip())))
        except Exception:
            level = int(self.inventory_settings.default_level or 50)
        try:
            price_paid = max(0, int(str(fv["price"].get() or "0").strip()))
        except Exception:
            price_paid = 0

        iv_values: Dict[str, int] = {k: 0 for k in STAT_KEYS}
        iv_vars = fv.get("ivs", {})
        for k in STAT_KEYS:
            try:
                iv_values[k] = max(0, min(31, int(iv_vars[k].get())))
            except Exception:
                iv_values[k] = 0

        item = self._inventory_get_item_by_id(raw_id) if raw_id else None
        if item is None:
            item = InventoryItem.create()
            item.box_index = self._inventory_box_index
            item.slot_index = self._inventory_first_free_slot(self._inventory_box_index)
            if item.slot_index < 0:
                self.inventory_settings.boxes_count += 1
                self._inventory_box_index = self.inventory_settings.boxes_count - 1
                item.box_index = self._inventory_box_index
                item.slot_index = 0

        item.species_id = species_id
        item.species_name = species_name
        item.gender = str(fv["gender"].get() or "U")
        if item.gender not in ("M", "F", "U"):
            item.gender = "U"
        item.nature = str(fv["nature"].get() or "")
        item.level = level
        item.ivs = iv_values
        item.ball = str(fv["ball"].get() or "")
        item.price_paid = price_paid
        notes_widget = fv.get("notes_widget")
        if notes_widget is not None:
            item.notes = str(notes_widget.get("1.0", tk.END)).strip()
        item.sprite_cache_key = str(item.species_id or "")
        if item.species_id:
            try:
                item.egg_groups = self.species_info.get_egg_groups(item.species_id)
            except Exception:
                item.egg_groups = []
        else:
            item.egg_groups = []
        return item

    def _inventory_refresh_stats(self):
        fv = self._inventory_form_vars
        species_name = str(fv.get("species", tk.StringVar(value="")).get() or "").strip().lower()
        species_id = self._inventory_species_id_from_name(species_name)
        base = {k: 0 for k in STAT_KEYS}
        if species_id:
            try:
                details = self.species_info.get_pokemon_details(species_id, version_group="black-white", language=self._lang)
                for s in details.get("stats", []) or []:
                    rk = normalize_stat_key(s.get("raw", ""))
                    if rk:
                        base[rk] = int(s.get("value", 0) or 0)
                egg_groups = tuple(details.get("summary", {}).get("egg_groups", []) or [])
                fv["egg_groups"].set(", ".join(egg_groups) if egg_groups else "—")
            except Exception:
                pass

        iv_vars = fv.get("ivs", {})
        ivs = {}
        for k in STAT_KEYS:
            try:
                ivs[k] = max(0, min(31, int(iv_vars[k].get())))
            except Exception:
                ivs[k] = 0
        try:
            level = max(1, min(100, int(str(fv["level"].get() or "50").strip())))
        except Exception:
            level = int(self.inventory_settings.default_level or 50)
        stats = calculate_stats(base_stats=base, ivs=ivs, level=level, nature_text=str(fv["nature"].get() or ""))
        for k in ("hp", "atk", "def", "spa", "spd", "spe", "total"):
            if k in self._inventory_stats_vars:
                self._inventory_stats_vars[k].set(str(int(stats.get(k, 0))))

    def _inventory_save_current(self):
        item = self._inventory_collect_form_item()
        if item is None:
            return
        idx = next((i for i, x in enumerate(self.inventory_items) if x.id == item.id), None)
        if idx is None:
            self.inventory_items.append(item)
        else:
            self.inventory_items[idx] = item
        self.inventory_store.save_items(self.inventory_items)
        self._inventory_selected_item_id = item.id
        self._inventory_draw_box()
        if self.selected:
            self._request_recompute(reason="inventory")

    def _inventory_duplicate_current(self):
        item = self._inventory_get_item_by_id(self._inventory_selected_item_id or "")
        if item is None:
            return
        slot = self._inventory_first_free_slot(self._inventory_box_index)
        if slot < 0:
            self.inventory_settings.boxes_count += 1
            self._inventory_box_index = self.inventory_settings.boxes_count - 1
            slot = 0
        new_item = InventoryItem.create()
        new_item.species_id = item.species_id
        new_item.species_name = item.species_name
        new_item.gender = item.gender
        new_item.nature = item.nature
        new_item.level = item.level
        new_item.ivs = dict(item.ivs)
        new_item.egg_groups = list(item.egg_groups)
        new_item.ball = item.ball
        new_item.price_paid = item.price_paid
        new_item.notes = item.notes
        new_item.box_index = self._inventory_box_index
        new_item.slot_index = slot
        new_item.sprite_cache_key = item.sprite_cache_key
        self.inventory_items.append(new_item)
        self.inventory_store.save_items(self.inventory_items)
        self._inventory_selected_item_id = new_item.id
        self._inventory_load_editor(new_item)
        self._inventory_draw_box()
        if self.selected:
            self._request_recompute(reason="inventory")

    def _inventory_delete_current(self):
        item_id = self._inventory_selected_item_id
        if not item_id:
            return
        self.inventory_items = [x for x in self.inventory_items if x.id != item_id]
        self.inventory_store.save_items(self.inventory_items)
        self._inventory_selected_item_id = None
        self._inventory_clear_editor()
        self._inventory_draw_box()
        if self.selected:
            self._request_recompute(reason="inventory")

    def _inventory_prev_box(self):
        self._inventory_sync_box_count()
        self._inventory_box_index = max(0, self._inventory_box_index - 1)
        self._inventory_draw_box()

    def _inventory_next_box(self):
        self._inventory_sync_box_count()
        if self._inventory_box_index + 1 >= self.inventory_settings.boxes_count:
            self.inventory_settings.boxes_count += 1
        self._inventory_box_index = min(self.inventory_settings.boxes_count - 1, self._inventory_box_index + 1)
        self._inventory_draw_box()

    def _inventory_import_pc(self):
        path = filedialog.askopenfilename(
            parent=self._inventory_window,
            title=self.t("inventory.import_title"),
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            self.inventory_items = self.inventory_store.import_items(path)
            self._inventory_selected_item_id = None
            self._inventory_clear_editor()
            self._inventory_draw_box()
            if self.selected:
                self._request_recompute(reason="inventory")
        except Exception as exc:
            messagebox.showerror(self.t("dialog.error"), str(exc))

    def _inventory_export_pc(self):
        path = filedialog.asksaveasfilename(
            parent=self._inventory_window,
            title=self.t("inventory.export_title"),
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            self.inventory_store.export_items(path, self.inventory_items)
        except Exception as exc:
            messagebox.showerror(self.t("dialog.error"), str(exc))

    def _inventory_save_prices_pc(self):
        for k, var in self._inventory_price_vars.items():
            try:
                v = int(var.get().strip() or 0)
            except Exception:
                v = 0
            self.inventory_settings.estimated_buy_price_by_iv_count[k] = max(0, v)
        try:
            dlevel = int(str(self._inventory_default_level_var.get()).strip())
        except Exception:
            dlevel = 50
        self.inventory_settings.default_level = max(1, min(100, dlevel))
        self.inventory_store.save_settings(self.inventory_settings)
        if self.selected:
            self._request_recompute(reason="inventory-prices")

    def _load_species_meta_async(self, pid: int, pname: str, selection_gen: Optional[int] = None):
        def task():
            egg_groups = []
            types = []
            try:
                egg_groups = self.species_info.get_egg_groups(pid)
            except Exception as exc:
                print(f"[SpeciesInfoService] Failed egg groups for #{pid}: {exc}")
            try:
                types = self.species_info.get_types(pid)
            except Exception as exc:
                print(f"[SpeciesInfoService] Failed types for #{pid}: {exc}")

            def apply():
                if selection_gen is not None and selection_gen != self._selection_generation_id:
                    return
                if not self.selected or self.selected.id != pid:
                    return
                type_txt = "/".join(self._localize_type_name(t) for t in types) if types else "?"
                self._name_type_text_var.set(f"{pname} (#{pid}) [{type_txt}]")
                self._egg_groups_var.set(self.t("left.egg_groups", groups=(", ".join(egg_groups) if egg_groups else "—")))
                color = TYPE_COLORS.get(types[0], "#666") if types else "#666"
                self.type_dot.itemconfig(self.type_dot_id, fill=color, outline=color)
            self.after(0, apply)
        threading.Thread(target=task, daemon=True).start()

    def _open_pokemon_info_window(self):
        if not self.selected:
            return

        if not self._info_window or not self._info_window.winfo_exists():
            self._build_info_window_shell()

        pid = self.selected.id
        pname = self.selected.name.title()
        self._info_species_id = pid
        self._info_details = None
        self._info_images = []
        self._info_header_var.set(f"N. {pid:03d} {pname}")
        self._set_info_loading(self.t("info.loading"))
        self._switch_info_tab(self._info_active_tab or "datos")
        self._apply_info_window_theme()
        self._load_info_async(pid)
        if self._info_window and self._info_window.winfo_exists():
            self._info_window.lift()
            self._info_window.focus_set()

    def _build_info_window_shell(self):
        win = tk.Toplevel(self)
        win.title(self.t("info.window_title"))
        win.geometry("980x680")
        win.minsize(760, 520)
        win.protocol("WM_DELETE_WINDOW", self._close_info_window)
        self._info_window = win

        root = tk.Frame(win, bg=self.theme["panel"], highlightthickness=1, highlightbackground=self.theme["border"])
        root.pack(fill="both", expand=True, padx=8, pady=8)
        self._info_root_frame = root

        header = tk.Frame(root, bg=self.theme["panel_alt"], height=40)
        header.pack(fill="x")
        header.pack_propagate(False)
        self._info_header_frame = header

        title_lbl = tk.Label(
            header,
            textvariable=self._info_header_var,
            bg=self.theme["panel_alt"],
            fg=self.theme["fg"],
            font=(self._ui_font_family, 13, "bold"),
            anchor="w",
        )
        title_lbl.pack(side="left", padx=10, pady=6)
        self._info_title_label = title_lbl

        close_btn = tk.Button(
            header,
            text="X",
            command=self._close_info_window,
            cursor="hand2",
            relief="flat",
            bd=0,
            padx=10,
            pady=3,
            font=(self._ui_font_family, 10, "bold"),
        )
        close_btn.pack(side="right", padx=8, pady=6)
        self._info_close_btn = close_btn

        tabbar = tk.Frame(root, bg=self.theme["panel"])
        tabbar.pack(fill="x", pady=(6, 4))
        self._info_tabbar_frame = tabbar

        tab_defs = self._get_info_tab_defs()
        self._info_tab_labels = {k: label for k, label in tab_defs}
        self._info_tab_buttons = {}
        for key, label in tab_defs:
            btn = tk.Button(
                tabbar,
                text=label,
                relief="flat",
                bd=0,
                padx=16,
                pady=8,
                cursor="hand2",
                font=(self._ui_font_family, 10, "bold"),
                command=lambda k=key: self._switch_info_tab(k),
            )
            btn.pack(side="left", padx=(0, 4))
            self._info_tab_buttons[key] = btn

        content = tk.Frame(root, bg=self.theme["panel"])
        content.pack(fill="both", expand=True, pady=(0, 6))
        self._info_content_frame = content

        self._info_tab_frames = {}
        self._info_tab_rendered = {}
        for key, _ in tab_defs:
            frame = tk.Frame(content, bg=self.theme["panel"], highlightthickness=1, highlightbackground=self.theme["border"])
            self._info_tab_frames[key] = frame
            self._info_tab_rendered[key] = False

        status = tk.Label(
            root,
            textvariable=self._info_status_var,
            anchor="w",
            bg=self.theme["panel_alt"],
            fg=self.theme["muted"],
            font=(self._ui_font_family, 9),
            padx=8,
            pady=5,
        )
        status.pack(fill="x")
        self._info_status_label = status

        self._info_active_tab = "datos"
        self._switch_info_tab("datos")
        self._set_info_loading(self.t("info.select_prompt"))
        self._apply_info_window_theme()

    def _get_info_tab_defs(self) -> List[Tuple[str, str]]:
        return [
            ("datos", self.t("info.tab.data")),
            ("movimientos", self.t("info.tab.moves")),
            ("stats", self.t("info.tab.stats")),
            ("sitios", self.t("info.tab.sites")),
            ("evoluciones", self.t("info.tab.evolutions")),
        ]

    def _build_info_window_texts(self):
        if not self._info_window or not self._info_window.winfo_exists():
            return
        self._info_window.title(self.t("info.window_title"))
        tab_defs = self._get_info_tab_defs()
        self._info_tab_labels = {k: label for k, label in tab_defs}
        for key, btn in self._info_tab_buttons.items():
            if key in self._info_tab_labels:
                btn.configure(text=self._info_tab_labels[key], font=(self._ui_font_family, 10, "bold"))

    def _load_info_async(self, pid: int):
        lang_snapshot = self._lang
        def task():
            try:
                details = self.species_info.get_pokemon_details(pid, version_group="black-white", language=lang_snapshot)
                self.after(0, lambda: self._populate_pokemon_info(pid, details))
            except Exception as exc:
                self.after(0, lambda: self._populate_pokemon_info_error(pid, exc))
        threading.Thread(target=task, daemon=True).start()

    def _set_info_loading(self, message: str):
        self._info_status_var.set(message)
        self._info_moves_rows = []
        self._info_moves_by_bucket = {}
        self._info_move_section_trees = {}
        self._info_sites_tree = None
        self._info_images = []
        for k in list(self._info_tab_rendered.keys()):
            self._info_tab_rendered[k] = False
        for frame in self._info_tab_frames.values():
            self._clear_info_tab(frame)
            lbl = tk.Label(
                frame,
                text=message,
                bg=self.theme["panel"],
                fg=self.theme["muted"],
                font=(self._ui_font_family, 11),
            )
            lbl.pack(expand=True)
            self._info_loading_label = lbl

    @staticmethod
    def _clear_info_tab(frame: tk.Frame):
        for w in frame.winfo_children():
            w.destroy()

    def _switch_info_tab(self, tab_key: str):
        if tab_key not in self._info_tab_frames:
            tab_key = "datos"
        for frame in self._info_tab_frames.values():
            frame.pack_forget()
        current = self._info_tab_frames[tab_key]
        current.pack(fill="both", expand=True)
        self._info_active_tab = tab_key
        self._refresh_info_tab_buttons()
        self._render_info_tab_if_needed(tab_key)

    def _render_info_tab_if_needed(self, tab_key: str):
        if not self._info_details:
            return
        if self._info_tab_rendered.get(tab_key):
            return
        frame = self._info_tab_frames.get(tab_key)
        if frame is None:
            return
        if tab_key == "datos":
            self._render_info_tab_datos(frame, self._info_details)
        elif tab_key == "movimientos":
            self._render_info_tab_moves(frame, self._info_details)
        elif tab_key == "stats":
            self._render_info_tab_stats(frame, self._info_details)
        elif tab_key == "sitios":
            self._render_info_tab_sites(frame, self._info_details)
        elif tab_key == "evoluciones":
            self._render_info_tab_evolutions(frame, self._info_details)
        self._info_tab_rendered[tab_key] = True

    def _refresh_info_tab_buttons(self):
        for key, btn in self._info_tab_buttons.items():
            active = key == self._info_active_tab
            btn.configure(
                bg=self.theme["info_tab_active_bg"] if active else self.theme["info_tab_bg"],
                fg=self.theme["info_tab_fg"],
                activebackground=self.theme["info_tab_active_bg"] if active else self.theme["panel_alt"],
                activeforeground=self.theme["fg"],
                highlightthickness=1,
                highlightbackground=self.theme["border"],
                font=(self._ui_font_family, 10, "bold"),
            )

    def _close_info_window(self):
        if self._info_window and self._info_window.winfo_exists():
            self._info_window.destroy()
        self._info_window = None
        self._info_species_id = None
        self._info_details = None
        self._info_moves_rows = []
        self._info_moves_by_bucket = {}
        self._info_move_section_trees = {}
        self._info_sites_tree = None
        self._info_images = []
        self._info_tab_frames = {}
        self._info_tab_buttons = {}
        self._info_tab_rendered = {}
        self._info_content_frame = None
        self._info_status_label = None

    def _populate_pokemon_info_error(self, pid: int, exc: Exception):
        if not self._info_window or not self._info_window.winfo_exists():
            return
        if self._info_species_id != pid:
            return
        self._set_info_loading(self.t("info.load_error", err=str(exc)))

    def _populate_pokemon_info(self, pid: int, details: dict):
        if not self._info_window or not self._info_window.winfo_exists():
            return
        if self._info_species_id != pid:
            return
        self._info_details = details
        summary = details.get("summary", {})
        sid = summary.get("id", pid)
        name = summary.get("name", details.get("name", "—"))
        try:
            sid_txt = f"{int(sid):03d}"
        except Exception:
            sid_txt = str(sid)
        self._info_header_var.set(f"N. {sid_txt} {name}")
        for k in list(self._info_tab_rendered.keys()):
            self._info_tab_rendered[k] = False
        fallback_used = bool(summary.get("sites_fallback_used"))
        if fallback_used:
            self._info_status_var.set(self.t("info.loaded_fallback"))
        else:
            self._info_status_var.set(self.t("info.loaded"))
        self._switch_info_tab(self._info_active_tab or "datos")

    def _compose_sprite_on_bg(self, img: Image.Image, size: Tuple[int, int], bg_hex: Optional[str] = None) -> Image.Image:
        sprite = img.convert("RGBA").resize(size, Image.NEAREST)
        if not bg_hex:
            return sprite
        try:
            r, g, b = self.theme_manager._hex_to_rgb(bg_hex)
        except Exception:
            r, g, b = (24, 28, 34)
        base = Image.new("RGBA", size, (r, g, b, 255))
        base.alpha_composite(sprite)
        return base

    def _load_sprite_photo(
        self,
        species_id: int,
        size: Tuple[int, int],
        allow_download: bool = True,
        compose_bg: Optional[str] = None,
    ) -> Optional[ImageTk.PhotoImage]:
        path = os.path.join(SPRITE_CACHE_DIR, f"{species_id}.png")
        if not os.path.exists(path):
            path = self.sprites.get_sprite_path(species_id) if allow_download else self.sprites.get_default_path()
        try:
            img = Image.open(path)
            img = self._compose_sprite_on_bg(img, size, bg_hex=compose_bg)
            photo = ImageTk.PhotoImage(img)
            self._info_images.append(photo)
            return photo
        except Exception as exc:
            print(f"[Info] failed loading sprite #{species_id} at {path}: {exc}")
            return None

    def _get_type_icon_photo(self, type_key: str, size: Tuple[int, int] = (42, 18)) -> Optional[ImageTk.PhotoImage]:
        if not type_key:
            return None
        photo = self.type_icons.get_icon(type_key, size=size)
        if photo is not None:
            self._info_images.append(photo)
        return photo

    def _render_info_tab_datos(self, frame: tk.Frame, details: dict):
        self._clear_info_tab(frame)
        summary = details.get("summary", {})
        pid = summary.get("id", details.get("id", 0))

        left = tk.Frame(frame, bg=self.theme["panel_alt"], highlightthickness=1, highlightbackground=self.theme["border"])
        left.pack(side="left", fill="y", padx=12, pady=12)
        right = tk.Frame(frame, bg=self.theme["panel"], highlightthickness=1, highlightbackground=self.theme["border"])
        right.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)
        try:
            pid_num = int(pid)
            pid_label = f"{pid_num:03d}"
        except Exception:
            pid_num = 0
            pid_label = str(pid)

        tk.Label(
            left,
            text=f"N. {pid_label} {summary.get('name', details.get('name', '—'))}",
            bg=self.theme["panel_alt"],
            fg=self.theme["fg"],
            font=(self._ui_font_family, 11, "bold"),
            pady=8,
        ).pack(fill="x")

        sprite = self._load_sprite_photo(
            pid_num,
            (112, 112),
            allow_download=True,
            compose_bg=self.theme["panel_alt"],
        ) if pid_num > 0 else None
        sprite_box = tk.Label(left, image=sprite, bg=self.theme["panel_alt"])
        sprite_box.pack(padx=18, pady=(6, 10))

        types_wrap = tk.Frame(left, bg=self.theme["panel_alt"])
        types_wrap.pack(fill="x", padx=10, pady=(0, 8))
        for t in summary.get("types", []) or []:
            pill = tk.Label(
                types_wrap,
                text=self._localize_type_name(t),
                bg=TYPE_COLORS.get(t, self.theme["accent"]),
                fg="#101014",
                padx=8,
                pady=2,
                font=(self._ui_font_family, 9, "bold"),
            )
            pill.pack(side="left", padx=(0, 6), pady=2)

        table = tk.Frame(right, bg=self.theme["panel"])
        table.pack(fill="both", expand=True, padx=8, pady=8)
        h_m = summary.get("height_m", 0.0)
        w_kg = summary.get("weight_kg", 0.0)
        try:
            h_txt = f"{float(h_m):.1f} m"
        except Exception:
            h_txt = "—"
        try:
            w_txt = f"{float(w_kg):.1f} kg"
        except Exception:
            w_txt = "—"
        rows = [
            (self.t("info.data.type"), "/".join([self._localize_type_name(t) for t in (summary.get("types", []) or [])]) or "—"),
            (self.t("info.data.desc"), summary.get("flavor_text", "—")),
            (self.t("info.data.height"), h_txt),
            (self.t("info.data.weight"), w_txt),
            (self.t("info.data.abilities"), summary.get("abilities", "—")),
            (self.t("info.data.hidden_ability"), summary.get("hidden_ability", "—")),
            (self.t("info.data.egg_group"), ", ".join(summary.get("egg_groups", [])) or "—"),
            (self.t("info.data.ev_yield"), summary.get("ev_yield", "—")),
            (self.t("info.data.capture"), str(summary.get("capture_rate", "—"))),
        ]
        for i, (label, value) in enumerate(rows):
            row_bg = self.theme["info_table_row_bg"] if i % 2 == 0 else self.theme["info_table_row_alt_bg"]
            row = tk.Frame(table, bg=row_bg, highlightthickness=1, highlightbackground=self.theme["border"])
            row.pack(fill="x", pady=1)
            tk.Label(
                row,
                text=label,
                width=16,
                anchor="w",
                bg=row_bg,
                fg=self.theme["fg"],
                padx=8,
                pady=6,
                font=(self._ui_font_family, 10, "bold"),
            ).pack(side="left")
            tk.Label(
                row,
                text=value if value else "—",
                anchor="w",
                justify="left",
                wraplength=560,
                bg=row_bg,
                fg=self.theme["fg"],
                padx=8,
                pady=6,
                font=(self._ui_font_family, 10),
            ).pack(side="left", fill="x", expand=True)

    def _render_info_tab_moves(self, frame: tk.Frame, details: dict):
        self._clear_info_tab(frame)
        self._info_moves_rows = list(details.get("moves", []) or [])
        self._info_moves_by_bucket = self._bucketize_info_moves(self._info_moves_rows)
        self._info_move_section_trees = {}
        self._build_moves_sections_ui(frame)

    def _bucketize_info_moves(self, rows: List[dict]) -> Dict[str, List[dict]]:
        buckets: Dict[str, List[dict]] = {"level": [], "egg": [], "tm": [], "hm": []}
        for r in rows:
            bucket = (r.get("learn_bucket", "") or "").strip().lower()
            if bucket in buckets:
                buckets[bucket].append(r)
        buckets["level"].sort(key=lambda r: (int(r.get("level", 0) or 0), r.get("name", "")))
        buckets["egg"].sort(key=lambda r: r.get("name", ""))
        buckets["tm"].sort(key=lambda r: r.get("name", ""))
        buckets["hm"].sort(key=lambda r: r.get("name", ""))
        return buckets

    def _build_moves_sections_ui(self, frame: tk.Frame):
        wrap = tk.Frame(frame, bg=self.theme["panel"])
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        canvas = tk.Canvas(
            wrap,
            bg=self.theme["panel"],
            highlightthickness=1,
            highlightbackground=self.theme["border"],
        )
        canvas.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(wrap, orient="vertical", command=canvas.yview)
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=canvas.xview)
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        canvas.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        inner = tk.Frame(canvas, bg=self.theme["panel"])
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync(_event=None):
            canvas.itemconfig(win_id, width=canvas.winfo_width())
            canvas.configure(scrollregion=canvas.bbox("all"))

        inner.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)

        sections = [
            ("level", self.t("info.moves.section.level"), self.t("info.moves.col.level")),
            ("egg", self.t("info.moves.section.egg"), self.t("info.moves.col.source")),
            ("tm", self.t("info.moves.section.tm"), self.t("info.moves.col.source")),
            ("hm", self.t("info.moves.section.hm"), self.t("info.moves.col.source")),
        ]
        for idx, (bucket, title, level_col) in enumerate(sections):
            rows = self._info_moves_by_bucket.get(bucket, [])
            section = tk.Frame(
                inner,
                bg=self.theme["panel_alt"] if idx % 2 else self.theme["panel"],
                highlightthickness=1,
                highlightbackground=self.theme["border"],
            )
            section.pack(fill="x", pady=(0, 10))
            tk.Label(
                section,
                text=title,
                bg=self.theme["info_table_header_bg"],
                fg=self.theme["fg"],
                anchor="w",
                padx=10,
                pady=6,
                font=(self._ui_font_family, 10, "bold"),
            ).pack(fill="x")
            table_wrap = tk.Frame(section, bg=section["bg"])
            table_wrap.pack(fill="both", expand=True, padx=8, pady=8)
            cols = ("level", "name", "type", "power", "pp", "accuracy")
            tree = ttk.Treeview(table_wrap, columns=cols, show="tree headings", style="Info.Treeview", height=max(3, min(8, len(rows) + 1)))
            tree.heading("#0", text="", anchor="center")
            tree.heading("level", text=level_col)
            tree.heading("name", text=self.t("info.moves.col.name"))
            tree.heading("type", text=self.t("info.moves.col.type"))
            tree.heading("power", text=self.t("info.moves.col.power"))
            tree.heading("pp", text="PP")
            tree.heading("accuracy", text=self.t("info.moves.col.accuracy"))
            tree.column("#0", width=52, minwidth=42, anchor="center", stretch=False)
            tree.column("level", width=88, minwidth=72, anchor="center", stretch=False)
            tree.column("name", width=250, minwidth=180, anchor="w")
            tree.column("type", width=120, minwidth=90, anchor="w", stretch=False)
            tree.column("power", width=80, minwidth=60, anchor="center", stretch=False)
            tree.column("pp", width=80, minwidth=60, anchor="center", stretch=False)
            tree.column("accuracy", width=90, minwidth=70, anchor="center", stretch=False)
            tree.grid(row=0, column=0, sticky="nsew")
            sv = ttk.Scrollbar(table_wrap, orient="vertical", command=tree.yview)
            sh = ttk.Scrollbar(table_wrap, orient="horizontal", command=tree.xview)
            sv.grid(row=0, column=1, sticky="ns")
            sh.grid(row=1, column=0, sticky="ew")
            table_wrap.rowconfigure(0, weight=1)
            table_wrap.columnconfigure(0, weight=1)
            tree.configure(yscrollcommand=sv.set, xscrollcommand=sh.set)
            self._info_move_section_trees[bucket] = tree
            self._populate_moves_section(bucket)

    def _populate_moves_section(self, bucket: str):
        tree = self._info_move_section_trees.get(bucket)
        if tree is None:
            return
        tree.delete(*tree.get_children())
        tree.tag_configure("odd", background=self.theme["info_table_row_alt_bg"], foreground=self.theme["fg"])
        tree.tag_configure("even", background=self.theme["info_table_row_bg"], foreground=self.theme["fg"])
        rows = self._info_moves_by_bucket.get(bucket, []) or []
        image_refs: List[ImageTk.PhotoImage] = []
        if not rows:
            tree.insert("", "end", text="", values=("—", self.t("info.moves.empty"), "—", "—", "—", "—"), tags=("even",))
            tree._img_refs = image_refs  # type: ignore[attr-defined]
            return

        for i, row in enumerate(rows):
            if bucket == "level":
                lvl_txt = self.t("info.moves.level_fmt", level=int(row.get('level', 0) or 0))
            elif bucket == "egg":
                lvl_txt = self.t("info.moves.bucket.egg")
            elif bucket == "tm":
                lvl_txt = self.t("info.moves.bucket.tm")
            elif bucket == "hm":
                lvl_txt = self.t("info.moves.bucket.hm")
            else:
                lvl_txt = row.get("method_level", "—")
            icon = self._get_type_icon_photo(row.get("type_icon_key", ""), size=(40, 16))
            if icon is not None:
                image_refs.append(icon)
            vals = (
                lvl_txt,
                row.get("name", "—"),
                self._localize_type_name(row.get("raw_type", row.get("type", ""))),
                row.get("power", "—"),
                row.get("pp", "—"),
                row.get("accuracy", "—"),
            )
            tree.insert("", "end", text="", image=icon, values=vals, tags=("odd" if i % 2 else "even",))
        tree._img_refs = image_refs  # type: ignore[attr-defined]

    def _render_info_tab_stats(self, frame: tk.Frame, details: dict):
        self._clear_info_tab(frame)
        stats = details.get("stats", []) or []
        wrap = tk.Frame(frame, bg=self.theme["panel"])
        wrap.pack(fill="both", expand=True, padx=12, pady=12)

        total = sum(int(s.get("value", 0) or 0) for s in stats)
        rows = list(stats) + [{"name": self.t("info.stats.total"), "value": total}]
        for s in rows:
            name = s.get("name", "—")
            val = int(s.get("value", 0) or 0)
            row = tk.Frame(wrap, bg=self.theme["info_table_row_bg"], highlightthickness=1, highlightbackground=self.theme["border"])
            row.pack(fill="x", pady=3)
            tk.Label(
                row,
                text=f"{name}:",
                width=14,
                anchor="w",
                bg=self.theme["info_table_row_bg"],
                fg=self.theme["fg"],
                font=(self._ui_font_family, 10, "bold"),
                padx=8,
                pady=7,
            ).pack(side="left")
            tk.Label(
                row,
                text=str(val),
                width=6,
                anchor="center",
                bg=self.theme["info_table_row_bg"],
                fg=self.theme["fg"],
                font=(self._ui_font_family, 10, "bold"),
                pady=7,
            ).pack(side="left", padx=(0, 8))
            bar = tk.Canvas(
                row,
                width=360,
                height=18,
                bg=self.theme["info_table_row_bg"],
                highlightthickness=0,
            )
            bar.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=6)
            bar.create_rectangle(0, 2, 355, 16, fill=self.theme["info_bar_bg"], outline=self.theme["border"])
            ratio = max(0.0, min(1.0, val / 255.0))
            fill_w = int(352 * ratio)
            fill_color = IV_COLORS.get(name, "#D8D8D8")
            bar.create_rectangle(2, 4, 2 + fill_w, 14, fill=fill_color, outline="")

    def _render_info_tab_sites(self, frame: tk.Frame, details: dict):
        self._clear_info_tab(frame)
        rows = details.get("encounters", []) or []
        summary = details.get("summary", {}) or {}
        if not rows:
            tk.Label(
                frame,
                text=self.t("info.sites.empty"),
                bg=self.theme["panel"],
                fg=self.theme["muted"],
                font=(self._ui_font_family, 11),
            ).pack(expand=True, pady=24)
            return

        wrap = tk.Frame(frame, bg=self.theme["panel"])
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        if summary.get("sites_fallback_used"):
            tk.Label(
                wrap,
                text=self.t("info.sites.fallback"),
                bg=self.theme["panel"],
                fg=self.theme["muted"],
                anchor="w",
                font=(self._ui_font_family, 9, "bold"),
            ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
            start_row = 1
        else:
            start_row = 0

        cols = ("method", "region", "version", "location", "levels", "chance")
        tree = ttk.Treeview(wrap, columns=cols, show="headings", style="Info.Treeview")
        tree.heading("method", text=self.t("info.sites.col.type"))
        tree.heading("region", text=self.t("info.sites.col.region"))
        tree.heading("version", text=self.t("info.sites.col.version"))
        tree.heading("location", text=self.t("info.sites.col.location"))
        tree.heading("levels", text=self.t("info.sites.col.levels"))
        tree.heading("chance", text=self.t("info.sites.col.rarity"))
        tree.column("method", width=120, anchor="w", stretch=False)
        tree.column("region", width=120, anchor="w", stretch=False)
        tree.column("version", width=120, anchor="w", stretch=False)
        tree.column("location", width=360, anchor="w")
        tree.column("levels", width=90, anchor="center", stretch=False)
        tree.column("chance", width=90, anchor="center", stretch=False)
        tree.grid(row=start_row, column=0, sticky="nsew")
        vs = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=tree.xview)
        vs.grid(row=start_row, column=1, sticky="ns")
        hs.grid(row=start_row + 1, column=0, sticky="ew")
        wrap.rowconfigure(start_row, weight=1)
        wrap.columnconfigure(0, weight=1)
        tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        tree.tag_configure("odd", background=self.theme["info_table_row_alt_bg"], foreground=self.theme["fg"])
        tree.tag_configure("even", background=self.theme["info_table_row_bg"], foreground=self.theme["fg"])
        for i, row in enumerate(rows):
            vals = (
                row.get("method", "—"),
                row.get("region", "—"),
                row.get("version", "—"),
                row.get("location", "—"),
                row.get("levels", "—"),
                row.get("chance", "—"),
            )
            tree.insert("", "end", values=vals, tags=("odd" if i % 2 else "even",))
        self._info_sites_tree = tree

    def _render_info_tab_evolutions(self, frame: tk.Frame, details: dict):
        self._clear_info_tab(frame)
        paths = details.get("evolution_chain", []) or []
        if not paths:
            tk.Label(
                frame,
                text=self.t("info.evo.none"),
                bg=self.theme["panel"],
                fg=self.theme["muted"],
                font=(self._ui_font_family, 11),
            ).pack(expand=True, pady=24)
            return

        wrap = tk.Frame(frame, bg=self.theme["panel"])
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        c = tk.Canvas(wrap, bg=self.theme["panel"], highlightthickness=1, highlightbackground=self.theme["border"])
        c.grid(row=0, column=0, sticky="nsew")
        vs = ttk.Scrollbar(wrap, orient="vertical", command=c.yview)
        hs = ttk.Scrollbar(wrap, orient="horizontal", command=c.xview)
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        wrap.rowconfigure(0, weight=1)
        wrap.columnconfigure(0, weight=1)
        c.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        node_w = 194
        node_h = 96
        step_x = 260
        base_x = 18
        base_y = 18
        row_h = 132
        max_len = 1
        selected_id = int(self._info_species_id or 0)
        for row_idx, path in enumerate(paths):
            max_len = max(max_len, len(path))
            y = base_y + row_idx * row_h
            for i, step in enumerate(path):
                x = base_x + i * step_x
                sid = int(step.get("species_id", 0) or 0)
                fill = self.theme["info_table_row_bg"] if i % 2 == 0 else self.theme["info_table_row_alt_bg"]
                border_color = self.theme["accent"] if sid == selected_id and selected_id > 0 else self.theme["border"]
                c.create_rectangle(x, y, x + node_w, y + node_h, fill=fill, outline=border_color, width=2 if border_color == self.theme["accent"] else 1)
                sprite = self._load_sprite_photo(sid, (56, 56), allow_download=True) if sid > 0 else None
                if sprite is not None:
                    c.create_image(x + 36, y + 48, image=sprite)
                c.create_text(
                    x + 122,
                    y + 40,
                    text=step.get("name", "—"),
                    fill=self.theme["fg"],
                    anchor="center",
                    font=(self._ui_font_family, 10, "bold"),
                    width=126,
                )
                c.create_text(
                    x + 122,
                    y + 68,
                    text=step.get("trigger_text", "") if i > 0 else self.t("info.evo.base"),
                    fill=self.theme["muted"],
                    anchor="center",
                    font=(self._ui_font_family, 9),
                    width=126,
                )
                if i > 0:
                    trigger = step.get("trigger_text", "") or self.t("info.evo.trigger")
                    sx = x - (step_x - node_w) + 10
                    ex = x - 8
                    cy = y + node_h // 2
                    c.create_line(sx, cy, ex, cy, fill=self.theme["edge_nature"], width=2)
                    c.create_text((sx + ex) // 2, cy - 15, text=trigger, fill=self.theme["muted"], font=(self._ui_font_family, 9))
                    c.create_text(ex + 2, cy, text=">", fill=self.theme["edge_nature"], font=(self._ui_font_family, 10, "bold"), anchor="w")

        total_w = base_x + (max_len * step_x) + 40
        total_h = base_y + (len(paths) * row_h) + 40
        c.configure(scrollregion=(0, 0, total_w, total_h))

    def _apply_info_window_theme(self):
        if not self._info_window or not self._info_window.winfo_exists():
            return
        self._info_window.configure(bg=self.theme["bg"])
        if hasattr(self, "_info_root_frame") and self._info_root_frame.winfo_exists():
            self._info_root_frame.configure(bg=self.theme["panel"], highlightbackground=self.theme["border"])
        if hasattr(self, "_info_header_frame") and self._info_header_frame.winfo_exists():
            self._info_header_frame.configure(bg=self.theme["panel_alt"])
        if hasattr(self, "_info_title_label") and self._info_title_label.winfo_exists():
            self._info_title_label.configure(bg=self.theme["panel_alt"], fg=self.theme["fg"])
        if hasattr(self, "_info_close_btn") and self._info_close_btn.winfo_exists():
            self._info_close_btn.configure(
                bg=self.theme["info_tab_bg"],
                fg=self.theme["fg"],
                activebackground=self.theme["info_tab_active_bg"],
                activeforeground=self.theme["fg"],
                highlightthickness=1,
                highlightbackground=self.theme["border"],
            )
        if hasattr(self, "_info_tabbar_frame") and self._info_tabbar_frame.winfo_exists():
            self._info_tabbar_frame.configure(bg=self.theme["panel"])
        if self._info_status_label and self._info_status_label.winfo_exists():
            self._info_status_label.configure(bg=self.theme["panel_alt"], fg=self.theme["muted"])
        self._refresh_info_tab_buttons()
        if self._info_details:
            active = self._info_active_tab
            for k in list(self._info_tab_rendered.keys()):
                self._info_tab_rendered[k] = False
            self._switch_info_tab(active)

    def _show_default_sprite(self):
        try:
            img = Image.open(self.sprites.get_default_path())
            img = self._compose_sprite_on_bg(img, (96, 96), bg_hex=self.theme["panel"])
            self._sprite_img = ImageTk.PhotoImage(img)
            self.sprite_label.configure(image=self._sprite_img)
        except Exception as exc:
            print(f"[App] Failed to load default sprite: {exc}")

    def _load_brace_icons_async(self):
        def task():
            loaded: Dict[str, Image.Image] = {}
            everstone_img: Optional[Image.Image] = None
            for stat in STATS:
                path = self.brace_sprites.get_icon_path(stat)
                if not path:
                    continue
                try:
                    img = Image.open(path).convert("RGBA").resize((16, 16), Image.NEAREST)
                    loaded[stat] = img
                except Exception as exc:
                    print(f"[App] Failed to open brace icon for {stat} at {path}: {exc}")
            epath = self.brace_sprites.get_everstone_path()
            if epath:
                try:
                    everstone_img = Image.open(epath).convert("RGBA").resize((16, 16), Image.NEAREST)
                except Exception as exc:
                    print(f"[App] Failed to open everstone icon at {epath}: {exc}")
            self.after(0, lambda: self._apply_brace_icons(loaded, everstone_img))
        threading.Thread(target=task, daemon=True).start()

    def _apply_brace_icons(self, icons: Dict[str, Image.Image], everstone_icon: Optional[Image.Image]):
        tk_icons: Dict[str, ImageTk.PhotoImage] = {}
        for stat, img in icons.items():
            try:
                tk_icons[stat] = ImageTk.PhotoImage(img)
            except Exception as exc:
                print(f"[App] Failed to convert brace icon for {stat}: {exc}")
        self._brace_icons.update(tk_icons)
        if everstone_icon is not None:
            try:
                self._everstone_icon = ImageTk.PhotoImage(everstone_icon)
            except Exception as exc:
                print(f"[App] Failed to convert everstone icon: {exc}")
        self._request_recompute(reason="icons")

    def _load_sprite_async(self, pid: int, selection_gen: Optional[int] = None):
        def task():
            path = self.sprites.get_sprite_path(pid)
            try:
                img = Image.open(path)
            except Exception as exc:
                print(f"[App] Failed to open sprite at {path}: {exc}")
                try:
                    img = Image.open(self.sprites.get_default_path())
                except Exception:
                    img = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
            img = self._compose_sprite_on_bg(img, (96, 96), bg_hex=self.theme["panel"])
            def apply():
                if selection_gen is not None and selection_gen != self._selection_generation_id:
                    return
                try:
                    tk_img = ImageTk.PhotoImage(img)
                    self._sprite_img = tk_img  # Keep reference
                    self.sprite_label.configure(image=tk_img)
                except Exception as exc:
                    print(f"[App] Failed to set sprite for #{pid}: {exc}")
            self.after(0, apply)
        threading.Thread(target=task, daemon=True).start()

    def _capture_canvas_view_state(self) -> Dict[str, float]:
        if not hasattr(self, "canvas"):
            return {"x_frac": 0.0, "y_frac": 0.0, "zoom": 1.0}
        try:
            xv = self.canvas.xview()
            yv = self.canvas.yview()
            x_frac = float(xv[0]) if xv else 0.0
            y_frac = float(yv[0]) if yv else 0.0
        except Exception:
            x_frac, y_frac = 0.0, 0.0
        return {"x_frac": x_frac, "y_frac": y_frac, "zoom": float(self._zoom_scale)}

    def _restore_canvas_view_state(self, state: Dict[str, float]) -> None:
        if not hasattr(self, "canvas"):
            return
        target_zoom = max(self._zoom_min, min(self._zoom_max, float(state.get("zoom", 1.0))))
        base_zoom = self._zoom_scale if self._zoom_scale > 0 else 1.0
        if abs(target_zoom - base_zoom) > 1e-3:
            factor = target_zoom / base_zoom
            self.canvas.scale("all", 0.0, 0.0, factor, factor)
            self._zoom_scale = target_zoom

        nb = self.canvas.bbox("all")
        if nb:
            self.canvas.configure(scrollregion=(nb[0] - 80, nb[1] - 80, nb[2] + 80, nb[3] + 80))
        x_frac = max(0.0, min(1.0, float(state.get("x_frac", 0.0))))
        y_frac = max(0.0, min(1.0, float(state.get("y_frac", 0.0))))
        self.canvas.xview_moveto(x_frac)
        self.canvas.yview_moveto(y_frac)

    def _on_canvas_resize(self, _event):
        if self._resize_after_id:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
        self._resize_after_id = self.after(70, self._redraw_last_plan)

    def _redraw_last_plan(self):
        self._resize_after_id = None
        if self._last_plan is None or self._render_inflight:
            return
        try:
            gen_id = self._render_generation_id
            model = self._build_render_model(self._last_plan, max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))
            meta = self._last_render_meta or {}
            self._apply_render_model(
                gen_id,
                model,
                self._last_plan,
                keep_status=True,
                inv_assignments=meta.get("inv_assignments"),
                allow_compat=meta.get("allow_compat"),
            )
        except Exception as exc:
            LOGGER.debug("Resize redraw failed: %s", exc)

    # ---------- Compute ----------
    def _recompute(self):
        self._request_recompute(reason="direct")

    def _set_recompute_inputs_state(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for btn in self._iv_buttons.values():
            try:
                btn.configure(state=state)
            except Exception:
                pass
        if hasattr(self, "nature_combo"):
            try:
                if self._use_ctk:
                    self.nature_combo.configure(state=state)
                else:
                    self.nature_combo.configure(state="readonly" if enabled else "disabled")
            except Exception:
                pass
        if hasattr(self, "compatible_cb"):
            try:
                self.compatible_cb.configure(state=state)
            except Exception:
                pass

    def _request_recompute(self, reason: str = "ui"):
        LOGGER.debug(
            "Recompute request: reason=%s selected=%s ivs=%s nature=%s",
            reason,
            bool(self.selected),
            {s: self.iv_vars[s].get() for s in STATS},
            self.nature_var.get(),
        )
        if self._recompute_after_id:
            try:
                self.after_cancel(self._recompute_after_id)
            except Exception:
                pass
            self._recompute_after_id = None
        if not self.selected:
            self._render_empty()
            return
        self._recompute_after_id = self.after(self._recompute_debounce_ms, lambda: self._start_recompute(reason))

    def _start_recompute(self, reason: str = "debounced"):
        self._recompute_after_id = None
        if not self.selected:
            self._render_empty()
            return
        gen_id = self._render_generation_id + 1
        self._render_generation_id = gen_id
        self._render_inflight = True
        self._set_status("status.calculating", is_key=True)
        req = BreedingRequest(
            pokemon=self.selected,
            desired_31={s: self.iv_vars[s].get() for s in STATS},
            desired_nature=self.nature_var.get().strip() or NATURE_NONE,
            keep_nature=False
        )
        view_w = max(1, self.canvas.winfo_width())
        view_h = max(1, self.canvas.winfo_height())
        LOGGER.debug(
            "Render start: gen=%s reason=%s view=(%s,%s) req_ivs=%s nature=%s",
            gen_id,
            reason,
            view_w,
            view_h,
            req.desired_31,
            req.desired_nature,
        )
        threading.Thread(target=self._compute_plan_and_model, args=(gen_id, req, view_w, view_h), daemon=True).start()

    def _compute_plan_and_model(self, gen_id: int, req: BreedingRequest, view_w: int, view_h: int):
        try:
            try:
                gender_rate = self.species_info.get_gender_rate(req.pokemon.id)
                ratio_label, gender_costs = self.species_info.classify_gender_cost(gender_rate)
            except Exception as exc:
                LOGGER.debug("Gender ratio lookup failed for #%s: %s", req.pokemon.id, exc)
                ratio_label, gender_costs = ("?", GENDER_COST_50_50)
            LOGGER.debug("Compute plan start: gen=%s", gen_id)
            plan = self.engine.build_plan(req, gender_costs=gender_costs, ratio_label=ratio_label)
            model = self._build_render_model(plan, view_w, view_h)
            if not model.get("positions"):
                raise RuntimeError(self.t("error.no_route"))
            self.after(0, lambda: self._on_compute_success(gen_id, req, plan, ratio_label, gender_costs, model))
        except Exception as exc:
            tb = traceback.format_exc()
            self.after(0, lambda: self._on_compute_error(gen_id, exc, tb))

    def _on_compute_error(self, gen_id: int, exc: Exception, tb: str):
        LOGGER.debug("Compute/render error gen=%s current=%s err=%s\n%s", gen_id, self._render_generation_id, exc, tb)
        if gen_id != self._render_generation_id:
            LOGGER.debug("Ignoring stale compute error gen=%s current=%s", gen_id, self._render_generation_id)
            return
        self._render_inflight = False
        self._set_status("status.failed_keep_previous", is_key=True, err=str(exc))

    def _on_compute_success(
        self,
        gen_id: int,
        req: BreedingRequest,
        plan: BreedingPlan,
        ratio_label: str,
        gender_costs: Dict[str, int],
        model: Dict[str, object],
    ):
        if gen_id != self._render_generation_id:
            LOGGER.debug("Ignoring stale compute success gen=%s current=%s", gen_id, self._render_generation_id)
            return
        try:
            inv_report = self._match_inventory_for_plan(req, plan)
            if gen_id != self._render_generation_id:
                LOGGER.debug("Inventory match became stale gen=%s current=%s", gen_id, self._render_generation_id)
                return
            inv_assignments = dict(getattr(inv_report, "node_assignments", {}) or {})
            allow_compat = bool(self.compatible_var.get())

            self._render_plan(req, plan, ratio_label, gender_costs, inv_report=inv_report)
            if gen_id != self._render_generation_id:
                LOGGER.debug("Render plan became stale gen=%s current=%s", gen_id, self._render_generation_id)
                return

            if not self._apply_render_model(
                gen_id,
                model,
                plan,
                inv_assignments=inv_assignments,
                allow_compat=allow_compat,
            ):
                raise RuntimeError(self.t("error.stale_render"))

            self._last_inventory_report = inv_report
            self._last_plan = plan
            self._last_render_meta = {
                "req": req,
                "ratio_label": ratio_label,
                "gender_costs": gender_costs,
                "model": model,
                "inv_assignments": inv_assignments,
                "allow_compat": allow_compat,
            }
            self._set_status("status.ready", is_key=True, version=APP_VERSION)
        except Exception as exc:
            LOGGER.debug("Apply render failed gen=%s: %s\n%s", gen_id, exc, traceback.format_exc())
            self._set_status("status.failed_keep_previous", is_key=True, err=str(exc))
        finally:
            self._render_inflight = False

    def _build_render_model(self, plan: BreedingPlan, view_w: int, view_h: int) -> Dict[str, object]:
        active_nodes = self._collect_active_nodes(plan)
        layout = self._build_render_layout(plan, active_nodes, view_w, view_h)
        model = {
            "active_nodes": active_nodes,
            "positions": layout["positions"],
            "content_w": layout["content_w"],
            "content_h": layout["content_h"],
            "margin_y": layout["margin_y"],
            "junction_x": layout["junction_x"],
            "fusion_points": layout.get("fusion_points", {}),
        }
        LOGGER.debug(
            "Render model built: nodes=%s edges=%s active_layers=%s",
            len(model["positions"]),
            len(plan.connections),
            ",".join(f"{li+1}:{len(idxs)}" for li, idxs in sorted(active_nodes.items())),
        )
        return model

    # ---------- Render ----------
    def _render_empty(self):
        self._render_generation_id += 1
        self._render_inflight = False
        self.cost_title.configure(text="—")
        self.cost_details.configure(text="")
        self.canvas.delete(self._graph_tag)
        self.canvas.configure(scrollregion=(0, 0, 1, 1))
        self._last_plan = None
        self._last_render_meta = None
        self._last_inventory_report = None
        self._zoom_scale = 1.0
        self._view_state = {"x_frac": 0.0, "y_frac": 0.0, "zoom": 1.0}
        self.gender_box.delete("1.0", tk.END)
        self.notes_box.delete("1.0", tk.END)
        self._set_status("status.empty", is_key=True)

    @staticmethod
    def _nature_key(nature_text: str) -> str:
        raw = (nature_text or "").strip()
        if not raw or raw == NATURE_NONE:
            return ""
        return raw.split("(", 1)[0].strip()

    def _build_inventory_requirements(self, req: BreedingRequest, plan: BreedingPlan) -> List[InventoryRequirement]:
        source_nodes = {(pl, pi) for (pl, pi), _ in plan.connections}
        nature_name = self._nature_key(req.desired_nature)
        try:
            req_egg_groups = tuple(self.species_info.get_egg_groups(req.pokemon.id))
        except Exception:
            req_egg_groups = tuple()
        out: List[InventoryRequirement] = []
        for li, layer in enumerate(plan.node_layers):
            for ni, node in enumerate(layer):
                if (li, ni) not in source_nodes:
                    continue
                out.append(
                    InventoryRequirement(
                        node_key=(li, ni),
                        species_id=req.pokemon.id,
                        species_name=req.pokemon.name,
                        egg_groups=req_egg_groups,
                        gender=node.gender,
                        ivs31=tuple(sorted({normalize_stat_key(s) for s in node.ivs if normalize_stat_key(s)})),
                        has_nature=bool(node.has_nature),
                        nature=nature_name if node.has_nature else "",
                    )
                )
        return out

    def _match_inventory_for_plan(self, req: BreedingRequest, plan: BreedingPlan):
        requirements = self._build_inventory_requirements(req, plan)
        report = self.inventory_matcher.match(
            requirements=requirements,
            items=self.inventory_items,
            settings=self.inventory_settings,
            allow_compatible=bool(self.compatible_var.get()),
        )
        return report

    def _inventory_cost_block_text(self, report) -> str:
        if report is None:
            return ""
        est_cost = int(report.estimated_buy_cost_total or 0)
        total = int((self._last_plan.total_cost if self._last_plan else 0) + est_cost) if self._last_plan else est_cost
        by_level_lines: List[str] = []
        for iv_count in range(1, 7):
            qty = int((report.purchased_by_iv_count or {}).get(iv_count, 0))
            if qty <= 0:
                continue
            unit = int(self.inventory_settings.estimated_buy_price_by_iv_count.get(iv_count, 0) or 0)
            by_level_lines.append(
                self.t(
                    "inventory.purchase_level_line",
                    level=f"{iv_count}x31",
                    qty=qty,
                    unit=f"{unit:,}$",
                )
            )
        by_level_text = ""
        if by_level_lines:
            by_level_text = "\n" + self.t("inventory.purchase_breakdown") + "\n" + "\n".join(by_level_lines)
        return (
            self.t("inventory.used_count", count=report.inventory_used_count) + "\n" +
            self.t("inventory.purchased_count", count=report.purchase_count) + "\n" +
            self.t("inventory.missing_cost", cost=f"{est_cost:,}$") + "\n" +
            self.t("inventory.total_with_purchases", cost=f"{total:,}$") +
            by_level_text
        )

    def _render_plan(
        self,
        req: BreedingRequest,
        plan: BreedingPlan,
        ratio_label: str,
        gender_costs: Dict[str, int],
        inv_report=None,
    ):
        self.cost_title.configure(text=f"{req.pokemon.name} · {plan.k}x31")
        if inv_report is None:
            inv_report = self._match_inventory_for_plan(req, plan)
        total_crosses = plan.breeds_needed
        nature_line = plan.desired_nature if plan.nature_selected else self.t("nature.none")
        braces_lines = "\n".join(
            self.t("cost.braces_line", level=lvl, qty=qty, unit=f"{BRACE_COST:,}$")
            for lvl, qty in plan.braces_by_level
        )
        if braces_lines:
            braces_lines += "\n"
        inventory_estimated = int(inv_report.estimated_buy_cost_total if inv_report else 0)
        total_with_inventory = int(plan.total_cost + inventory_estimated)
        inv_by_level_lines: List[str] = []
        if inv_report is not None:
            for iv_count in range(1, 7):
                qty = int((inv_report.purchased_by_iv_count or {}).get(iv_count, 0))
                if qty <= 0:
                    continue
                unit = int(self.inventory_settings.estimated_buy_price_by_iv_count.get(iv_count, 0) or 0)
                inv_by_level_lines.append(
                    self.t(
                        "inventory.purchase_level_line",
                        level=f"{iv_count}x31",
                        qty=qty,
                        unit=f"{unit:,}$",
                    )
                )
        inv_by_level_text = ""
        if inv_by_level_lines:
            inv_by_level_text = "\n" + self.t("inventory.purchase_breakdown") + "\n" + "\n".join(inv_by_level_lines)
        self.cost_details.configure(text=
            self.t("cost.parents_needed", count=plan.parents_needed) + "\n" +
            self.t("cost.total_crosses", count=total_crosses) + "\n" +
            self.t("cost.nature", nature=nature_line) + "\n" +
            f"{braces_lines}" +
            self.t("cost.braces_total", cost=f"{plan.braces_cost:,}$", qty=plan.braces_needed) + "\n" +
            self.t("cost.nature_total", cost=f"{plan.everstone_cost:,}$", qty=plan.everstone_uses, each=f"{EVERSTONE_COST:,}$") + "\n" +
            self.t("cost.balls_total", cost=f"{plan.balls_cost:,}$", qty=plan.balls_used, each=f"{POKEBALL_COST:,}$") + "\n" +
            self.t("cost.gender_total", cost=f"{plan.gender_cost_total:,}$") + "\n" +
            self.t("cost.ratio", ratio=ratio_label) + "\n" +
            self.t("cost.gender_selections", m=plan.gender_selections.get('M', 0), f=plan.gender_selections.get('F', 0)) + "\n" +
            self.t("cost.total", cost=f"{plan.total_cost:,}$") + "\n\n" +
            self.t("inventory.used_count", count=(inv_report.inventory_used_count if inv_report else 0)) + "\n" +
            self.t("inventory.purchased_count", count=(inv_report.purchase_count if inv_report else 0)) + "\n" +
            self.t("inventory.missing_cost", cost=f"{inventory_estimated:,}$") + "\n" +
            self.t("inventory.total_with_purchases", cost=f"{total_with_inventory:,}$") +
            inv_by_level_text
        )
        # Género details
        self.gender_box.delete("1.0", tk.END)
        self.gender_box.insert(tk.END, self.t("gender.selection_costs", ratio=ratio_label) + "\n")
        self.gender_box.insert(tk.END, self.t("gender.male_cost", cost=f"{gender_costs.get('M', 0):,}$") + "\n")
        self.gender_box.insert(tk.END, self.t("gender.female_cost", cost=f"{gender_costs.get('F', 0):,}$") + "\n\n")
        self.gender_box.insert(tk.END, self.t("gender.layers_header") + "\n")
        for gl in plan.gender_layers:
            tag = f" {self.t('gender.selectable')}" if gl.selectable else ""
            self.gender_box.insert(tk.END, self.t("gender.layer_line", label=gl.label, total=gl.count, m=gl.need_m, f=gl.need_f, tag=tag) + "\n")
        self.gender_box.insert(tk.END, "\n" + self.t("gender.reminder") + "\n")
        # Notes
        self.notes_box.delete("1.0", tk.END)
        for n in plan.notes:
            self.notes_box.insert(tk.END, f"• {self._translate_note_line(n)}\n")
        self.notes_box.insert(
            tk.END,
            f"• {self.t('inventory.note', used=(inv_report.inventory_used_count if inv_report else 0), missing=(inv_report.purchase_count if inv_report else 0), compat=(self.t('inventory.compat_on') if self.compatible_var.get() else self.t('inventory.compat_off')))}\n"
        )

    def _apply_render_model(
        self,
        gen_id: int,
        model: Dict[str, object],
        plan: BreedingPlan,
        keep_status: bool = False,
        inv_assignments: Optional[Dict[Tuple[int, int], str]] = None,
        allow_compat: Optional[bool] = None,
    ) -> bool:
        if gen_id != self._render_generation_id:
            LOGGER.debug("Skipping stale apply: gen=%s current=%s", gen_id, self._render_generation_id)
            return False
        ok = self._draw_layers(
            plan,
            model=model,
            gen_id=gen_id,
            inv_assignments=inv_assignments,
            allow_compat=allow_compat,
        )
        if ok and not keep_status:
            self._set_status("status.rendered", is_key=True, gen=gen_id)
        return ok

    def _translate_note_line(self, note: str) -> str:
        note = (note or "").strip()
        mapping = {
            "Cada cruce consume a ambos padres y solo queda el huevo.": "notes.cross_consumes",
            "Braces: 2 por cruce; si un padre lleva naturaleza, usa Everstone en lugar de brace.": "notes.braces_rule",
            "Base (1x31) NO puede seleccionar género con NPC: se requieren M/H necesarios.": "notes.base_gender",
            "En capas intermedias se selecciona el género del huevo para garantizar parejas.": "notes.intermediate_gender",
        }
        if note.startswith("Género (según species): ratio "):
            ratio = note.replace("Género (según species): ratio ", "").rstrip(".")
            return self.t("notes.gender_ratio", ratio=ratio)
        if note.startswith("Insumos: ") and "Pokéballs usadas" in note:
            m = re.search(r"Insumos:\s*(\d+)", note)
            balls = m.group(1) if m else "0"
            return self.t("notes.balls_used", count=balls)
        if note.startswith("Naturaleza fijada desde base y propagada con Piedra Eterna"):
            return self.t("notes.nature_fix", cost=f"{EVERSTONE_COST:,}")
        key = mapping.get(note)
        return self.t(key) if key else note

    def _collect_active_nodes(self, plan: BreedingPlan) -> Dict[int, List[int]]:
        layer_count = len(plan.node_layers)
        active_sets: Dict[int, set] = {li: set() for li in range(layer_count)}

        if plan.nature_selected:
            parents_by_child: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}
            fusion_roots: List[Tuple[int, int]] = []
            for (pl, pi), (cl, ci) in plan.connections:
                parents_by_child.setdefault((cl, ci), []).append((pl, pi))

            for li, layer in enumerate(plan.node_layers):
                for idx, node in enumerate(layer):
                    if node.is_nature_branch:
                        active_sets[li].add(idx)
                    if node.is_fusion_donor:
                        fusion_roots.append((li, idx))
                        active_sets[li].add(idx)

            stack = list(fusion_roots)
            seen = set(stack)
            while stack:
                key = stack.pop()
                for pkey in parents_by_child.get(key, []):
                    pl, pi = pkey
                    pnode = plan.node_layers[pl][pi]
                    if pnode.is_nature_branch:
                        continue
                    active_sets[pl].add(pi)
                    if pkey not in seen:
                        seen.add(pkey)
                        stack.append(pkey)
        else:
            for (pl, pi), (cl, ci) in plan.connections:
                active_sets[pl].add(pi)
                active_sets[cl].add(ci)

        out: Dict[int, List[int]] = {}
        for li, layer in enumerate(plan.node_layers):
            if not active_sets[li]:
                active_sets[li] = set(range(len(layer)))
            out[li] = sorted(active_sets[li])
        return out

    def _build_render_layout(
        self,
        plan: BreedingPlan,
        active_nodes: Dict[int, List[int]],
        view_w: int,
        view_h: int,
    ) -> Dict[str, object]:
        layer_count = len(plan.node_layers)
        margin_x, margin_y = 38.0, 24.0
        node_w, node_h = 136.0, 84.0
        col_gap = 72.0
        header_h = 30.0
        top_padding = margin_y + header_h + 18.0
        min_node_gap_y = 16.0
        leaf_pitch = node_h + 26.0
        tree_block_gap = 120.0

        column_x = {
            li: margin_x + li * (node_w + col_gap)
            for li in range(layer_count)
        }
        content_w = max(
            view_w,
            margin_x * 2 + layer_count * node_w + max(0, layer_count - 1) * col_gap,
        )

        positions: Dict[Tuple[int, int], Tuple[float, float, float, float]] = {}
        fusion_points: Dict[Tuple[int, int], Tuple[float, float]] = {}
        junction_x = {li: column_x[li] - 24.0 for li in range(layer_count)}

        if plan.nature_selected:
            # Build independent vertical blocks by tree_id, keep primary block lower.
            roots: Dict[int, BreedingNode] = {}
            for li, layer in enumerate(plan.node_layers):
                for idx in active_nodes.get(li, []):
                    n = layer[idx]
                    if n.is_nature_branch or n.tree_id <= 0 or n.slot != 0:
                        continue
                    prev = roots.get(n.tree_id)
                    if prev is None or len(n.ivs) > len(prev.ivs):
                        roots[n.tree_id] = n

            donor_tree_ids = sorted(
                [tid for tid, n in roots.items() if n.branch_role == "nature_donor"],
                key=lambda tid: roots[tid].fusion_level if roots[tid].fusion_level else tid,
            )
            primary_tree_ids = sorted([tid for tid, n in roots.items() if n.branch_role == "primary"])
            ordered_trees = donor_tree_ids + primary_tree_ids

            tree_top: Dict[int, float] = {}
            root_y: Dict[int, float] = {}
            cursor = top_padding + node_h + 132.0
            for tid in ordered_trees:
                root_node = roots[tid]
                leaves = max(1, 2 ** (len(root_node.ivs) - 1))
                block_h = leaves * leaf_pitch
                tree_top[tid] = cursor
                root_y[tid] = cursor + block_h / 2.0
                cursor += block_h + tree_block_gap

            for li, layer in enumerate(plan.node_layers):
                x0_col = column_x[li]
                for idx in active_nodes.get(li, []):
                    n = layer[idx]
                    if n.is_nature_branch or n.tree_id <= 0:
                        continue
                    top = tree_top.get(n.tree_id, top_padding + node_h)
                    span = max(1.0, float(2 ** (max(1, len(n.ivs)) - 1)))
                    center_y = top + (n.slot + 0.5) * span * leaf_pitch
                    y0 = center_y - node_h / 2.0
                    positions[(li, idx)] = (x0_col, y0, x0_col + node_w, y0 + node_h)

            # Nature staircase aligned to fusion donors.
            k = layer_count
            nature_y: Dict[int, float] = {}
            nature_step = node_h + 24.0
            for level in range(1, k + 1):
                li = level - 1
                donor_idx = next(
                    (
                        idx
                        for idx in active_nodes.get(li, [])
                        if plan.node_layers[li][idx].is_fusion_donor
                        and plan.node_layers[li][idx].fusion_level == level
                    ),
                    None,
                )
                if donor_idx is not None and (li, donor_idx) in positions:
                    dbox = positions[(li, donor_idx)]
                    donor_cy = (dbox[1] + dbox[3]) / 2.0
                    offset = node_h + (82.0 if level == k else 52.0)
                    center_y = donor_cy - offset
                elif level == 1:
                    center_y = top_padding + node_h / 2.0
                else:
                    center_y = nature_y[level - 1] + nature_step

                if level > 1 and center_y < nature_y[level - 1] + nature_step:
                    center_y = nature_y[level - 1] + nature_step
                nature_y[level] = center_y

                nat_idx = next(
                    (idx for idx in active_nodes.get(li, []) if plan.node_layers[li][idx].is_nature_branch),
                    None,
                )
                if nat_idx is not None:
                    x0_col = column_x[li]
                    y0 = center_y - node_h / 2.0
                    positions[(li, nat_idx)] = (x0_col, y0, x0_col + node_w, y0 + node_h)
                    if level > 1:
                        fusion_points[(li, nat_idx)] = (x0_col - 42.0, center_y)

            LOGGER.debug(
                "Layout active: %s",
                ", ".join(f"{li+1}x31={len(active_nodes.get(li, []))}" for li in range(layer_count)),
            )
            LOGGER.debug("Layout tree roots: %s", ", ".join(f"T{tid}={root_y.get(tid, 0):.1f}" for tid in ordered_trees))
            LOGGER.debug("Layout nature y: %s", ", ".join(f"L{lvl}={nature_y[lvl]:.1f}" for lvl in sorted(nature_y)))
        else:
            # Regular bracket (pure mode).
            for li, layer in enumerate(plan.node_layers):
                x0_col = column_x[li]
                vis = active_nodes.get(li, [])
                stride = max(1.0, float(2 ** li)) * leaf_pitch
                base_top = top_padding + 18.0
                for pos, idx in enumerate(vis):
                    center_y = base_top + (pos + 0.5) * stride
                    y0 = center_y - node_h / 2.0
                    positions[(li, idx)] = (x0_col, y0, x0_col + node_w, y0 + node_h)

        # Hard no-overlap pass per column.
        for li, idxs in active_nodes.items():
            seq = sorted(idxs, key=lambda idx: positions.get((li, idx), (0, 0, 0, 0))[1])
            prev_bottom = None
            for idx in seq:
                key = (li, idx)
                if key not in positions:
                    continue
                x0, y0, x1, y1 = positions[key]
                if prev_bottom is not None and y0 < prev_bottom + min_node_gap_y:
                    dy = (prev_bottom + min_node_gap_y) - y0
                    y0 += dy
                    y1 += dy
                    positions[key] = (x0, y0, x1, y1)
                prev_bottom = positions[key][3]

        min_y = min((rect[1] for rect in positions.values()), default=top_padding)
        if min_y < top_padding:
            shift = top_padding - min_y
            for key, (x0, y0, x1, y1) in list(positions.items()):
                positions[key] = (x0, y0 + shift, x1, y1 + shift)
            if fusion_points:
                fusion_points = {k: (pt[0], pt[1] + shift) for k, pt in fusion_points.items()}

        max_y = max((rect[3] for rect in positions.values()), default=top_padding + node_h)
        content_h = max(view_h, max_y + margin_y + 30.0)

        # Debug overlap count.
        keys = list(positions.keys())
        overlaps = 0
        for i in range(len(keys)):
            a = positions[keys[i]]
            for j in range(i + 1, len(keys)):
                b = positions[keys[j]]
                if a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]:
                    continue
                overlaps += 1
        if overlaps:
            LOGGER.debug("Layout overlap warnings: %s", overlaps)

        return {
            "positions": positions,
            "content_w": content_w,
            "content_h": content_h,
            "margin_y": margin_y,
            "node_h": node_h,
            "junction_x": junction_x,
            "fusion_points": fusion_points,
        }

    def _draw_connections_from_layout(
        self,
        plan: BreedingPlan,
        positions: Dict[Tuple[int, int], Tuple[float, float, float, float]],
        junction_x: Dict[int, float],
        fusion_points: Dict[Tuple[int, int], Tuple[float, float]],
    ) -> None:
        def edge_kind(parent_key: Tuple[int, int], child_key: Tuple[int, int]) -> str:
            p = plan.node_layers[parent_key[0]][parent_key[1]]
            c = plan.node_layers[child_key[0]][child_key[1]]
            if p.is_nature_branch and c.is_nature_branch:
                return "nature_spine"
            if c.is_nature_branch and not p.is_nature_branch:
                return "fusion"
            return "pure"

        for parent_key, child_key in plan.connections:
            pbox = positions.get(parent_key)
            cbox = positions.get(child_key)
            if not pbox or not cbox:
                continue

            kind = edge_kind(parent_key, child_key)
            if kind == "nature_spine":
                color = self.theme["edge_nature"]
                width = 2.8
            elif kind == "fusion":
                color = self.theme["edge_fusion"]
                width = 2.2
            else:
                color = self.theme["edge_pure"]
                width = 1.4

            py = (pbox[1] + pbox[3]) / 2.0
            cy = (cbox[1] + cbox[3]) / 2.0

            if kind in ("nature_spine", "fusion") and child_key in fusion_points:
                fx, fy = fusion_points[child_key]
                sx = pbox[2] if parent_key[0] < child_key[0] else pbox[0]
                self.canvas.create_line(sx, py, fx, py, fill=color, width=width, tags=(self._graph_tag, "edge"))
                self.canvas.create_line(fx, py, fx, fy, fill=color, width=width, tags=(self._graph_tag, "edge"))
                self.canvas.create_line(fx, fy, cbox[0], cy, fill=color, width=width, tags=(self._graph_tag, "edge"))
            else:
                sx = pbox[2]
                ex = cbox[0]
                jx = junction_x.get(child_key[0], (sx + ex) / 2.0)
                jx = min(max(jx, sx + 14.0), ex - 14.0)
                self.canvas.create_line(sx, py, jx, py, fill=color, width=width, tags=(self._graph_tag, "edge"))
                self.canvas.create_line(jx, py, jx, cy, fill=color, width=width, tags=(self._graph_tag, "edge"))
                self.canvas.create_line(jx, cy, ex, cy, fill=color, width=width, tags=(self._graph_tag, "edge"))

    def _draw_layers(
        self,
        plan: BreedingPlan,
        model: Optional[Dict[str, object]] = None,
        gen_id: Optional[int] = None,
        inv_assignments: Optional[Dict[Tuple[int, int], str]] = None,
        allow_compat: Optional[bool] = None,
    ) -> bool:
        if gen_id is not None and gen_id != self._render_generation_id:
            LOGGER.debug("Draw aborted by stale generation: draw=%s current=%s", gen_id, self._render_generation_id)
            return False
        prev_view = self._capture_canvas_view_state()
        if not plan.node_layers:
            return False
        if model is None:
            model = self._build_render_model(plan, max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height()))

        active_nodes: Dict[int, List[int]] = model.get("active_nodes", {})  # type: ignore[assignment]
        positions: Dict[Tuple[int, int], Tuple[float, float, float, float]] = model.get("positions", {})  # type: ignore[assignment]
        if not positions:
            return False
        content_w = float(model.get("content_w", max(1, self.canvas.winfo_width())))
        content_h = float(model.get("content_h", max(1, self.canvas.winfo_height())))
        margin_y = float(model.get("margin_y", 24.0))
        junction_x: Dict[int, float] = model.get("junction_x", {})  # type: ignore[assignment]
        fusion_points: Dict[Tuple[int, int], Tuple[float, float]] = model.get("fusion_points", {})  # type: ignore[assignment]

        self.canvas.delete(self._graph_tag)
        self._zoom_scale = 1.0
        self.canvas.configure(scrollregion=(0, 0, content_w, content_h))
        self._draw_canvas_background(content_w, content_h)

        for layer_idx, layer_nodes in enumerate(plan.node_layers):
            vis_indices = active_nodes.get(layer_idx, list(range(len(layer_nodes))))
            x0_col = min((positions[(layer_idx, idx)][0] for idx in vis_indices if (layer_idx, idx) in positions), default=38.0)
            self.canvas.create_text(
                x0_col,
                margin_y + 2,
                anchor="nw",
                fill=self.theme["muted"],
                text=self.t("graph.layer_header", level=layer_idx + 1, count=len(vis_indices)),
                font=(self._ui_font_family, 10),
                tags=(self._graph_tag, "label"),
            )

        self._draw_connections_from_layout(plan, positions, junction_x, fusion_points)
        source_nodes = {(pl, pi) for (pl, pi), _ in plan.connections}
        if inv_assignments is None:
            inv_assignments = {}
            if self._last_inventory_report is not None:
                inv_assignments = dict(getattr(self._last_inventory_report, "node_assignments", {}) or {})
        compat_enabled = bool(self.compatible_var.get()) if allow_compat is None else bool(allow_compat)

        for layer_idx, layer_nodes in enumerate(plan.node_layers):
            for node_idx in active_nodes.get(layer_idx, list(range(len(layer_nodes)))):
                if gen_id is not None and gen_id != self._render_generation_id:
                    LOGGER.debug("Node draw interrupted: draw=%s current=%s", gen_id, self._render_generation_id)
                    return False
                node = layer_nodes[node_idx]
                if (layer_idx, node_idx) not in positions:
                    continue
                x0, y0, x1, y1 = positions[(layer_idx, node_idx)]
                node_is_source = (layer_idx, node_idx) in source_nodes
                node_fill = self.theme["nature_fill"] if node.has_nature else self.theme["node_fill"]
                inv_assigned = (layer_idx, node_idx) in inv_assignments
                border_color = "#36D37E" if inv_assigned else self.theme["border"]
                border_width = 2 if inv_assigned else 1
                node_tag = f"node:{layer_idx}:{node_idx}"
                node_tags = (self._graph_tag, "node", node_tag)
                self.canvas.create_rectangle(
                    x0 + 2,
                    y0 + 2,
                    x1 + 2,
                    y1 + 2,
                    outline="",
                    fill=self.theme["node_shadow"],
                    tags=node_tags,
                )
                self._create_round_rect(x0, y0, x1, y1, radius=10, outline=border_color, fill=node_fill, width=border_width, tags=node_tags)
                self._draw_colored_ivs((x0 + x1) / 2, y0 + 40, node.ivs, tags=node_tags)

                gsym = "♂" if node.gender == "M" else "♀"
                gcol = "#60A5FA" if node.gender == "M" else "#F472B6"
                self.canvas.create_text(x1 - 8, y0 + 8, text=gsym, fill=gcol, anchor="ne", font=(self._ui_font_family, 10, "bold"), tags=node_tags)

                if node_is_source and node.item:
                    if node.item == "EVERSTONE":
                        self.canvas.create_text((x0 + x1) / 2, y0 + 8, text=f"${EVERSTONE_COST//1000}k", fill="#FDE68A", font=(self._ui_font_family, 7, "bold"), tags=(self._graph_tag, "node"))
                        if self._everstone_icon:
                            self.canvas.create_image((x0 + x1) / 2, y0 + 21, image=self._everstone_icon, anchor="center", tags=node_tags)
                        else:
                            self.canvas.create_text((x0 + x1) / 2, y0 + 21, text="E", fill="#FDE68A", font=(self._ui_font_family, 9, "bold"), tags=node_tags)
                    else:
                        self.canvas.create_text((x0 + x1) / 2, y0 + 8, text=f"${BRACE_COST//1000}k", fill="#E2E8F0", font=(self._ui_font_family, 7, "bold"), tags=node_tags)
                        icon = self._brace_icons.get(node.item)
                        if icon:
                            self.canvas.create_image((x0 + x1) / 2, y0 + 21, image=icon, anchor="center", tags=node_tags)

                if node.has_nature:
                    self.canvas.create_text((x0 + x1) / 2, y0 - 8, fill="#FDE68A", text=self.t("graph.nature"), font=(self._ui_font_family, 7, "bold"), tags=node_tags)
                status_parts: List[str] = []
                if node_is_source:
                    status_parts.append(self.t("graph.inv") if inv_assigned else self.t("graph.buy"))
                if compat_enabled and not node.is_nature_branch:
                    status_parts.append(self.t("graph.compat"))
                if status_parts:
                    if node_is_source and inv_assigned:
                        status_color = "#36D37E"
                    elif node_is_source:
                        status_color = self.theme["muted"]
                    else:
                        status_color = self.theme["accent"]
                    self.canvas.create_text(
                        x0 + 8,
                        y0 + 8,
                        text=" · ".join(status_parts),
                        fill=status_color,
                        anchor="nw",
                        font=(self._ui_font_family, 6, "bold" if node_is_source else "normal"),
                        tags=node_tags,
                    )
                if node_is_source:
                    self.canvas.tag_bind(node_tag, "<Button-3>", lambda _e, key=(layer_idx, node_idx): self._show_inventory_assignment(key))

                footer_parts = []
                if node.cost_ball > 0:
                    footer_parts.append(self.t("graph.ball", cost=POKEBALL_COST))
                if node.cost_gender > 0:
                    footer_parts.append(self.t("graph.gender", cost=f"{node.cost_gender:,}"))
                if footer_parts:
                    self.canvas.create_text((x0 + x1) / 2, y1 - 8, text=" | ".join(footer_parts), fill=self.theme["muted"], font=(self._ui_font_family, 7), tags=node_tags)

        bbox = self.canvas.bbox(self._graph_tag)
        if bbox:
            self.canvas.configure(scrollregion=(bbox[0] - 80, bbox[1] - 80, bbox[2] + 80, bbox[3] + 80))
            self._restore_canvas_view_state(prev_view)
            self._view_state = self._capture_canvas_view_state()
        LOGGER.debug("Render done: gen=%s nodes=%s edges=%s", gen_id if gen_id is not None else self._render_generation_id, len(positions), len(plan.connections))
        return True

    def _show_inventory_assignment(self, node_key: Tuple[int, int]) -> None:
        report = self._last_inventory_report
        if report is None:
            self._set_status("status.rendered", is_key=True)
            return
        assigned_id = (report.node_assignments or {}).get(node_key)
        if not assigned_id:
            self._set_status(f"{self.t('graph.buy')} · {node_key[0] + 1}x31/{node_key[1] + 1}")
            return
        item = next((x for x in self.inventory_items if x.id == assigned_id), None)
        if item is None:
            self._set_status(f"{self.t('graph.inv')} · #{assigned_id[:8]}")
            return
        iv_text = "+".join(item.ivs_key()) or "-"
        self._set_status(f"{self.t('graph.inv')} · {item.species_name or '?'} · {item.gender} · {iv_text}")

    def _create_round_rect(self, x1, y1, x2, y2, radius=8, **kwargs):
        points = [
            x1 + radius, y1,
            x2 - radius, y1,
            x2, y1,
            x2, y1 + radius,
            x2, y2 - radius,
            x2, y2,
            x2 - radius, y2,
            x1 + radius, y2,
            x1, y2,
            x1, y2 - radius,
            x1, y1 + radius,
            x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, splinesteps=12, **kwargs)

    def _draw_canvas_background(self, width: float, height: float):
        # subtle radial gradient approximation
        cx, cy = width / 2, height / 2
        base1 = self.theme["canvas_bg"]
        base2 = self.theme_manager._mix(self.theme["canvas_bg"], self.theme["panel"], 0.25)
        base3 = self.theme_manager._mix(self.theme["canvas_bg"], "#000000", 0.20 if self.theme_cfg.mode == "dark" else 0.0)
        for i, color in enumerate([base1, base2, base3]):
            r = max(width, height) * (1.0 - i * 0.2)
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=color, outline="", tags=(self._graph_tag, "bg"))
        # faint grid
        step = 28
        for x in range(0, int(width), step):
            self.canvas.create_line(x, 0, x, height, fill=self.theme["grid"], width=1, tags=(self._graph_tag, "bg"))
        for y in range(0, int(height), step):
            self.canvas.create_line(0, y, width, y, fill=self.theme["grid"], width=1, tags=(self._graph_tag, "bg"))

    def _draw_colored_ivs(self, cx: float, cy: float, iv_tokens: Tuple[str, ...], tags=()):
        tokens = [t for t in iv_tokens if t]
        if not tokens:
            return
        font = tkfont.Font(family=self._ui_font_family, size=8, weight="bold")
        parts: List[Tuple[str, str]] = []
        for i, tok in enumerate(tokens):
            parts.append((tok, IV_COLORS.get(tok, self.theme["fg"])))
            if i < len(tokens) - 1:
                parts.append(("+", self.theme["muted"]))
        total_w = sum(font.measure(txt) for txt, _ in parts)
        x = cx - total_w / 2
        for txt, col in parts:
            self.canvas.create_text(x, cy, text=txt, anchor="w", fill=col, font=font, tags=tags)
            x += font.measure(txt)

    def _on_canvas_press(self, event):
        current = self.canvas.find_withtag("current")
        if current:
            tags = self.canvas.gettags(current[0])
            if "node" in tags:
                self._is_panning = False
                return
        self._is_panning = True
        self.canvas.scan_mark(event.x, event.y)
        self.canvas.configure(cursor="hand2")

    def _on_canvas_drag(self, event):
        if not self._is_panning:
            return
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_canvas_motion(self, event):
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        items = self.canvas.find_withtag("node")
        
        # Reset all nodes border
        for item in items:
            # Only affect polygons (round rects)
            if self.canvas.type(item) == "polygon":
                self.canvas.itemconfig(item, outline=self.theme["border"], width=1)
                
        # Find hovered items
        closest = self.canvas.find_overlapping(x, y, x, y)
        for c in closest:
            if "node" in self.canvas.gettags(c) and self.canvas.type(c) == "polygon":
                self.canvas.itemconfig(c, outline=self.theme["accent"], width=2)
                self.canvas.configure(cursor="hand1")
                return
        
        if not self._is_panning:
            self.canvas.configure(cursor="")

    def _on_canvas_release(self, _event):
        if self._is_panning:
            self.canvas.configure(cursor="")
        self._is_panning = False

    def _on_canvas_mousewheel(self, event):
        bbox = self.canvas.bbox("all")
        if not bbox:
            return
        if hasattr(event, "delta") and event.delta:
            direction = 1 if event.delta > 0 else -1
        elif getattr(event, "num", None) == 4:
            direction = 1
        elif getattr(event, "num", None) == 5:
            direction = -1
        else:
            return

        target_factor = 1.12 if direction > 0 else (1 / 1.12)
        new_scale = self._zoom_scale * target_factor
        if new_scale < self._zoom_min or new_scale > self._zoom_max:
            return

        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        self._smooth_zoom(x, y, target_factor, steps=4)

    def _smooth_zoom(self, x: float, y: float, total_factor: float, steps: int = 4):
        if steps <= 0:
            return
        step_factor = total_factor ** (1.0 / steps)

        def do_step(remaining: int):
            if remaining <= 0:
                return
            next_scale = self._zoom_scale * step_factor
            if next_scale < self._zoom_min or next_scale > self._zoom_max:
                return
            self.canvas.scale("all", x, y, step_factor, step_factor)
            self._zoom_scale = next_scale
            nb = self.canvas.bbox("all")
            if nb:
                self.canvas.configure(scrollregion=(nb[0] - 80, nb[1] - 80, nb[2] + 80, nb[3] + 80))
            self.after(12, lambda: do_step(remaining - 1))

        do_step(steps)


def ensure_default_asset():
    # Never write into runtime/install dir. Ensure user fallback default exists.
    if os.path.exists(DEFAULT_SPRITE_PATH):
        return
    if os.path.exists(RUNTIME_DEFAULT_SPRITE_PATH):
        try:
            os.makedirs(os.path.dirname(DEFAULT_SPRITE_PATH), exist_ok=True)
            shutil.copy2(RUNTIME_DEFAULT_SPRITE_PATH, DEFAULT_SPRITE_PATH)
            return
        except Exception as exc:
            print(f"[Assets] failed to copy bundled default sprite to user dir: {exc}")
    try:
        os.makedirs(os.path.dirname(DEFAULT_SPRITE_PATH), exist_ok=True)
        img = Image.new("RGBA", (96, 96), (25, 25, 30, 255))
        img.save(DEFAULT_SPRITE_PATH)
    except Exception as exc:
        print(f"[Assets] failed to create user default sprite at {DEFAULT_SPRITE_PATH}: {exc}")


if __name__ == "__main__":
    from launcher import run_app

    run_app(
        app_factory=App,
        ensure_assets=ensure_default_asset,
        app_version=APP_VERSION,
        updater_config_path=UPDATER_CONFIG_PATH,
        splash_duration_ms=1200,
        runtime_assets_dir=RUNTIME_ASSETS_DIR,
        user_assets_dir=ASSETS_DIR,
        enable_updater=True,
    )
