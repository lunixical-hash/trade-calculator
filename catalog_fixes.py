"""Shared catalog cleanup for MM2 values / trade calculator."""

from __future__ import annotations

import math
from typing import Any

# Reject history points outside [ref/factor, ref*factor]. Contaminated scrapes
# often inject another item's value (60 on a 220k chroma, 1e6 on Batwing); real
# MM2 moves stay well inside this band.
HISTORY_SCALE_FACTOR = 25.0

# bootstrap_history.py once invented "prior" points via value/(1+pct/100).
# Those are never real SV ticks (SV publishes integer values).
_SYNTHETIC_EPS = 1e-6

# Scraper sometimes puts these on the wrong page / with placeholder stats
RARITY_OVERRIDES: dict[str, str] = {
    "Batwing": "Ancient",
}

# Force correct Supreme Values stats when scrape picks up junk (e.g. 1,000,000)
VALUE_OVERRIDES: dict[str, float] = {
    "Batwing": 42.0,
}

DEMAND_OVERRIDES: dict[str, int] = {
    "Batwing": 1,
}

RARITY_SCORE_OVERRIDES: dict[str, int] = {
    "Batwing": 2,
}

# Not tradeable / not useful in a values calculator
UNOBTAINABLE_IDS: set[str] = {
    "BlackLuger",
    "MortalBlade",
}

# Bad scrape rows that duplicate a real SV item under another id
DUPLICATE_IDS: set[str] = {
    "SunriseGun",  # duplicate of Sunrise
    "SunsetKnife",  # duplicate of Sunset
    "SunriseKnife",  # mislabeled Sunset duplicate
}

EXCLUDE_FROM_CALCULATOR: set[str] = UNOBTAINABLE_IDS | DUPLICATE_IDS

# Junk / bulk sets that shouldn't appear in the trade calculator
EXCLUDE_SET_IDS: set[str] = {
    "ChromaWeaponSet",
    "FullChromaSet",
    "SmallSet103",
    "SmallSet107",
}

# Drop low-value set listings (individual weapons stay)
MIN_SET_VALUE_FOR_CALCULATOR = 50.0

# Bad scrape ids -> correct SV / game ids
ID_RENAMES: dict[str, str] = {
    "SpecialTierNiksScythe": "Gingerscope",  # image is Gingerscope; popup text was wrong
}

DISPLAY_NAME_OVERRIDES: dict[str, str] = {
    "Gingerscope": "Gingerscope",
}

# Sets whose SV page omits a "Contains - …" list (or needs a forced mapping).
# Only include pairs that sum-check against the set value in mm2_values.json.
SET_MEMBER_OVERRIDES: dict[str, list[str]] = {
    # Chroma knife+gun sets
    "ChromaSnowSet": ["ChromaSnowcannon", "ChromaSnowDagger"],
    "ChromaBlizzardSet": ["ChromaBlizzard", "ChromaSnowstorm"],
    "ChromaBringerSet": ["ChromaDarkbringer", "ChromaLightbringer"],
    "ChromaSunSet": ["ChromaSunrise", "ChromaSunset"],
    "ChromaEverSet": ["ChromaEvergun", "ChromaEvergreen"],
    "ChromaBeachSet": ["ChromaBeachy", "ChromaSands"],
    "ChromaAlienSet": ["ChromaAlienbeam", "ChromaRaygun"],
    "ChromaBaubleSet": ["ChromaBauble", "ChromaOrnament"],
    "ChromaSweetSet": ["ChromaSweet", "ChromaTreat"],
    "ChromaSlasherSet": ["ChromaLaser", "ChromaSlasher"],
    # Matching godly sets
    "SunSet": ["Sunrise", "Sunset"],
    "EverSet": ["Evergun", "Evergreen"],
    "BeachSet": ["Beachy", "Sands"],
    "AlienSet": ["Alienbeam", "Raygun"],
    "BaubleSet": ["Bauble", "Ornament"],
    "SweetSet": ["Sweet", "Treat"],
    "BringerSet": ["Darkbringer", "Lightbringer"],
    "SnowSet": ["Snowcannon", "SnowDagger"],
    "BlizzardSet": ["Blizzard", "Snowstorm"],
    "DarkSet": ["Darkshot", "Darksword"],
    "SakuraSet": ["Sakura", "Blossom"],
    "SoulSet": ["Soul", "Spirit"],
    "CelestialSet": ["Celestial", "Constellation"],
    "HallowSet": ["Hallowgun", "Hallowscythe"],
    "TravelersSet": ["TravelersGun", "TravelersAxe"],
    "VampiresSet": ["VampireGun", "VampiresAxe"],
    "BorealisSet": ["Borealis", "Australis"],
    "SwirlySet": ["SwirlyGun", "SwirlyAxe"],
    "CandySet": ["Candy", "Sugar"],
    "RainbowSet": ["Rainbow", "RainbowGun"],
    "XenoSet": ["Xenoshot", "Xenoknife"],
    "FlowerwoodSet": ["FlowerwoodGun", "Flowerwood"],
    "PearlSet": ["Pearl", "Pearlshine"],
}


