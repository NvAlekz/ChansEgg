import json
import math
import os
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


STAT_KEYS: Tuple[str, ...] = ("hp", "atk", "def", "spa", "spd", "spe")
STAT_ALIASES: Dict[str, str] = {
    "hp": "hp",
    "atk": "atk",
    "attack": "atk",
    "def": "def",
    "defense": "def",
    "spa": "spa",
    "special-attack": "spa",
    "spatk": "spa",
    "spd": "spd",
    "special-defense": "spd",
    "spdef": "spd",
    "spe": "spe",
    "speed": "spe",
}


NATURE_CHART: Dict[str, Tuple[Optional[str], Optional[str]]] = {
    "hardy": (None, None),
    "lonely": ("atk", "def"),
    "brave": ("atk", "spe"),
    "adamant": ("atk", "spa"),
    "naughty": ("atk", "spd"),
    "bold": ("def", "atk"),
    "docile": (None, None),
    "relaxed": ("def", "spe"),
    "impish": ("def", "spa"),
    "lax": ("def", "spd"),
    "timid": ("spe", "atk"),
    "hasty": ("spe", "def"),
    "serious": (None, None),
    "jolly": ("spe", "spa"),
    "naive": ("spe", "spd"),
    "modest": ("spa", "atk"),
    "mild": ("spa", "def"),
    "quiet": ("spa", "spe"),
    "bashful": (None, None),
    "rash": ("spa", "spd"),
    "calm": ("spd", "atk"),
    "gentle": ("spd", "def"),
    "sassy": ("spd", "spe"),
    "careful": ("spd", "spa"),
    "quirky": (None, None),
}


def normalize_stat_key(stat_key: str) -> str:
    k = (stat_key or "").strip().lower()
    return STAT_ALIASES.get(k, "")


def normalize_nature_name(nature_text: str) -> str:
    raw = (nature_text or "").strip()
    if not raw:
        return ""
    lowered = raw.lower()
    if lowered.startswith("ninguna") or lowered.startswith("none"):
        return ""
    first = raw.split("(", 1)[0].strip().split(" ", 1)[0].strip().lower()
    if first in NATURE_CHART:
        return first
    return ""