def _is_canonical_sv_value(v: float, ref: float | None) -> bool:
    """SV chart ticks are whole numbers; reject reverse-% bootstrap fractions."""
    if not math.isfinite(v):
        return False
    # Always allow exact integers.
    if abs(v - round(v)) <= _SYNTHETIC_EPS:
        return True
    # If the live value is an integer (normal for MM2), non-integers are junk.
    if ref is not None and abs(ref - round(ref)) <= _SYNTHETIC_EPS:
        return False
    # Otherwise allow half-units only (rare / legacy).
    return abs(v * 2 - round(v * 2)) <= _SYNTHETIC_EPS


def _looks_like_reverse_pct_prior(
    v: float,
    current_value: float | None,
    change_pct: float | None,
) -> bool:
    if (
        current_value is None
        or change_pct is None
        or not math.isfinite(current_value)
        or not math.isfinite(change_pct)
        or abs(change_pct) < 1e-9
        or current_value <= 0
    ):
        return False
    expected = current_value / (1.0 + change_pct / 100.0)
    return abs(v - expected) <= max(1e-6, abs(expected) * 1e-9)


def _normalize_history_point(p: dict) -> dict[str, Any] | None:
    v = p.get("v")
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    fv = float(v)
    if not math.isfinite(fv) or fv < 0:
        return None
    pt: dict[str, Any] = {"v": fv}
    if isinstance(p.get("t"), (int, float)) and not isinstance(p.get("t"), bool):
        pt["t"] = int(p["t"])
    label = p.get("label")
    if isinstance(label, str) and label.strip():
        pt["label"] = label.strip()
    return pt