def canonical_ivs(ivs: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    out = {k: 0 for k in STAT_KEYS}
    if not ivs:
        return out
    for rk, rv in ivs.items():
        key = normalize_stat_key(str(rk))
        if not key:
            continue
        try:
            v = int(rv)
        except Exception:
            v = 0
        out[key] = max(0, min(31, v))
    return out


def ivs31_from_dict(ivs: Dict[str, int]) -> Tuple[str, ...]:
    up_map = {"hp": "HP", "atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}
    return tuple(up_map[k] for k in STAT_KEYS if int(ivs.get(k, 0)) >= 31)


def calculate_stats(
    base_stats: Dict[str, int],
    ivs: Dict[str, int],
    level: int,
    nature_text: str,
    evs: Optional[Dict[str, int]] = None,
) -> Dict[str, int]:
    lvl = max(1, min(100, int(level or 50)))
    iv = canonical_ivs(ivs)
    ev = {k: 0 for k in STAT_KEYS}
    if evs:
        for rk, rv in evs.items():
            key = normalize_stat_key(str(rk))
            if not key:
                continue
            try:
                v = int(rv)
            except Exception:
                v = 0
            ev[key] = max(0, min(252, v))

    base = {k: int(base_stats.get(k, 0) or 0) for k in STAT_KEYS}

    hp = math.floor(((2 * base["hp"] + iv["hp"] + math.floor(ev["hp"] / 4)) * lvl) / 100) + lvl + 10

    nature_name = normalize_nature_name(nature_text)
    up, down = NATURE_CHART.get(nature_name, (None, None))

    out: Dict[str, int] = {"hp": int(hp)}
    for key in ("atk", "def", "spa", "spd", "spe"):
        val = math.floor(((2 * base[key] + iv[key] + math.floor(ev[key] / 4)) * lvl) / 100) + 5
        if up == key:
            val = math.floor(val * 1.1)
        elif down == key:
            val = math.floor(val * 0.9)
        out[key] = int(val)

    out["total"] = sum(out[k] for k in STAT_KEYS)
    return out


@dataclass
class InventoryItem:
    id: str
    species_id: Optional[int] = None
    species_name: str = ""
    gender: str = "U"  # M | F | U
    nature: str = ""
    level: int = 50
    ivs: Dict[str, int] = field(default_factory=lambda: {k: 0 for k in STAT_KEYS})
    egg_groups: List[str] = field(default_factory=list)
    ball: str = ""
    price_paid: int = 0
    notes: str = ""
    box_index: int = 0
    slot_index: int = -1
    sprite_cache_key: str = ""

    @staticmethod
    def create() -> "InventoryItem":
        return InventoryItem(id=str(uuid.uuid4()))

    def ivs_key(self) -> Tuple[str, ...]:
        return tuple(k for k in STAT_KEYS if int(self.ivs.get(k, 0)) >= 31)

    def iv_count_31(self) -> int:
        return len(self.ivs_key())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "species_id": self.species_id,
            "species_name": self.species_name,
            "gender": self.gender,
            "nature": self.nature,
            "level": int(self.level or 50),
            "ivs": canonical_ivs(self.ivs),
            "egg_groups": list(self.egg_groups or []),
            "ball": self.ball,
            "price_paid": int(self.price_paid or 0),
            "notes": self.notes,
            "box_index": int(self.box_index or 0),
            "slot_index": int(self.slot_index if self.slot_index is not None else -1),
            "sprite_cache_key": self.sprite_cache_key,
        }

    @staticmethod
    def _from_legacy_ivs31(ivs31: List[str]) -> Dict[str, int]:
        out = {k: 0 for k in STAT_KEYS}
        for raw in ivs31 or []:
            key = normalize_stat_key(str(raw))
            if not key:
                continue
            out[key] = 31
        return out

    @staticmethod
    def from_dict(data: dict, default_level: int = 50) -> "InventoryItem":
        legacy_ivs31 = [str(x) for x in (data.get("ivs31", []) or []) if str(x)]
        ivs = data.get("ivs") if isinstance(data.get("ivs"), dict) else None
        if ivs is None:
            ivs = InventoryItem._from_legacy_ivs31(legacy_ivs31)

        item = InventoryItem(
            id=str(data.get("id") or str(uuid.uuid4())),
            species_id=int(data["species_id"]) if data.get("species_id") not in (None, "", 0, "0") else None,
            species_name=str(data.get("species_name", "") or ""),
            gender=str(data.get("gender", "U") or "U").upper(),
            nature=str(data.get("nature", "") or ""),
            level=int(data.get("level", default_level) or default_level),
            ivs=canonical_ivs(ivs),
            egg_groups=[str(x) for x in (data.get("egg_groups", []) or []) if str(x)],
            ball=str(data.get("ball", "") or ""),
            price_paid=int(data.get("price_paid", 0) or 0),
            notes=str(data.get("notes", "") or ""),
            box_index=int(data.get("box_index", 0) or 0),
            slot_index=int(data.get("slot_index", -1) if data.get("slot_index", None) is not None else -1),
            sprite_cache_key=str(data.get("sprite_cache_key", "") or ""),
        )
        if item.gender not in ("M", "F", "U"):
            item.gender = "U"
        item.level = max(1, min(100, int(item.level or default_level or 50)))
        if item.price_paid < 0:
            item.price_paid = 0
        return item


@dataclass
class InventorySettings:
    estimated_buy_price_by_iv_count: Dict[int, int] = field(
        default_factory=lambda: {
            1: 20_000,
            2: 40_000,
            3: 80_000,
            4: 160_000,
            5: 320_000,
            6: 640_000,
        }
    )
    default_level: int = 50
    boxes_count: int = 1

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "default_level": int(self.default_level),
            "boxes_count": int(self.boxes_count),
            "estimated_buy_price_by_iv_count": {str(k): int(v) for k, v in self.estimated_buy_price_by_iv_count.items()},
        }

    @staticmethod
    def from_dict(data: dict) -> "InventorySettings":
        raw = (data or {}).get("estimated_buy_price_by_iv_count", {}) or {}
        out: Dict[int, int] = {}
        for k, v in raw.items():
            try:
                ik = int(k)
                iv = int(v)
            except Exception:
                continue
            if ik < 1 or ik > 6:
                continue
            out[ik] = max(0, iv)
        base = InventorySettings()
        if out:
            base.estimated_buy_price_by_iv_count.update(out)
        try:
            base.default_level = max(1, min(100, int((data or {}).get("default_level", base.default_level))))
        except Exception:
            pass
        try:
            base.boxes_count = max(1, int((data or {}).get("boxes_count", 1)))
        except Exception:
            pass
        return base


@dataclass
class InventoryRequirement:
    node_key: Tuple[int, int]
    species_id: Optional[int]
    species_name: str = ""
    egg_groups: Tuple[str, ...] = field(default_factory=tuple)
    gender: str = "M"
    ivs31: Tuple[str, ...] = field(default_factory=tuple)  # lower-case stat keys
    has_nature: bool = False
    nature: str = ""


@dataclass
class InventoryMatchReport:
    used_items: List[Tuple[Tuple[int, int], str]] = field(default_factory=list)
    node_assignments: Dict[Tuple[int, int], str] = field(default_factory=dict)
    missing_nodes: List[Tuple[int, int]] = field(default_factory=list)
    estimated_buy_cost_total: int = 0
    inventory_used_count: int = 0
    purchase_count: int = 0
    estimated_savings: int = 0
    purchased_by_iv_count: Dict[int, int] = field(default_factory=dict)
    used_by_iv_count: Dict[int, int] = field(default_factory=dict)


class InventoryStore:
    def __init__(self, inventory_path: str, settings_path: str):
        self.inventory_path = inventory_path
        self.settings_path = settings_path

    def load_settings(self) -> InventorySettings:
        if not os.path.exists(self.settings_path):
            cfg = InventorySettings()
            self.save_settings(cfg)
            return cfg
        try:
            with open(self.settings_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f) or {}
            return InventorySettings.from_dict(data)
        except Exception:
            return InventorySettings()

    def save_settings(self, cfg: InventorySettings) -> None:
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)

    def _assign_missing_slots(self, items: List[InventoryItem], slots_per_box: int = 40) -> None:
        occupied = {(it.box_index, it.slot_index) for it in items if it.slot_index >= 0}
        cursor_box = 0
        cursor_slot = 0
        for it in items:
            if it.slot_index >= 0:
                continue
            while (cursor_box, cursor_slot) in occupied:
                cursor_slot += 1
                if cursor_slot >= slots_per_box:
                    cursor_box += 1
                    cursor_slot = 0
            it.box_index = cursor_box
            it.slot_index = cursor_slot
            occupied.add((cursor_box, cursor_slot))

    def load_items(self) -> List[InventoryItem]:
        settings = self.load_settings()
        if not os.path.exists(self.inventory_path):
            self.save_items([])
            return []
        migrated = False
        try:
            with open(self.inventory_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f) or {}
            version = int(data.get("version", 1) or 1)
            raw_items = [x for x in (data.get("items", []) or []) if isinstance(x, dict)]
            items = [InventoryItem.from_dict(x, default_level=settings.default_level) for x in raw_items]
            if version < 2:
                migrated = True
            if any(it.slot_index < 0 for it in items):
                migrated = True
            self._assign_missing_slots(items)
            if migrated:
                self.save_items(items)
            return items
        except Exception:
            return []

    def save_items(self, items: List[InventoryItem]) -> None:
        os.makedirs(os.path.dirname(self.inventory_path), exist_ok=True)
        payload = {
            "version": 2,
            "items": [x.to_dict() for x in items],
        }
        with open(self.inventory_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def import_items(self, src_path: str) -> List[InventoryItem]:
        settings = self.load_settings()
        with open(src_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f) or {}
        items = [InventoryItem.from_dict(x, default_level=settings.default_level) for x in (data.get("items", []) or []) if isinstance(x, dict)]
        self._assign_missing_slots(items)
        self.save_items(items)
        return items

    def export_items(self, dst_path: str, items: List[InventoryItem]) -> None:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        payload = {
            "version": 2,
            "items": [x.to_dict() for x in items],
        }
        with open(dst_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)


class InventoryMatcher:
    @staticmethod
    def _norm_nature(nature: str) -> str:
        return normalize_nature_name(nature)

    @staticmethod
    def _estimate_buy_cost(iv_count: int, settings: InventorySettings) -> int:
        return int(settings.estimated_buy_price_by_iv_count.get(iv_count, 0) or 0)

    @staticmethod
    def _is_ditto(item: InventoryItem) -> bool:
        return (item.species_name or "").strip().lower() == "ditto" or int(item.species_id or 0) == 132

    def _species_rank(self, req: InventoryRequirement, item: InventoryItem, allow_compatible: bool) -> Optional[int]:
        if item.species_id and req.species_id and item.species_id == req.species_id:
            return 0
        if item.species_id:
            if not allow_compatible:
                return None
            item_groups = {g.strip().lower() for g in (item.egg_groups or []) if g}
            req_groups = {g.strip().lower() for g in (req.egg_groups or []) if g}
            if self._is_ditto(item):
                return 1
            if item_groups and req_groups and item_groups.intersection(req_groups):
                return 1
            return None
        return 2

    def match(
        self,
        requirements: List[InventoryRequirement],
        items: List[InventoryItem],
        settings: InventorySettings,
        allow_compatible: bool,
    ) -> InventoryMatchReport:
        report = InventoryMatchReport()
        if not requirements:
            return report

        used_item_ids: Set[str] = set()
        req_order = sorted(
            requirements,
            key=lambda r: (
                -self._estimate_buy_cost(len(r.ivs31), settings),
                -len(r.ivs31),
                0 if r.has_nature else 1,
                r.node_key[0],
                r.node_key[1],
            ),
        )

        baseline_total = 0
        for req in req_order:
            iv_count = len(req.ivs31)
            req_buy_cost = self._estimate_buy_cost(iv_count, settings)
            baseline_total += req_buy_cost

            req_nature = self._norm_nature(req.nature) if req.has_nature else ""
            candidates: List[Tuple[int, int, int, int, str, InventoryItem]] = []
            for item in items:
                if item.id in used_item_ids:
                    continue

                gender_rank = 0
                if req.gender in ("M", "F"):
                    if item.gender == req.gender:
                        gender_rank = 0
                    elif item.gender == "U":
                        gender_rank = 1
                    else:
                        continue

                ok_ivs = True
                for stat_key in req.ivs31:
                    k = normalize_stat_key(stat_key)
                    if not k or int(item.ivs.get(k, 0)) < 31:
                        ok_ivs = False
                        break
                if not ok_ivs:
                    continue

                item_nature = self._norm_nature(item.nature)
                if req.has_nature and item_nature != req_nature:
                    continue

                species_rank = self._species_rank(req, item, allow_compatible)
                if species_rank is None:
                    continue

                nature_rank = 0 if (not req.has_nature or item_nature == req_nature) else 1
                item_31 = set(item.ivs_key())
                req_31 = {normalize_stat_key(s) for s in req.ivs31 if normalize_stat_key(s)}
                waste = max(0, len(item_31 - req_31))
                price_paid = int(item.price_paid or 0)
                candidates.append((species_rank, nature_rank, gender_rank, waste, price_paid, item.id, item))

            if not candidates:
                report.missing_nodes.append(req.node_key)
                report.estimated_buy_cost_total += req_buy_cost
                report.purchase_count += 1
                report.purchased_by_iv_count[iv_count] = report.purchased_by_iv_count.get(iv_count, 0) + 1
                continue

            candidates.sort(key=lambda x: (x[0], x[1], x[2], x[3], x[4], x[5]))
            chosen = candidates[0][6]
            used_item_ids.add(chosen.id)
            report.used_items.append((req.node_key, chosen.id))
            report.node_assignments[req.node_key] = chosen.id
            report.inventory_used_count += 1
            report.used_by_iv_count[iv_count] = report.used_by_iv_count.get(iv_count, 0) + 1

        report.estimated_savings = max(0, baseline_total - report.estimated_buy_cost_total)
        return report