def _coalesce_flat_runs(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse consecutive equal values; keep earliest labeled point of each run.

    Repeated scrapes used to append the same tip with a new scrape timestamp,
    which stretched charts with fake 'moves' that were only date noise.
    """
    if not points:
        return []
    out: list[dict[str, Any]] = []
    for p in points:
        if out and abs(out[-1]["v"] - p["v"]) < _SYNTHETIC_EPS:
            prev = out[-1]
            # Prefer a point that already has an SV-style label / older stamp.
            prev_has_label = "label" in prev
            cur_has_label = "label" in p
            if cur_has_label and not prev_has_label:
                out[-1] = p
            elif (
                "t" in prev
                and "t" in p
                and cur_has_label == prev_has_label
                and p["t"] < prev["t"]
            ):
                out[-1] = p
            continue
        out.append(p)
    return out


def sanitize_item_history(
    history: list | None,
    current_value: float | int | None = None,
    *,
    scale_factor: float = HISTORY_SCALE_FACTOR,
    change_pct: float | int | None = None,
) -> list[dict[str, Any]]:
    """Keep only real, same-scale history points for an item.

    Drops:
      - wrong-scale contamination from bad scrapes
      - synthetic reverse-% bootstrap priors (non-integer / unlabeled pct-derived)
      - consecutive duplicate values from repeated scrapes

    Does not invent dates. Legitimate integer moves inside the scale band stay.
    """
    if not isinstance(history, list):
        return []

    ref: float | None = None
    if (
        isinstance(current_value, (int, float))
        and not isinstance(current_value, bool)
        and current_value > 0
        and math.isfinite(float(current_value))
    ):
        ref = float(current_value)

    pct: float | None = None
    if (
        isinstance(change_pct, (int, float))
        and not isinstance(change_pct, bool)
        and math.isfinite(float(change_pct))
    ):
        pct = float(change_pct)

    points: list[dict[str, Any]] = []
    for p in history:
        if not isinstance(p, dict):
            continue
        had_label = isinstance(p.get("label"), str) and bool(p["label"].strip())
        pt = _normalize_history_point(p)
        if pt is None:
            continue
        fv = pt["v"]
        if not _is_canonical_sv_value(fv, ref):
            continue
        # Only drop reverse-% priors when unlabeled (bootstrap invented those).
        # Labeled SV ticks that happen to match value/(1+pct) are real.
        if not had_label and _looks_like_reverse_pct_prior(fv, ref, pct):
            continue
        points.append(pt)

    if not points:
        return []

    if ref is None:
        positive = sorted(p["v"] for p in points if p["v"] > 0)
        if positive:
            ref = positive[len(positive) // 2]

    if ref is not None and ref > 0 and scale_factor > 1:
        lo = ref / scale_factor
        hi = ref * scale_factor
        points = [
            p
            for p in points
            if not (p["v"] <= 0 and ref >= 1) and lo <= p["v"] <= hi
        ]

    points.sort(
        key=lambda p: (
            p.get("t") is None,
            p.get("t") or 0,
            # Do not sort by value — same-second SV ticks must keep source order.
            0,
        )
    )
    return _coalesce_flat_runs(points)


def apply_to_values_payload(data: dict) -> dict:
    """Mutate mm2_values-style payload in place and return it."""
    items = data.setdefault("items", {})
    rarities = data.setdefault("rarities", {})
    meta = data.setdefault("meta", {})
    images = data.setdefault("images", {})
    displays = data.setdefault("displayNames", {})

    # Rename mis-scraped ids across all maps
    for old_id, new_id in ID_RENAMES.items():
        if old_id == new_id:
            continue
        for bucket in (items, rarities, meta, images, displays):
            if old_id in bucket and new_id not in bucket:
                bucket[new_id] = bucket.pop(old_id)
            else:
                bucket.pop(old_id, None)
        for key in ("aliases", "svToGame", "manualSvToGame"):
            mapping = data.get(key)
            if not isinstance(mapping, dict):
                continue
            for k, v in list(mapping.items()):
                if k == old_id:
                    val = mapping.pop(k)
                    mapping.setdefault(new_id, val)
                elif v == old_id:
                    mapping[k] = new_id

    for item_id, name in DISPLAY_NAME_OVERRIDES.items():
        if item_id in items or item_id in displays:
            displays[item_id] = name

    for item_id, rarity in RARITY_OVERRIDES.items():
        if item_id in rarities or item_id in items:
            rarities[item_id] = rarity
        img = images.get(item_id) or ""
        if item_id == "Batwing" and "/mm2godlies/" in img:
            images[item_id] = img.replace("/mm2godlies/", "/mm2ancients/")

    for item_id, value in VALUE_OVERRIDES.items():
        if item_id in items:
            items[item_id] = float(value)

    for item_id, demand in DEMAND_OVERRIDES.items():
        entry = meta.setdefault(item_id, {})
        if isinstance(entry, dict):
            entry["demand"] = int(demand)

    for item_id, score in RARITY_SCORE_OVERRIDES.items():
        entry = meta.setdefault(item_id, {})
        if isinstance(entry, dict):
            entry["rarityScore"] = int(score)

    for item_id in UNOBTAINABLE_IDS:
        entry = meta.setdefault(item_id, {})
        if isinstance(entry, dict):
            entry["unobtainable"] = True

    # Drop scrape duplicates from the main maps so they don't linger
    for key in ("items", "displayNames", "images", "rarities", "meta"):
        bucket = data.get(key)
        if not isinstance(bucket, dict):
            continue
        for item_id in DUPLICATE_IDS:
            bucket.pop(item_id, None)

    # Strip scale-outlier / synthetic history left by bad scrapes / bootstraps
    for item_id, entry in list(meta.items()):
        if not isinstance(entry, dict):
            continue
        hist = entry.get("history")
        if not isinstance(hist, list) or not hist:
            continue
        cur = items.get(item_id)
        pct = entry.get("changePct")
        cleaned = sanitize_item_history(
            hist,
            cur if isinstance(cur, (int, float)) else None,
            change_pct=pct if isinstance(pct, (int, float)) else None,
        )
        entry["history"] = cleaned

    if "count" in data and isinstance(data.get("items"), dict):
        data["count"] = len(data["items"])
    return data


def clean_set_display_name(name: str, rarity: str) -> str:
    """Turn 'Alien Set Contains - …' into 'Alien Set'."""
    if rarity == "Set" and " Contains" in name:
        return name.split(" Contains", 1)[0].strip()
    return name
