"""Build MM2 trade calculator HTML from raw Supreme Values (pre-alias names)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from catalog_fixes import (
    EXCLUDE_FROM_CALCULATOR,
    EXCLUDE_SET_IDS,
    MIN_SET_VALUE_FOR_CALCULATOR,
    RARITY_OVERRIDES,
    SET_MEMBER_OVERRIDES,
    apply_to_values_payload,
    clean_set_display_name,
    sanitize_item_history,
)

ROOT = Path(__file__).resolve().parent
VALUES = ROOT / "mm2_values.json"
OUT = ROOT / "trade_calculator.html"


def fmt(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if abs(n) >= 1000:
        return f"{n:,.0f}"
    if n == int(n):
        return str(int(n))
    return f"{n:g}"


def image_short_alias(url: str) -> str | None:
    if not url:
        return None
    name = url.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    if not stem or stem in {"N_A", "na", "unknown"}:
        return None
    # Prefer short codes like CRG / CAB
    if 1 < len(stem) <= 8 and stem.replace("_", "").isalnum():
        return stem
    return None


def alias_list_for(sv_id: str, m: dict, reverse: dict[str, list[str]], image: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(x: str | None) -> None:
        if not x:
            return
        s = str(x).strip()
        if not s or s in seen or s == sv_id:
            return
        seen.add(s)
        out.append(s)

    raw = m.get("aliases")
    if isinstance(raw, str):
        for part in raw.replace(";", ",").split(","):
            add(part)
    elif isinstance(raw, list):
        for part in raw:
            add(str(part))

    for game_id in reverse.get(sv_id, []):
        add(game_id)

    add(image_short_alias(image))
    return out


def _norm_name(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"\s*\[.*?\]\s*", " ", s)
    s = s.replace("'s", "s").replace("'", "")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_set_member_names(display_name: str) -> list[str]:
    if " Contains" not in display_name:
        return []
    after = display_name.split(" Contains", 1)[1]
    after = after.lstrip(" -–—").strip()
    if not after:
        return []
    # Skip vague bulk sets ("All …")
    if re.match(r"(?i)^all\b", after):
        return []
    parts = re.split(r"\s*[+,]\s*", after)
    out = []
    for part in parts:
        name = part.strip()
        if not name:
            continue
        if re.match(r"(?i)^all\b", name):
            return []
        out.append(name)
    return out


def build_name_index(
    items: dict, displays: dict, rarities: dict, aliases: set[str]
) -> dict[str, str]:
    """Normalized display name -> sv id (prefer non-set items)."""
    index: dict[str, str] = {}
    # First pass: non-sets
    for sv_id in items:
        if sv_id in aliases or sv_id in EXCLUDE_FROM_CALCULATOR:
            continue
        rarity = RARITY_OVERRIDES.get(sv_id) or rarities.get(sv_id) or "Unknown"
        if rarity in {"Pet", "Set"}:
            continue
        raw = displays.get(sv_id, sv_id)
        for key in (raw, clean_set_display_name(raw, rarity)):
            n = _norm_name(key)
            if n and n not in index:
                index[n] = sv_id
    # Second: sets (for nested expansion)
    for sv_id in items:
        if sv_id in aliases or sv_id in EXCLUDE_FROM_CALCULATOR:
            continue
        rarity = RARITY_OVERRIDES.get(sv_id) or rarities.get(sv_id) or "Unknown"
        if rarity != "Set":
            continue
        raw = displays.get(sv_id, sv_id)
        for key in (raw, clean_set_display_name(raw, rarity), sv_id):
            n = _norm_name(key)
            if n and n not in index:
                index[n] = sv_id
    return index


def resolve_set_leaves(
    set_id: str,
    items: dict,
    displays: dict,
    rarities: dict,
    name_index: dict[str, str],
    memo: dict[str, list[str] | None],
    stack: set[str],
    alias_to_canonical: dict[str, str] | None = None,
) -> list[str] | None:
    """Fully expand a set to non-set item ids, or None if incomplete."""
    if set_id in memo:
        return memo[set_id]
    if set_id in stack:
        memo[set_id] = None
        return None
    stack.add(set_id)

    alias_to_canonical = alias_to_canonical or {}

    def canon(mid: str) -> str:
        # Prefer non-alias catalog ids (game-id aliases are excluded from the calculator)
        target = alias_to_canonical.get(mid)
        if isinstance(target, str) and target in items:
            return target
        return mid

    if set_id in SET_MEMBER_OVERRIDES:
        member_ids = [canon(mid) for mid in SET_MEMBER_OVERRIDES[set_id]]
    else:
        names = parse_set_member_names(displays.get(set_id, set_id))
        if not names:
            stack.remove(set_id)
            memo[set_id] = None
            return None
        member_ids = []
        for name in names:
            hit = name_index.get(_norm_name(name))
            if not hit:
                stack.remove(set_id)
                memo[set_id] = None
                return None
            member_ids.append(canon(hit))

    leaves: list[str] = []
    for mid in member_ids:
        mid = canon(mid)
        if mid not in items:
            stack.remove(set_id)
            memo[set_id] = None
            return None
        rarity = RARITY_OVERRIDES.get(mid) or rarities.get(mid) or "Unknown"
        if rarity == "Set":
            nested = resolve_set_leaves(
                mid, items, displays, rarities, name_index, memo, stack, alias_to_canonical
            )
            if nested is None:
                stack.remove(set_id)
                memo[set_id] = None
                return None
            leaves.extend(nested)
        else:
            leaves.append(mid)

    # Dedupe while preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for mid in leaves:
        if mid in seen:
            continue
        seen.add(mid)
        uniq.append(mid)

    stack.remove(set_id)
    memo[set_id] = uniq
    return uniq


def main() -> None:
    d = apply_to_values_payload(json.loads(VALUES.read_text(encoding="utf-8")))
    items = d.get("items") or {}
    displays = d.get("displayNames") or {}
    images = d.get("images") or {}
    rarities = d.get("rarities") or {}
    meta = d.get("meta") or {}
    aliases_map = d.get("aliases") or {}
    aliases = set(aliases_map.keys())
    trending_raw = d.get("trending") if isinstance(d.get("trending"), list) else []

    reverse: dict[str, list[str]] = {}
    for game_id, sv_id in aliases_map.items():
        if isinstance(game_id, str) and isinstance(sv_id, str):
            reverse.setdefault(sv_id, []).append(game_id)

    # Alias id -> canonical sv id (calculator catalog drops alias rows)
    alias_to_canonical = {
        game_id: sv_id
        for game_id, sv_id in aliases_map.items()
        if isinstance(game_id, str) and isinstance(sv_id, str)
    }

    name_index = build_name_index(items, displays, rarities, aliases)
    set_memo: dict[str, list[str] | None] = {}

    catalog = []
    for sv_id, value in items.items():
        if sv_id in aliases:
            continue  # game-id aliases only — keep raw SV names
        if sv_id in EXCLUDE_FROM_CALCULATOR:
            continue
        m = meta.get(sv_id) or {}
        if m.get("unobtainable"):
            continue
        rarity = RARITY_OVERRIDES.get(sv_id) or rarities.get(sv_id) or "Unknown"
        if rarity in {"Pet"}:
            continue
        if rarity == "Set":
            if sv_id in EXCLUDE_SET_IDS:
                continue
            try:
                set_val = float(value)
            except (TypeError, ValueError):
                set_val = 0.0
            if set_val < MIN_SET_VALUE_FOR_CALCULATOR:
                continue
        raw_name = displays.get(sv_id, sv_id)
        image = images.get(sv_id) or ""
        history = m.get("history") if isinstance(m.get("history"), list) else []
        change_pct = m.get("changePct")
        if not isinstance(change_pct, (int, float)):
            change_pct = None
        hist_clean = sanitize_item_history(
            history,
            value if isinstance(value, (int, float)) else None,
            change_pct=change_pct,
        )
        entry = {
            "id": sv_id,
            "name": clean_set_display_name(raw_name, rarity),
            "value": float(value) if isinstance(value, (int, float)) else 0,
            "image": image,
            "rarity": rarity,
            "demand": m.get("demand"),
            "rarityScore": m.get("rarityScore"),
            "stability": m.get("stability"),
            "origin": m.get("origin"),
            "change": m.get("change"),
            "changePct": change_pct,
            "history": hist_clean,
            "aliases": alias_list_for(sv_id, m, reverse, image),
        }
        if rarity == "Set":
            leaves = resolve_set_leaves(
                sv_id,
                items,
                displays,
                rarities,
                name_index,
                set_memo,
                set(),
                alias_to_canonical,
            )
            if leaves:
                # Only keep members that will exist as catalog rows
                entry["members"] = [
                    mid for mid in leaves if mid not in aliases and mid in items
                ]
                if len(entry["members"]) < 2:
                    entry.pop("members", None)
        catalog.append(entry)

    catalog.sort(key=lambda r: (-r["value"], r["name"].lower()))
    data_json = json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    trending_json = json.dumps(trending_raw, ensure_ascii=False, separators=(",", ":"))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Lunix's AI Trade Assistant</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;600;700;800&family=Syne:wght@700;800&display=swap" rel="stylesheet" />
<style>
  :root {{
    --bg: #07060c;
    --bg-top: #0b0914;
    --bg-bottom: #030208;
    --card: #12101a;
    --card-2: #1a1626;
    --text: #f4efff;
    --muted: #9a90b3;
    --line: #2a2438;
    --line-strong: #3b3352;
    --purple: #a855f7;
    --purple-bright: #c084fc;
    --purple-deep: #7c3aed;
    --purple-pale: #e9d5ff;
    --purple-rgb: 168, 85, 247;
    --purple-bright-rgb: 192, 132, 252;
    --purple-deep-rgb: 124, 58, 237;
    --accent-shift-rgb: 56, 189, 248;
    --accent-warm-rgb: 52, 211, 153;
    --accent-soft-rgb: 216, 180, 254;
    --red: #f04444;
    --red-dark: #d63232;
    --green: #3dd68c;
    --green-soft: #34d399;
    --shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
    --scrollbar-size: 4px;
    --scrollbar-thumb: rgba(var(--purple-rgb), 0.22);
    --scrollbar-track: transparent;
  }}
  * {{
    box-sizing: border-box;
    scrollbar-width: thin;
    scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);
  }}
  /* Subtle themed scrollbars — Firefox above, WebKit below.
     No CSS scroll-behavior:smooth (feels laggy on wheel); JS uses behavior:'smooth' for programmatic scrolls. */
  *::-webkit-scrollbar {{
    width: var(--scrollbar-size);
    height: var(--scrollbar-size);
  }}
  *::-webkit-scrollbar-track {{
    background: var(--scrollbar-track);
  }}
  *::-webkit-scrollbar-thumb {{
    background: rgba(var(--purple-rgb), 0.22);
    border-radius: 999px;
  }}
  *::-webkit-scrollbar-thumb:hover {{
    background: rgba(var(--purple-bright-rgb), 0.4);
  }}
  *::-webkit-scrollbar-thumb:active {{
    background: rgba(var(--purple-rgb), 0.5);
  }}
  *::-webkit-scrollbar-corner {{
    background: transparent;
  }}
  body {{
    margin: 0;
    min-height: 100vh;
    font-family: "Outfit", system-ui, sans-serif;
    color: var(--text);
    background:
      radial-gradient(1100px 640px at 12% -8%, rgba(var(--accent-shift-rgb), 0.09) 0%, transparent 52%),
      radial-gradient(980px 560px at 88% 8%, rgba(var(--purple-rgb), 0.18) 0%, transparent 48%),
      radial-gradient(900px 720px at 50% 108%, rgba(var(--accent-warm-rgb), 0.07) 0%, transparent 55%),
      linear-gradient(168deg, var(--bg-top) 0%, var(--bg) 42%, var(--bg-bottom) 100%);
    overflow-x: hidden;
  }}
  .bg-ambient {{
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    overflow: hidden;
    background:
      radial-gradient(820px 480px at 48% -12%, rgba(var(--purple-rgb), 0.2) 0%, transparent 58%),
      radial-gradient(640px 420px at 100% 28%, rgba(var(--accent-shift-rgb), 0.1) 0%, transparent 52%),
      radial-gradient(700px 500px at 0% 70%, rgba(var(--purple-deep-rgb), 0.12) 0%, transparent 55%),
      radial-gradient(560px 400px at 70% 90%, rgba(var(--accent-warm-rgb), 0.06) 0%, transparent 50%);
  }}
  .bg-ambient::before {{
    content: "";
    position: absolute;
    inset: -45%;
    background:
      radial-gradient(ellipse 42% 34% at 22% 30%, rgba(var(--purple-rgb), 0.28), transparent 70%),
      radial-gradient(ellipse 38% 32% at 78% 24%, rgba(var(--accent-shift-rgb), 0.16), transparent 68%),
      radial-gradient(ellipse 40% 36% at 58% 78%, rgba(var(--purple-deep-rgb), 0.2), transparent 70%),
      radial-gradient(ellipse 34% 30% at 18% 82%, rgba(var(--accent-warm-rgb), 0.1), transparent 65%),
      radial-gradient(ellipse 42% 34% at 122% 130%, rgba(var(--purple-rgb), 0.28), transparent 70%),
      radial-gradient(ellipse 38% 32% at 178% 124%, rgba(var(--accent-shift-rgb), 0.16), transparent 68%);
    background-size: 200% 200%;
    background-position: 0% 0%;
    animation: auroraMesh 36s linear infinite;
    opacity: 0.85;
    mix-blend-mode: screen;
  }}
  .bg-ambient::after {{
    content: "";
    position: absolute;
    inset: 0;
    background:
      linear-gradient(125deg, transparent 0%, rgba(var(--purple-bright-rgb), 0.04) 35%, transparent 55%, rgba(var(--accent-shift-rgb), 0.035) 72%, transparent 100%);
    background-size: 220% 220%;
    animation: auroraSheen 22s ease-in-out infinite;
    opacity: 0.9;
  }}
  .bg-blob {{
    position: absolute;
    width: 48vw;
    height: 48vw;
    min-width: 320px;
    min-height: 320px;
    border-radius: 50%;
    filter: blur(52px);
    opacity: var(--peak, 0.55);
    will-change: opacity, transform;
    mix-blend-mode: screen;
    background: radial-gradient(circle, rgba(var(--purple-bright-rgb), 0.72) 0%, rgba(var(--purple-rgb), 0.28) 40%, transparent 70%);
    animation-name: blobDrift;
    animation-timing-function: ease-in-out;
    animation-iteration-count: infinite;
  }}
  .bg-blob.b2 {{
    background: radial-gradient(circle, rgba(var(--accent-shift-rgb), 0.55) 0%, rgba(var(--purple-deep-rgb), 0.28) 42%, transparent 70%);
  }}
  .bg-blob.b3 {{
    background: radial-gradient(circle, rgba(var(--accent-soft-rgb), 0.62) 0%, rgba(var(--purple-rgb), 0.24) 40%, transparent 68%);
  }}
  .bg-blob.b4 {{
    background: radial-gradient(circle, rgba(var(--accent-warm-rgb), 0.4) 0%, rgba(var(--purple-deep-rgb), 0.22) 46%, transparent 70%);
  }}
  .bg-blob.b5 {{
    background: radial-gradient(circle, rgba(var(--accent-soft-rgb), 0.48) 0%, rgba(var(--accent-shift-rgb), 0.16) 44%, transparent 68%);
  }}
  .bg-blob.b6 {{
    background: radial-gradient(circle, rgba(var(--purple-deep-rgb), 0.58) 0%, rgba(var(--purple-rgb), 0.18) 45%, transparent 70%);
  }}
  .bg-cursor-glow {{
    position: absolute;
    width: 280px;
    height: 280px;
    margin: -140px 0 0 -140px;
    border-radius: 50%;
    pointer-events: none;
    background: radial-gradient(circle, rgba(var(--accent-soft-rgb), 0.28) 0%, rgba(var(--purple-rgb), 0.12) 35%, transparent 70%);
    filter: blur(18px);
    opacity: 0;
    transform: translate3d(-9999px, -9999px, 0);
    transition: opacity .35s ease;
    mix-blend-mode: screen;
    will-change: transform, opacity;
  }}
  .bg-cursor-glow.on {{
    opacity: 1;
  }}
  .cursor-trail {{
    position: fixed;
    inset: 0;
    z-index: 2;
    pointer-events: none;
    overflow: hidden;
  }}
  .trail-dot {{
    position: absolute;
    width: 7px;
    height: 7px;
    margin: -3.5px 0 0 -3.5px;
    border-radius: 50%;
    background: rgba(var(--accent-soft-rgb), 0.55);
    box-shadow: 0 0 10px rgba(var(--purple-rgb), 0.35);
    opacity: 0;
    will-change: transform, opacity;
    pointer-events: none;
  }}

  /* Background variants (tinted by theme vars) */
  body[data-bg-variant="mesh"] .bg-ambient::before {{
    inset: -60%;
    background-size: 160% 160%;
    animation: auroraMesh 28s linear infinite;
    opacity: 1;
    filter: saturate(1.15);
  }}
  body[data-bg-variant="mesh"] .bg-ambient::after {{
    background:
      repeating-linear-gradient(
        115deg,
        transparent 0 48px,
        rgba(var(--purple-rgb), 0.03) 48px 50px
      ),
      linear-gradient(125deg, transparent 0%, rgba(var(--purple-bright-rgb), 0.05) 40%, transparent 58%, rgba(var(--accent-shift-rgb), 0.04) 78%, transparent 100%);
    animation: auroraSheen 18s ease-in-out infinite;
  }}
  body[data-bg-variant="mesh"] .bg-blob {{
    opacity: calc(var(--peak, 0.55) * 0.35);
    filter: blur(64px);
  }}

  body[data-bg-variant="blobs"] .bg-ambient::before {{
    opacity: 0.22;
    animation: none;
    background-position: 30% 40%;
  }}
  body[data-bg-variant="blobs"] .bg-ambient::after {{
    opacity: 0.35;
    animation: none;
  }}
  body[data-bg-variant="blobs"] .bg-blob {{
    filter: blur(44px);
    animation-name: blobDrift;
    animation-duration: 7s;
  }}

  body[data-bg-variant="pulse"] .bg-ambient::before {{
    animation: auroraMesh 48s linear infinite, ambientPulse 7s ease-in-out infinite;
  }}
  body[data-bg-variant="pulse"] .bg-ambient::after {{
    animation: auroraSheen 26s ease-in-out infinite, ambientPulse 9s ease-in-out infinite reverse;
  }}
  body[data-bg-variant="pulse"] .bg-blob {{
    animation-name: blobPulse;
    filter: blur(58px);
  }}

  body[data-bg-variant="minimal"] .bg-ambient {{
    background:
      radial-gradient(900px 520px at 50% -10%, rgba(var(--purple-rgb), 0.12) 0%, transparent 60%),
      radial-gradient(700px 480px at 90% 80%, rgba(var(--purple-deep-rgb), 0.06) 0%, transparent 55%);
  }}
  body[data-bg-variant="minimal"] .bg-ambient::before,
  body[data-bg-variant="minimal"] .bg-ambient::after {{
    opacity: 0;
    animation: none;
  }}
  body[data-bg-variant="minimal"] .bg-blob {{
    opacity: calc(var(--peak, 0.55) * 0.18);
    filter: blur(70px);
    animation: none;
  }}
  body[data-bg-variant="minimal"] .bg-cursor-glow {{
    opacity: 0 !important;
  }}

  /* Stackable background textures (theme-tinted) — kept bold on dark UIs */
  .bg-texture,
  .bg-effect {{
    position: fixed;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    opacity: 0;
    mix-blend-mode: normal;
  }}
  body[data-bg-texture="grain"] .bg-texture {{
    opacity: 0.42;
    mix-blend-mode: soft-light;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 200 200' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='3' stitchTiles='stitch'/%3E%3CfeColorMatrix type='matrix' values='0 0 0 0 1 0 0 0 0 1 0 0 0 0 1 0 0 0 0.85 0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
    background-size: 120px 120px;
  }}
  body[data-bg-texture="grid"] .bg-texture {{
    opacity: 1;
    background-image:
      linear-gradient(rgba(var(--purple-bright-rgb), 0.35) 1px, transparent 1px),
      linear-gradient(90deg, rgba(var(--accent-shift-rgb), 0.28) 1px, transparent 1px),
      linear-gradient(rgba(255,255,255,0.14) 1px, transparent 1px),
      linear-gradient(90deg, rgba(255,255,255,0.1) 1px, transparent 1px);
    background-size: 56px 56px, 56px 56px, 8px 8px, 8px 8px;
    background-position: -1px -1px;
  }}
  body[data-bg-texture="carbon"] .bg-texture {{
    opacity: 0.5;
    mix-blend-mode: soft-light;
    background-image:
      repeating-linear-gradient(
        0deg,
        rgba(255,255,255,0.03) 0 1px,
        transparent 1px 3px
      ),
      repeating-linear-gradient(
        90deg,
        rgba(0,0,0,0.22) 0 1px,
        transparent 1px 3px
      ),
      repeating-linear-gradient(
        45deg,
        rgba(var(--purple-rgb), 0.05) 0 2px,
        transparent 2px 6px
      ),
      repeating-linear-gradient(
        -45deg,
        rgba(var(--accent-shift-rgb), 0.04) 0 2px,
        transparent 2px 6px
      );
    background-size: 6px 6px, 6px 6px, 10px 10px, 10px 10px;
  }}
  body[data-bg-texture="ripple"] .bg-texture {{
    opacity: 0.4;
    mix-blend-mode: soft-light;
    background-image:
      repeating-radial-gradient(
        circle at 30% 28%,
        transparent 0 18px,
        rgba(var(--purple-rgb), 0.05) 18px 19px,
        transparent 19px 36px
      ),
      repeating-radial-gradient(
        circle at 78% 70%,
        transparent 0 22px,
        rgba(var(--accent-shift-rgb), 0.045) 22px 23px,
        transparent 23px 44px
      ),
      repeating-radial-gradient(
        circle at 55% 48%,
        transparent 0 28px,
        rgba(255,255,255,0.025) 28px 29px,
        transparent 29px 56px
      );
    animation: rippleDrift 40s linear infinite;
  }}
  body[data-bg-texture="diagonal"] .bg-texture {{
    opacity: 1;
    background-image:
      repeating-linear-gradient(
        -32deg,
        transparent 0 6px,
        rgba(var(--purple-bright-rgb), 0.22) 6px 9px,
        transparent 9px 16px
      ),
      repeating-linear-gradient(
        32deg,
        transparent 0 9px,
        rgba(var(--accent-shift-rgb), 0.18) 9px 12px,
        transparent 12px 22px
      );
  }}

  /* Stackable weather / particle effects (independent of texture) */
  body[data-bg-effect="stars"] .bg-effect {{
    opacity: 1;
    mix-blend-mode: screen;
    background-image:
      radial-gradient(2px 2px at 10% 20%, #fff, transparent),
      radial-gradient(2.5px 2.5px at 30% 65%, rgba(var(--purple-bright-rgb), 1), transparent),
      radial-gradient(1.5px 1.5px at 55% 35%, #fff, transparent),
      radial-gradient(3px 3px at 75% 15%, rgba(var(--accent-shift-rgb), 1), transparent),
      radial-gradient(2px 2px at 85% 70%, #fff, transparent),
      radial-gradient(2.5px 2.5px at 20% 85%, rgba(var(--accent-soft-rgb), 1), transparent),
      radial-gradient(1.5px 1.5px at 45% 80%, #fff, transparent),
      radial-gradient(2px 2px at 65% 55%, rgba(var(--purple-rgb), 1), transparent),
      radial-gradient(2px 2px at 5% 50%, #fff, transparent),
      radial-gradient(2.5px 2.5px at 92% 40%, rgba(var(--purple-bright-rgb), 1), transparent),
      radial-gradient(1.5px 1.5px at 38% 12%, #fff, transparent),
      radial-gradient(2px 2px at 58% 48%, rgba(var(--accent-shift-rgb), 0.95), transparent);
    background-size: 220px 220px, 220px 220px, 220px 220px, 220px 220px, 220px 220px,
      180px 180px, 180px 180px, 180px 180px, 160px 160px, 160px 160px, 140px 140px, 140px 140px;
    animation: starDrift 48s linear infinite, starTwinkle 3.2s ease-in-out infinite;
  }}
  body[data-bg-effect="snow"] .bg-effect {{
    opacity: 0.55;
    mix-blend-mode: screen;
    background-image:
      radial-gradient(2px 2px at 12% 18%, rgba(255,255,255,0.7), transparent),
      radial-gradient(1.5px 1.5px at 38% 42%, rgba(255,255,255,0.55), transparent),
      radial-gradient(2.5px 2.5px at 62% 28%, rgba(255,255,255,0.65), transparent),
      radial-gradient(1.5px 1.5px at 84% 58%, rgba(255,255,255,0.5), transparent),
      radial-gradient(2px 2px at 22% 72%, rgba(255,255,255,0.6), transparent),
      radial-gradient(1.5px 1.5px at 55% 82%, rgba(255,255,255,0.45), transparent),
      radial-gradient(2px 2px at 78% 12%, rgba(var(--purple-bright-rgb), 0.35), transparent),
      radial-gradient(1.5px 1.5px at 8% 88%, rgba(255,255,255,0.5), transparent);
    background-size: 180px 180px, 220px 220px, 160px 160px, 200px 200px,
      140px 140px, 190px 190px, 170px 170px, 210px 210px;
    animation: snowDrift 28s linear infinite;
  }}
  body[data-bg-effect="rain"] .bg-effect {{
    opacity: 0.35;
    mix-blend-mode: soft-light;
    background-image:
      repeating-linear-gradient(
        calc(105deg + var(--rain-wind, 0) * 1deg),
        transparent 0 10px,
        rgba(255,255,255,0.04) 10px 11px,
        transparent 11px 22px
      ),
      repeating-linear-gradient(
        calc(105deg + var(--rain-wind, 0) * 1deg),
        transparent 0 16px,
        rgba(var(--purple-bright-rgb), 0.05) 16px 17px,
        transparent 17px 34px
      ),
      linear-gradient(180deg, transparent 70%, rgba(var(--purple-rgb), 0.06) 100%);
    animation: rainSheer 1.8s linear infinite;
  }}

  /* Rainy window background — condensation + glass droplets */
  body[data-bg-variant="rainy"] .bg-ambient {{
    background:
      radial-gradient(920px 540px at 48% -8%, rgba(var(--purple-bright-rgb), 0.14) 0%, transparent 58%),
      radial-gradient(700px 480px at 92% 40%, rgba(var(--accent-shift-rgb), 0.1) 0%, transparent 55%),
      radial-gradient(640px 460px at 8% 78%, rgba(var(--purple-deep-rgb), 0.14) 0%, transparent 55%),
      linear-gradient(180deg, rgba(255,255,255,0.03) 0%, transparent 28%, rgba(0,0,0,0.12) 100%);
  }}
  body[data-bg-variant="rainy"] .bg-ambient::before {{
    inset: 0;
    background:
      radial-gradient(ellipse 18px 24px at 12% 18%, rgba(255,255,255,0.22), transparent 70%),
      radial-gradient(ellipse 12px 16px at 28% 42%, rgba(255,255,255,0.16), transparent 70%),
      radial-gradient(ellipse 22px 28px at 48% 22%, rgba(255,255,255,0.2), transparent 70%),
      radial-gradient(ellipse 10px 14px at 66% 58%, rgba(255,255,255,0.14), transparent 70%),
      radial-gradient(ellipse 16px 22px at 82% 30%, rgba(255,255,255,0.18), transparent 70%),
      radial-gradient(ellipse 14px 18px at 18% 72%, rgba(255,255,255,0.12), transparent 70%),
      radial-gradient(ellipse 20px 26px at 58% 78%, rgba(255,255,255,0.15), transparent 70%),
      radial-gradient(ellipse 11px 15px at 88% 68%, rgba(255,255,255,0.13), transparent 70%),
      radial-gradient(ellipse 15px 20px at 38% 8%, rgba(255,255,255,0.17), transparent 70%),
      radial-gradient(ellipse 9px 12px at 74% 88%, rgba(255,255,255,0.11), transparent 70%),
      linear-gradient(
        108deg,
        transparent 0 40%,
        rgba(255,255,255,0.035) 42%,
        transparent 46%,
        rgba(255,255,255,0.025) 58%,
        transparent 62%
      );
    background-size: 100% 100%;
    animation: rainyGlass 22s ease-in-out infinite;
    opacity: 0.95;
    mix-blend-mode: soft-light;
    filter: blur(0.4px);
  }}
  body[data-bg-variant="rainy"] .bg-ambient::after {{
    background:
      repeating-linear-gradient(
        102deg,
        transparent 0 18px,
        rgba(255,255,255,0.035) 18px 19px,
        transparent 19px 42px
      ),
      repeating-linear-gradient(
        98deg,
        transparent 0 28px,
        rgba(var(--purple-bright-rgb), 0.04) 28px 29px,
        transparent 29px 56px
      ),
      radial-gradient(ellipse 80% 50% at 50% 0%, rgba(255,255,255,0.06), transparent 55%),
      linear-gradient(180deg, rgba(255,255,255,0.04) 0%, transparent 35%, rgba(0,0,0,0.08) 100%);
    animation: rainyStreak 16s linear infinite;
    opacity: 0.9;
    mix-blend-mode: soft-light;
    filter: blur(0.6px);
  }}
  body[data-bg-variant="rainy"] .bg-blob {{
    filter: blur(70px);
    opacity: calc(var(--peak, 0.55) * 0.45);
    animation-duration: 14s;
  }}
  body[data-bg-variant="rainy"] .bg-cursor-glow {{
    width: 320px;
    height: 320px;
    margin: -160px 0 0 -160px;
    background: radial-gradient(circle, rgba(255,255,255,0.14) 0%, rgba(var(--purple-bright-rgb), 0.12) 35%, transparent 68%);
    filter: blur(16px);
    mix-blend-mode: soft-light;
  }}

  .weather-fx {{
    position: fixed;
    inset: 0;
    z-index: 1;
    pointer-events: none;
    overflow: hidden;
    opacity: 0;
    transition: opacity .25s ease;
  }}
  body[data-bg-effect="rain"] .weather-fx,
  body[data-bg-effect="snow"] .weather-fx {{
    opacity: 1;
  }}
  .rain-drop {{
    position: absolute;
    left: 0;
    top: 0;
    width: 2px;
    height: var(--len, 16px);
    margin-left: -1px;
    border-radius: 2px;
    background: linear-gradient(
      to bottom,
      transparent,
      rgba(255,255,255,0.55) 35%,
      rgba(var(--purple-bright-rgb), 0.45) 100%
    );
    opacity: 0;
    transform-origin: 50% 0%;
    will-change: transform, opacity;
  }}
  .rain-splash {{
    position: absolute;
    left: 0;
    top: 0;
    width: var(--s, 20px);
    height: calc(var(--s, 20px) * 0.38);
    border-radius: 50%;
    border: 1.5px solid rgba(255,255,255,0.5);
    box-shadow: 0 0 10px rgba(var(--accent-soft-rgb), 0.25), inset 0 0 8px rgba(255,255,255,0.15);
    background: radial-gradient(circle, rgba(255,255,255,0.18) 0%, transparent 70%);
    opacity: 0;
    will-change: transform, opacity;
  }}
  .rain-splash.go {{
    animation: rainSplash 0.45s ease-out forwards;
  }}
  .snow-flake {{
    position: absolute;
    left: 0;
    top: 0;
    width: var(--sz, 4px);
    height: var(--sz, 4px);
    margin: calc(var(--sz, 4px) / -2) 0 0 calc(var(--sz, 4px) / -2);
    border-radius: 50%;
    background: rgba(255,255,255,0.85);
    box-shadow: 0 0 6px rgba(255,255,255,0.45);
    opacity: 0;
    will-change: transform, opacity;
  }}

  .theme-swatch.chroma {{
    background: linear-gradient(
      90deg,
      #ff6b6b,
      #fbbf24,
      #34d399,
      #38bdf8,
      #a855f7,
      #f472b6,
      #ff6b6b,
      #fbbf24,
      #34d399,
      #38bdf8,
      #a855f7,
      #f472b6,
      #ff6b6b
    );
    background-size: 200% 100%;
    animation: chromaFlow 14s linear infinite;
  }}
  body[data-theme-chroma] .theme-dot {{
    background: linear-gradient(
      90deg,
      #ff6b6b,
      #fbbf24,
      #34d399,
      #38bdf8,
      #a855f7,
      #f472b6,
      #ff6b6b,
      #fbbf24,
      #34d399,
      #38bdf8,
      #a855f7,
      #f472b6,
      #ff6b6b
    );
    background-size: 200% 100%;
    animation: chromaFlow 14s linear infinite;
  }}
  body[data-theme-chroma] .theme-toggle {{
    border-color: rgba(255,255,255,0.28);
  }}
  /* Chroma primary buttons follow the live accent (solid), not a full rainbow */
  body[data-theme-chroma] .inv-actions button.primary,
  body[data-theme-chroma] .target-actions button.primary {{
    background: var(--purple);
    border-color: var(--purple);
    color: #fff;
    animation: none;
  }}
  @keyframes starDrift {{
    0% {{
      background-position:
        0 0, 0 0, 0 0, 0 0, 0 0,
        0 0, 0 0, 0 0, 0 0, 0 0, 0 0, 0 0;
    }}
    100% {{
      background-position:
        220px 140px, -180px 90px, 110px -160px, -90px 200px, 160px 60px,
        -140px -100px, 90px 160px, -60px -180px, 120px -80px, -200px 110px,
        70px 130px, -110px -70px;
    }}
  }}
  @keyframes starTwinkle {{
    0%, 100% {{ opacity: 0.72; filter: brightness(0.85) saturate(0.9); }}
    20% {{ opacity: 1; filter: brightness(1.35) saturate(1.15); }}
    40% {{ opacity: 0.8; filter: brightness(0.95) saturate(1); }}
    60% {{ opacity: 1; filter: brightness(1.25) saturate(1.2); }}
    80% {{ opacity: 0.78; filter: brightness(0.9) saturate(0.95); }}
  }}
  @keyframes rippleDrift {{
    0% {{ background-position: 0 0, 0 0, 0 0; }}
    100% {{ background-position: 48px 36px, -40px 30px, 24px -28px; }}
  }}
  @keyframes snowDrift {{
    0% {{
      background-position:
        0 0, 40px 20px, 0 0, 60px 40px,
        20px 0, 0 50px, 30px 10px, 10px 30px;
    }}
    100% {{
      background-position:
        40px 180px, -20px 200px, 80px 160px, -40px 220px,
        60px 140px, -30px 190px, 50px 170px, -10px 210px;
    }}
  }}
  @keyframes rainSheer {{
    0% {{ background-position: 0 0, 0 0, 0 0; }}
    100% {{ background-position: 24px 80px, -18px 110px, 0 0; }}
  }}
  @keyframes rainSplash {{
    0% {{
      transform: translate(-50%, -50%) scale(0.25, 0.4);
      opacity: 0.85;
    }}
    100% {{
      transform: translate(-50%, -50%) scale(1.35, 0.9);
      opacity: 0;
    }}
  }}
  @keyframes rainyGlass {{
    0%, 100% {{ opacity: 0.88; filter: blur(0.35px); }}
    50% {{ opacity: 1; filter: blur(0.55px); }}
  }}
  @keyframes rainyStreak {{
    0% {{ background-position: 0 0, 0 0, 0 0, 0 0; }}
    100% {{ background-position: 30px 90px, -22px 120px, 0 0, 0 0; }}
  }}

  @keyframes auroraMesh {{
    0% {{ background-position: 0% 0%; }}
    100% {{ background-position: 100% 100%; }}
  }}
  @keyframes auroraSheen {{
    0%, 100% {{ background-position: 0% 40%; opacity: 0.75; }}
    50% {{ background-position: 100% 60%; opacity: 1; }}
  }}
  @keyframes blobDrift {{
    0%, 100% {{ transform: translate3d(0, 0, 0) scale(1); opacity: var(--peak, 0.55); }}
    25% {{ transform: translate3d(4%, -5%, 0) scale(1.06); opacity: calc(var(--peak, 0.55) * 0.92); }}
    50% {{ transform: translate3d(-3%, -8%, 0) scale(1.1); opacity: calc(var(--peak, 0.55) * 0.78); }}
    75% {{ transform: translate3d(-5%, 3%, 0) scale(1.04); opacity: calc(var(--peak, 0.55) * 0.9); }}
  }}
  @keyframes blobPulse {{
    0%, 100% {{ transform: translate3d(0, 0, 0) scale(1); opacity: var(--peak, 0.55); }}
    50% {{ transform: translate3d(2%, -3%, 0) scale(1.12); opacity: calc(var(--peak, 0.55) * 0.7); }}
  }}
  @keyframes ambientPulse {{
    0%, 100% {{ opacity: 0.72; }}
    50% {{ opacity: 1; }}
  }}
  .shell {{
    position: relative;
    z-index: 2;
    width: min(1680px, calc(100% - 24px));
    margin: 0 auto;
    padding: 36px 0 88px;
    display: grid;
    grid-template-columns: 280px minmax(0, 1fr) 300px;
    gap: 18px;
    align-items: start;
  }}
  .wrap {{ min-width: 0; }}
  .trends-panel {{
    position: sticky;
    top: 16px;
    max-height: calc(100vh - 32px);
    overflow: auto;
    background: linear-gradient(180deg, var(--card-2), var(--card));
    border: 1px solid var(--line-strong);
    border-radius: 16px;
    box-shadow: var(--shadow);
    padding: 14px 12px 16px;
  }}
  .trends-panel h2 {{
    margin: 0 0 12px;
    font-size: 15px;
    font-weight: 800;
    color: var(--purple-bright);
  }}
  .trends-panel .trends-sub {{
    display: none;
  }}
  .trends-block {{
    margin-bottom: 14px;
  }}
  .trends-block:last-child {{ margin-bottom: 0; }}
  .trends-block h3 {{
    margin: 0 0 8px;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }}
  .trends-block.h-up h3 {{ color: var(--green-soft); }}
  .trends-block.h-down h3 {{ color: #f87171; }}
  .trends-block.h-hot h3 {{ color: #fbbf24; }}
  .trends-list {{
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .trend-row {{
    display: grid;
    grid-template-columns: 34px 1fr auto;
    gap: 8px;
    align-items: center;
    padding: 7px 8px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: rgba(13, 11, 20, 0.65);
    cursor: pointer;
    text-align: left;
    width: 100%;
    color: inherit;
    font: inherit;
  }}
  .trend-row:hover {{
    border-color: var(--purple);
    background: rgba(var(--purple-rgb), 0.1);
  }}
  .trend-row img, .trend-row .noimg {{
    width: 34px;
    height: 34px;
    object-fit: contain;
    border-radius: 7px;
    background: #0d0b14;
  }}
  .trend-row .noimg {{
    display: grid;
    place-items: center;
    color: var(--muted);
    font-size: 10px;
  }}
  .trend-row .tname-wrap {{
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    line-height: 1.25;
  }}
  .trend-row .tname {{
    font-size: 12px;
    font-weight: 700;
  }}
  .chroma-name {{
    background: linear-gradient(
      90deg,
      #ff6b6b,
      #fbbf24,
      #34d399,
      #38bdf8,
      #a855f7,
      #f472b6,
      #ff6b6b,
      #fbbf24,
      #34d399,
      #38bdf8,
      #a855f7,
      #f472b6,
      #ff6b6b
    );
    background-size: 200% 100%;
    background-position: 0% 50%;
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    animation: chromaFlow 14s linear infinite;
  }}
  .hot-name {{
    background: linear-gradient(
      90deg,
      #7f1d1d,
      #dc2626,
      #f97316,
      #fbbf24,
      #fff7ed,
      #f97316,
      #ef4444,
      #7f1d1d,
      #dc2626,
      #f97316,
      #fbbf24,
      #fff7ed,
      #f97316,
      #ef4444,
      #7f1d1d
    );
    background-size: 200% 100%;
    background-position: 0% 50%;
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    animation: hotFlow 3.2s linear infinite;
  }}
  @keyframes chromaFlow {{
    0% {{ background-position: 0% 50%; }}
    100% {{ background-position: -100% 50%; }}
  }}
  @keyframes hotFlow {{
    0% {{ background-position: 0% 50%; }}
    100% {{ background-position: 100% 50%; }}
  }}
  @media (prefers-reduced-motion: reduce) {{
    .chroma-name {{
      animation: none;
      background-size: 100% 100%;
      background-position: 0% 50%;
      background-image: linear-gradient(
        110deg,
        #ff6b6b 0%,
        #fbbf24 18%,
        #34d399 36%,
        #38bdf8 54%,
        #a855f7 72%,
        #f472b6 88%,
        #ff6b6b 100%
      );
    }}
    .hot-name {{
      animation: none;
      background-size: 100% 100%;
      background-position: 0% 50%;
      background-image: linear-gradient(
        110deg,
        #b91c1c 0%,
        #ea580c 35%,
        #fbbf24 65%,
        #dc2626 100%
      );
    }}
    .bg-ambient::before,
    .bg-ambient::after,
    .bg-blob {{
      animation: none !important;
    }}
    .bg-ambient::before {{
      background-position: 28% 32%;
      opacity: 0.7;
    }}
    .bg-ambient::after {{
      background-position: 40% 50%;
      opacity: 0.85;
    }}
    .bg-blob {{
      opacity: calc(var(--peak, 0.55) * 0.55);
      transform: none;
    }}
    body[data-bg-variant="mesh"] .bg-ambient::before {{
      opacity: 0.85;
      filter: none;
    }}
    body[data-bg-variant="blobs"] .bg-blob {{
      opacity: calc(var(--peak, 0.55) * 0.7);
    }}
    body[data-bg-variant="pulse"] .bg-ambient::before,
    body[data-bg-variant="pulse"] .bg-ambient::after {{
      opacity: 0.8;
    }}
    body[data-bg-variant="minimal"] .bg-blob {{
      opacity: calc(var(--peak, 0.55) * 0.2);
    }}
    body[data-bg-variant="rainy"] .bg-ambient::before,
    body[data-bg-variant="rainy"] .bg-ambient::after {{
      animation: none !important;
      filter: none;
    }}
    .bg-texture,
    .bg-effect {{
      animation: none !important;
    }}
    .slot.slot-enter,
    .slot.slot-exit,
    .slot.slot-bump {{
      animation: none !important;
    }}
    .weather-fx {{
      display: none !important;
    }}
    body[data-theme-chroma] .theme-dot,
    .theme-swatch.chroma {{
      animation: none !important;
      background-size: 100% 100%;
      background-position: 0% 50%;
    }}
  }}
  .name-mark {{
    display: inline-block;
    margin-left: 4px;
    font-size: 0.95em;
    line-height: 1;
    vertical-align: baseline;
    font-weight: 800;
  }}
  .name-mark.hot {{
    filter: drop-shadow(0 0 4px rgba(251, 146, 60, 0.55));
  }}
  .name-mark.rise,
  .name-mark.rise2 {{
    color: var(--green-soft);
    filter: drop-shadow(0 0 3px rgba(52, 211, 153, 0.4));
  }}
  .name-mark.rise2 {{
    letter-spacing: -0.12em;
  }}
  .name-mark.flat {{
    color: #94a3b8;
    opacity: 0.85;
    font-weight: 700;
  }}
  .name-mark.drop,
  .name-mark.drop2 {{
    color: #f87171;
    filter: drop-shadow(0 0 3px rgba(248, 113, 113, 0.4));
  }}
  .name-mark.drop2 {{
    letter-spacing: -0.12em;
  }}
  .name-mark.caution {{
    color: #facc15;
    filter: drop-shadow(0 0 4px rgba(250, 204, 21, 0.55));
  }}
  .name-line, .dump-title {{
    display: flex;
    align-items: baseline;
    min-width: 0;
    gap: 0;
  }}
  .name-line .name, .dump-title .name {{
    min-width: 0;
  }}
  .trend-row .tmeta {{
    font-size: 10px;
    color: var(--muted);
    margin-top: 2px;
  }}
  .trend-row .tpct {{
    font-size: 12px;
    font-weight: 800;
    white-space: nowrap;
  }}
  .trend-row .tpct.up {{ color: var(--green-soft); }}
  .trend-row .tpct.down {{ color: #f87171; }}
  .trends-empty {{
    font-size: 11px;
    color: var(--muted);
    line-height: 1.4;
    padding: 4px 2px;
  }}
  h1 {{
    margin: 0;
    text-align: center;
    font-family: "Outfit", sans-serif;
    font-size: clamp(24px, 3.2vw, 32px);
    font-weight: 700;
    letter-spacing: -0.01em;
    background: linear-gradient(115deg, #ffffff 8%, var(--purple-bright) 42%, var(--purple) 72%, var(--purple-pale) 100%);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
  }}
  .wrap-head {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    flex-wrap: wrap;
    margin: 0 0 18px;
  }}
  .quick-search {{
    position: relative;
    margin: 0 0 28px;
    z-index: 20;
  }}
  .quick-search[hidden] {{ display: none; }}
  .quick-search-row {{
    display: flex;
    gap: 10px;
    align-items: center;
  }}
  .quick-search-row input[type="search"] {{
    flex: 1;
    border: 1px solid var(--line-strong);
    border-radius: 12px;
    padding: 12px 14px;
    font: inherit;
    font-size: 14px;
    background: var(--card);
    color: var(--text);
    box-shadow: var(--shadow);
  }}
  .quick-search-row input[type="search"]::placeholder {{ color: #6f6688; }}
  .quick-search-row input[type="search"]:focus {{
    outline: none;
    border-color: var(--purple);
    box-shadow: 0 0 0 2px rgba(var(--purple-rgb), 0.28);
  }}
  .quick-search-row select {{
    border: 1px solid var(--line-strong);
    border-radius: 12px;
    padding: 12px 10px;
    font: inherit;
    font-size: 13px;
    background: var(--card);
    color: var(--text);
    min-width: 120px;
  }}
  .quick-hint {{
    margin: 8px 2px 0;
    font-size: 11px;
    color: var(--muted);
  }}
  .quick-results {{
    position: absolute;
    left: 0;
    right: 0;
    top: calc(100% + 8px);
    max-height: min(60vh, 520px);
    overflow: auto;
    background: linear-gradient(180deg, var(--card-2), var(--card));
    border: 1px solid var(--line-strong);
    border-radius: 14px;
    box-shadow: var(--shadow);
    padding: 8px;
  }}
  .quick-results[hidden] {{ display: none; }}
  .quick-row {{
    display: grid;
    grid-template-columns: 72px 1fr auto;
    gap: 14px;
    align-items: center;
    padding: 12px;
    border-radius: 12px;
    border: 1px solid transparent;
  }}
  .quick-row:hover {{
    background: rgba(var(--purple-rgb), 0.08);
    border-color: rgba(var(--purple-rgb), 0.28);
  }}
  .quick-row img, .quick-row .noimg {{
    width: 72px;
    height: 72px;
    border-radius: 12px;
    object-fit: contain;
    background: #0d0b14;
    border: 1px solid var(--line);
  }}
  .quick-row .noimg {{
    display: grid;
    place-items: center;
    font-size: 12px;
    color: var(--muted);
  }}
  .quick-row .name {{ font-weight: 700; font-size: 16px; }}
  .quick-row .meta {{ color: var(--muted); font-size: 13px; margin-top: 3px; }}
  .quick-row .val {{
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    color: var(--purple-bright);
    font-size: 15px;
    margin-top: 4px;
  }}
  .quick-actions {{
    display: flex;
    flex-direction: column;
    gap: 7px;
  }}
  .quick-actions button {{
    border: 1px solid var(--line);
    background: rgba(13, 11, 20, 0.65);
    color: var(--text);
    font-family: inherit;
    font-weight: 700;
    font-size: 12px;
    padding: 9px 12px;
    border-radius: 9px;
    cursor: pointer;
    white-space: nowrap;
  }}
  .quick-actions button:hover {{
    border-color: var(--purple);
    color: var(--purple-bright);
  }}
  .quick-actions button.offer {{
    border-color: rgba(var(--purple-rgb), 0.45);
    background: rgba(var(--purple-rgb), 0.14);
  }}
  .quick-actions button.request {{
    border-color: rgba(56, 189, 248, 0.4);
    background: rgba(56, 189, 248, 0.1);
    color: #7dd3fc;
  }}
  .quick-actions button.request:hover {{
    border-color: #38bdf8;
    color: #bae6fd;
  }}
  .quick-empty {{
    padding: 22px 14px;
    text-align: center;
    color: var(--muted);
    font-size: 13px;
  }}

  /* Header comparison */
  .compare {{
    display: grid;
    grid-template-columns: 140px 1fr 140px;
    gap: 18px;
    align-items: center;
    margin-bottom: 34px;
  }}
  .value-box {{
    background: linear-gradient(180deg, var(--card-2), var(--card));
    border-radius: 16px;
    box-shadow: var(--shadow);
    border: 1px solid var(--line-strong);
    padding: 18px 12px;
    text-align: center;
  }}
  .value-box .num {{
    font-size: 28px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    line-height: 1.1;
    color: var(--purple-bright);
  }}
  .value-box .label {{
    margin-top: 4px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: var(--muted);
  }}
  .meter-wrap {{ text-align: center; }}
  .meter {{
    height: 14px;
    border-radius: 999px;
    border: 2px solid var(--line-strong);
    background: #0d0b14;
    overflow: hidden;
    position: relative;
  }}
  .meter-fill {{
    height: 100%;
    width: 50%;
    background: linear-gradient(90deg, var(--purple-deep), var(--purple-bright));
    transition: width .25s ease, background .25s ease;
  }}
  .verdict {{
    margin: 10px 0 0;
    font-size: 22px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
    color: var(--muted);
  }}
  .verdict.fair {{ color: var(--purple-bright); }}
  .verdict.win {{ color: var(--green); }}
  .verdict.loss {{ color: var(--red); }}
  .trade-caution {{
    display: none;
    margin: 12px 0 0;
    padding: 10px 14px;
    border-radius: 12px;
    border: 1px solid rgba(245, 158, 11, 0.45);
    background: rgba(245, 158, 11, 0.1);
    color: #fbbf24;
    font-size: 13px;
    font-weight: 600;
    line-height: 1.4;
    text-align: center;
  }}
  .trade-caution.show {{ display: block; }}
  .trade-caution strong {{
    font-weight: 800;
    letter-spacing: 0.02em;
  }}
  .trade-caution .drop {{
    color: #fcd34d;
    font-weight: 700;
  }}
  .board.caution-side h2 {{
    color: #fbbf24;
  }}
  .board.caution-side h2::after {{
    content: ' ⚠';
    font-size: 0.75em;
    opacity: 0.9;
  }}

  /* Boards */
  .boards {{
    display: grid;
    grid-template-columns: 1fr 120px 1fr;
    gap: 18px;
    align-items: start;
  }}
  .board h2 {{
    margin: 0 0 14px;
    text-align: center;
    font-size: 22px;
    font-weight: 800;
    color: var(--text);
  }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }}
  .slot {{
    aspect-ratio: 1;
    background: var(--card);
    border: 1.5px solid var(--line);
    border-radius: 14px;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    position: relative;
    overflow: hidden;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.03);
    transition: transform .18s cubic-bezier(.2,.85,.3,1), opacity .16s ease, border-color .15s ease, box-shadow .15s ease;
  }}
  .slot.slot-enter {{
    animation: slotEnter .28s cubic-bezier(.2,.9,.25,1) both;
  }}
  .slot.slot-exit {{
    animation: slotExit .16s ease-in both;
    pointer-events: none;
  }}
  .slot.slot-bump {{
    animation: slotBump .2s ease;
  }}
  @keyframes slotEnter {{
    0% {{ transform: scale(0.9); opacity: 0; }}
    100% {{ transform: scale(1); opacity: 1; }}
  }}
  @keyframes slotExit {{
    0% {{ transform: scale(1); opacity: 1; }}
    100% {{ transform: scale(0.88); opacity: 0; }}
  }}
  @keyframes slotBump {{
    0% {{ transform: scale(1); }}
    40% {{ transform: scale(1.05); }}
    100% {{ transform: scale(1); }}
  }}
  .slot.empty {{
    cursor: pointer;
    transition: border-color .15s, background .15s, box-shadow .15s, transform .15s ease;
  }}
  .slot.empty:hover {{
    border-color: var(--purple);
    background: var(--card-2);
    box-shadow: 0 0 0 1px rgba(var(--purple-rgb), 0.25);
    transform: translateY(-1px);
  }}
  .slot.empty:active {{
    transform: scale(0.97);
  }}
  .slot .plus {{
    font-size: 42px;
    font-weight: 500;
    color: var(--purple-bright);
    line-height: 1;
    user-select: none;
    transition: transform .15s ease, color .15s ease;
  }}
  .slot.empty:hover .plus {{
    transform: scale(1.08);
  }}
  .slot .art {{
    width: 62%;
    height: 54%;
    object-fit: contain;
    margin-top: 8px;
  }}
  .slot .qty {{
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 6px 0 10px;
  }}
  .slot .qty button {{
    width: 22px;
    height: 22px;
    border: none;
    border-radius: 50%;
    background: var(--purple);
    color: #fff;
    font-size: 16px;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    display: grid;
    place-items: center;
    transition: transform .12s ease, background .12s ease;
  }}
  .slot .qty button:hover {{ background: var(--purple-deep); }}
  .slot .qty button:active {{ transform: scale(0.88); }}
  .slot .qty input {{
    width: 36px;
    height: 24px;
    border: 1px solid var(--line-strong);
    border-radius: 6px;
    text-align: center;
    font-weight: 700;
    font-size: 13px;
    font-family: inherit;
    background: #0d0b14;
    color: var(--text);
  }}
  .slot .remove {{
    position: absolute;
    top: 6px;
    right: 6px;
    width: 22px;
    height: 22px;
    border: none;
    border-radius: 50%;
    background: #2a2438;
    color: #d4c8ef;
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    display: none;
    transition: transform .12s ease, background .12s ease, color .12s ease;
  }}
  .slot.filled:hover .remove {{ display: grid; place-items: center; }}
  .slot .remove:hover {{
    background: #3f2a4a;
    color: #fff;
  }}
  .slot .remove:active {{
    transform: scale(0.88);
  }}

  .center {{
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding-top: 48px;
  }}
  .reset {{
    margin-top: 8px;
    border: none;
    background: linear-gradient(135deg, var(--purple), var(--purple-deep));
    color: #fff;
    font-family: inherit;
    font-weight: 700;
    font-size: 14px;
    padding: 12px 18px;
    border-radius: 10px;
    cursor: pointer;
    box-shadow: 0 8px 22px rgba(var(--purple-deep-rgb), 0.35);
  }}
  .reset:hover {{ filter: brightness(1.08); }}
  .gen-offer {{
    border: 1px solid var(--purple);
    background: transparent;
    color: var(--purple-bright);
    font-family: inherit;
    font-weight: 700;
    font-size: 13px;
    padding: 10px 14px;
    border-radius: 10px;
    cursor: pointer;
  }}
  .gen-offer:hover {{
    background: rgba(var(--purple-rgb), 0.12);
  }}
  .gen-offer.lower {{
    border-color: #7c6a9a;
    color: #d4c8ef;
  }}
  .gen-offer.lower:hover {{
    border-color: var(--purple-bright);
    color: var(--purple-bright);
    background: rgba(var(--purple-rgb), 0.1);
  }}
  .gen-offer[hidden] {{ display: none; }}
  .complete-offer {{
    border: 1px solid var(--green-soft);
    background: rgba(52, 211, 153, 0.1);
    color: var(--green-soft);
    font-family: inherit;
    font-weight: 700;
    font-size: 13px;
    padding: 10px 14px;
    border-radius: 10px;
    cursor: pointer;
  }}
  .complete-offer:hover {{
    background: rgba(52, 211, 153, 0.2);
  }}
  .complete-offer[hidden] {{ display: none; }}
  .history-row {{
    display: flex;
    gap: 8px;
    margin-top: 2px;
  }}
  .history-btn {{
    border: 1px solid var(--line-strong);
    background: rgba(255, 255, 255, 0.03);
    color: #d4c8ef;
    font-family: inherit;
    font-weight: 700;
    font-size: 13px;
    padding: 8px 12px;
    border-radius: 10px;
    cursor: pointer;
    min-width: 72px;
  }}
  .history-btn:hover:not(:disabled) {{
    border-color: var(--purple);
    color: var(--purple-bright);
  }}
  .history-btn:disabled {{
    opacity: 0.35;
    cursor: not-allowed;
  }}
  .trade-hist-btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    border: 1px solid rgba(var(--purple-rgb), 0.55);
    background: rgba(var(--purple-rgb), 0.12);
    color: var(--purple-bright);
    font-family: inherit;
    font-weight: 800;
    font-size: 13px;
    padding: 10px 14px;
    border-radius: 10px;
    cursor: pointer;
    width: 100%;
    max-width: 168px;
  }}
  .trade-hist-btn:hover {{
    border-color: var(--purple);
    color: #fff;
    background: rgba(var(--purple-rgb), 0.22);
  }}
  .trade-hist-badge {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 22px;
    height: 22px;
    padding: 0 6px;
    border-radius: 999px;
    background: var(--purple);
    color: #fff;
    font-size: 12px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }}
  .gen-offer.higher {{
    border-color: #6ee7b7;
    color: #6ee7b7;
  }}
  .gen-offer.higher:hover {{
    background: rgba(110, 231, 183, 0.12);
  }}
  .gen-offer.receive {{
    border-color: #fbbf24;
    color: #fcd34d;
  }}
  .gen-offer.receive:hover {{
    border-color: #fde68a;
    color: #fef3c7;
    background: rgba(251, 191, 36, 0.1);
  }}

  .note {{
    display: none;
  }}

  /* Trade history modal — split list + detail */
  .graph-modal.trade-hist-modal {{
    width: min(1180px, 98vw);
    height: min(92vh, 900px);
  }}
  .trade-hist-body {{
    flex: 1;
    min-height: 0;
    display: grid;
    grid-template-columns: minmax(280px, 340px) minmax(0, 1fr);
    gap: 0;
    padding: 0;
    overflow: hidden;
  }}
  .trade-hist-sidebar {{
    display: flex;
    flex-direction: column;
    min-height: 0;
    border-right: 1px solid var(--line);
    background: rgba(0, 0, 0, 0.18);
  }}
  .trade-hist-sidebar-head {{
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 14px 12px;
    border-bottom: 1px solid var(--line);
    flex-shrink: 0;
  }}
  .trade-hist-meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px 14px;
    font-size: 12px;
    color: var(--muted);
  }}
  .trade-hist-meta strong {{
    color: var(--text);
    font-weight: 800;
  }}
  .trade-hist-filter {{
    width: 100%;
    border: 1px solid var(--line-strong);
    border-radius: 10px;
    background: rgba(255,255,255,0.04);
    color: var(--text);
    font-family: inherit;
    font-size: 13px;
    font-weight: 600;
    padding: 10px 12px;
  }}
  .trade-hist-filter::placeholder {{ color: var(--muted); }}
  .trade-hist-filter:focus {{
    outline: none;
    border-color: var(--purple);
    box-shadow: 0 0 0 2px rgba(var(--purple-rgb), 0.25);
  }}
  .trade-hist-list {{
    display: flex;
    flex-direction: column;
    gap: 8px;
    overflow: auto;
    flex: 1;
    min-height: 0;
    padding: 12px;
  }}
  .trade-hist-empty {{
    padding: 36px 16px;
    text-align: center;
    color: var(--muted);
    font-size: 14px;
    line-height: 1.45;
  }}
  .trade-hist-card {{
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 8px 12px;
    padding: 12px 12px 12px 14px;
    border: 1px solid transparent;
    border-radius: 12px;
    background: rgba(255,255,255,0.03);
    cursor: pointer;
    text-align: left;
    color: inherit;
    font: inherit;
    width: 100%;
    transition: background .15s ease, border-color .15s ease;
  }}
  .trade-hist-card:hover {{
    background: rgba(var(--purple-rgb), 0.1);
  }}
  .trade-hist-card.active {{
    background: rgba(var(--purple-rgb), 0.18);
    border-color: rgba(var(--purple-rgb), 0.55);
    box-shadow: inset 3px 0 0 var(--purple-bright);
  }}
  .trade-hist-card-main {{
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }}
  .trade-hist-card .when {{
    font-size: 13px;
    font-weight: 800;
    line-height: 1.3;
  }}
  .trade-hist-card .status {{
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
  }}
  .trade-hist-card .status .src {{
    color: #fcd34d;
  }}
  .trade-hist-card-side {{
    display: flex;
    align-items: center;
    justify-content: flex-end;
  }}
  .trade-hist-pill {{
    display: inline-flex;
    align-items: center;
    padding: 3px 8px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: rgba(255,255,255,0.03);
    font-size: 11px;
    font-weight: 800;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }}
  .trade-hist-pill.win {{
    color: var(--green-soft);
    border-color: rgba(52, 211, 153, 0.35);
    background: rgba(52, 211, 153, 0.1);
  }}
  .trade-hist-pill.loss {{
    color: #f87171;
    border-color: rgba(248, 113, 113, 0.35);
    background: rgba(248, 113, 113, 0.1);
  }}
  .trade-hist-detail {{
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: auto;
    padding: 18px 20px 22px;
    background:
      radial-gradient(700px 320px at 80% -10%, rgba(var(--purple-rgb), 0.14), transparent 60%),
      linear-gradient(180deg, rgba(255,255,255,0.02), transparent 40%);
  }}
  .trade-hist-detail-empty {{
    margin: auto;
    text-align: center;
    color: var(--muted);
    font-size: 14px;
    padding: 40px 20px;
  }}
  .trade-hist-detail-head {{
    display: flex;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 16px;
  }}
  .trade-hist-detail-head h4 {{
    margin: 0 0 4px;
    font-size: 18px;
    font-weight: 800;
    color: var(--text);
  }}
  .trade-hist-detail-head .sub {{
    margin: 0;
    font-size: 13px;
    color: var(--muted);
  }}
  .trade-hist-detail-actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .trade-hist-detail-actions button {{
    border: 1px solid var(--line);
    background: rgba(255,255,255,0.04);
    color: var(--muted);
    font-family: inherit;
    font-weight: 700;
    font-size: 12px;
    padding: 8px 12px;
    border-radius: 9px;
    cursor: pointer;
  }}
  .trade-hist-detail-actions button:hover {{
    color: #fecaca;
    border-color: rgba(248, 113, 113, 0.45);
  }}
  .trade-hist-section {{
    border: 1px solid var(--line);
    border-radius: 16px;
    background: rgba(0, 0, 0, 0.2);
    padding: 16px;
    margin-bottom: 14px;
  }}
  .trade-hist-section:last-child {{ margin-bottom: 0; }}
  .trade-hist-section-top {{
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 14px;
  }}
  .trade-hist-section-top h5 {{
    margin: 0;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--purple-bright);
  }}
  .trade-hist-section-totals {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px 16px;
    font-size: 13px;
    font-weight: 700;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }}
  .trade-hist-section-totals strong {{
    color: var(--text);
    font-weight: 800;
  }}
  .trade-hist-cards {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
    gap: 12px;
  }}
  .trade-hist-item-card {{
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 12px;
    border-radius: 14px;
    border: 1px solid var(--line);
    background: rgba(255,255,255,0.03);
    min-width: 0;
  }}
  .trade-hist-item-card.clickable {{
    cursor: pointer;
  }}
  .trade-hist-item-card.clickable:hover {{
    border-color: rgba(var(--purple-rgb), 0.55);
    background: rgba(var(--purple-rgb), 0.08);
  }}
  .trade-hist-item-card .art-wrap {{
    display: grid;
    place-items: center;
    aspect-ratio: 1;
    border-radius: 10px;
    background: #0d0b14;
    overflow: hidden;
  }}
  .trade-hist-item-card img,
  .trade-hist-item-card .noimg {{
    width: 72%;
    height: 72%;
    object-fit: contain;
  }}
  .trade-hist-item-card .noimg {{
    display: grid;
    place-items: center;
    color: var(--muted);
    font-weight: 800;
  }}
  .trade-hist-item-card .iname {{
    font-size: 12px;
    font-weight: 800;
    line-height: 1.25;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    min-height: 2.5em;
  }}
  .trade-hist-item-card .qty {{
    font-size: 11px;
    font-weight: 700;
    color: var(--muted);
  }}
  .trade-hist-item-card .vals {{
    display: flex;
    flex-direction: column;
    gap: 3px;
    font-size: 13px;
    font-weight: 700;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }}
  .trade-hist-item-card .vals strong {{
    color: var(--text);
    font-weight: 800;
  }}
  .trade-hist-item-card .vals .was {{
    text-decoration: line-through;
    opacity: 0.65;
    font-weight: 700;
  }}
  .trade-hist-item-card .vals .up {{ color: var(--green-soft); }}
  .trade-hist-item-card .vals .down {{ color: #f87171; }}
  .trade-hist-banners {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    margin-top: 14px;
  }}
  .trade-hist-banner {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    border: 1px solid transparent;
  }}
  .trade-hist-banner.win {{
    color: var(--green-soft);
    background: rgba(52, 211, 153, 0.12);
    border-color: rgba(52, 211, 153, 0.35);
  }}
  .trade-hist-banner.loss {{
    color: #fecaca;
    background: rgba(248, 113, 113, 0.14);
    border-color: rgba(248, 113, 113, 0.4);
  }}
  .trade-hist-banner.fair {{
    color: var(--muted);
    background: rgba(255,255,255,0.04);
    border-color: var(--line);
  }}
  .trade-hist-summary {{
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 12px;
    align-items: center;
    margin-bottom: 16px;
    padding: 14px;
    border-radius: 14px;
    border: 1px solid var(--line);
    background: rgba(255,255,255,0.03);
  }}
  .trade-hist-summary .box {{
    text-align: center;
  }}
  .trade-hist-summary .box .num {{
    font-size: 22px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
  }}
  .trade-hist-summary .box .label {{
    margin-top: 2px;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.06em;
    color: var(--muted);
  }}
  .trade-hist-summary .box .sub {{
    margin-top: 4px;
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
  }}
  .trade-hist-summary .box .sub strong {{ color: var(--text); }}
  .trade-hist-summary .mid {{
    text-align: center;
    min-width: 110px;
  }}
  .trade-hist-summary .mid .verdict {{
    margin: 0;
    font-size: 18px;
    font-weight: 800;
  }}
  .trade-hist-summary .mid .verdict.win {{ color: var(--green-soft); }}
  .trade-hist-summary .mid .verdict.loss {{ color: #f87171; }}
  .trade-hist-summary .mid .verdict.fair {{ color: var(--muted); }}
  .trade-hist-summary .mid .hint {{
    margin-top: 4px;
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
  }}
  .trade-hist-summary .mid .hint.win {{ color: var(--green-soft); }}
  .trade-hist-summary .mid .hint.loss {{ color: #f87171; }}
  .trade-hist-summary .mid .hint.fair {{ color: var(--muted); }}
  @media (max-width: 860px) {{
    .trade-hist-body {{
      grid-template-columns: 1fr;
      grid-template-rows: minmax(220px, 38%) minmax(0, 1fr);
    }}
    .trade-hist-sidebar {{
      border-right: none;
      border-bottom: 1px solid var(--line);
    }}
    .trade-hist-summary {{
      grid-template-columns: 1fr;
    }}
  }}

  /* Previous trade preview modal */
  .prev-trade-backdrop {{
    z-index: 80;
  }}
  .prev-trade-body {{
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 18px 20px 20px;
    overflow: auto;
  }}
  .prev-trade-meta {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px 16px;
    font-size: 13px;
    color: var(--muted);
    flex-shrink: 0;
  }}
  .prev-trade-meta strong {{
    color: var(--text);
    font-weight: 800;
  }}
  .prev-trade-meta .hindsight.win {{ color: var(--green-soft); }}
  .prev-trade-meta .hindsight.loss {{ color: #f87171; }}
  .prev-trade-meta .hindsight.fair {{ color: var(--muted); }}
  .prev-trade-compare {{
    display: grid;
    grid-template-columns: 140px 1fr 140px;
    gap: 14px;
    align-items: center;
    flex-shrink: 0;
  }}
  .prev-trade-compare .value-box .sub {{
    margin-top: 6px;
    font-size: 11px;
    font-weight: 600;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }}
  .prev-trade-compare .value-box .sub strong {{
    color: var(--text);
    font-weight: 800;
  }}
  .prev-trade-boards {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 18px;
    align-items: start;
    flex: 1;
    min-height: 0;
  }}
  .prev-trade-board h2 {{
    margin: 0 0 6px;
    text-align: center;
    font-size: 20px;
    font-weight: 800;
    color: var(--text);
  }}
  .prev-trade-board .side-totals {{
    text-align: center;
    margin: 0 0 12px;
    font-size: 12px;
    font-weight: 600;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
  }}
  .prev-trade-board .side-totals strong {{
    color: var(--text);
    font-weight: 800;
  }}
  .prev-trade-grid {{
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }}
  .prev-trade-slot.slot {{
    aspect-ratio: auto;
    min-height: 148px;
    padding: 10px 8px 12px;
    cursor: default;
    gap: 4px;
  }}
  .prev-trade-slot .art {{
    width: 54%;
    height: 64px;
    margin-top: 2px;
  }}
  .prev-trade-slot .slot-name {{
    width: 100%;
    padding: 0 4px;
    font-size: 11px;
    font-weight: 700;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .prev-trade-slot .slot-qty {{
    font-size: 11px;
    font-weight: 700;
    color: var(--muted);
  }}
  .prev-trade-slot .slot-vals {{
    display: flex;
    flex-direction: column;
    gap: 1px;
    font-size: 11px;
    font-weight: 600;
    color: var(--muted);
    font-variant-numeric: tabular-nums;
    text-align: center;
    line-height: 1.35;
  }}
  .prev-trade-slot .slot-vals strong {{
    color: var(--text);
    font-weight: 800;
  }}
  .prev-trade-slot .slot-vals .delta.up {{ color: var(--green-soft); }}
  .prev-trade-slot .slot-vals .delta.down {{ color: #f87171; }}
  .prev-trade-empty {{
    grid-column: 1 / -1;
    padding: 28px 12px;
    text-align: center;
    color: var(--muted);
    font-size: 13px;
    border: 1px dashed var(--line);
    border-radius: 14px;
  }}
  @media (max-width: 720px) {{
    .prev-trade-compare {{ grid-template-columns: 1fr; }}
    .prev-trade-boards {{ grid-template-columns: 1fr; }}
  }}

  /* Suggested trades */
  .suggest {{
    margin-top: 28px;
  }}
  .suggest-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 12px;
    flex-wrap: wrap;
  }}
  .suggest-head h2 {{
    margin: 0;
    font-size: 18px;
    font-weight: 800;
  }}
  .suggest-head p {{
    display: none;
  }}
  .suggest-toggles {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px 16px;
    align-items: center;
    justify-content: flex-end;
  }}
  .set-protect-toggle {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    user-select: none;
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
    letter-spacing: 0.01em;
  }}
  .set-protect-toggle input {{
    appearance: none;
    width: 34px;
    height: 20px;
    margin: 0;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.06);
    position: relative;
    cursor: pointer;
    flex-shrink: 0;
    transition: background .15s ease, border-color .15s ease;
  }}
  .set-protect-toggle input::after {{
    content: '';
    position: absolute;
    top: 2px;
    left: 2px;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: #c4b5d4;
    transition: transform .15s ease, background .15s ease;
  }}
  .set-protect-toggle input:checked {{
    background: color-mix(in srgb, var(--purple-bright) 55%, transparent);
    border-color: var(--purple-bright);
  }}
  .set-protect-toggle input:checked::after {{
    transform: translateX(14px);
    background: #fff;
  }}
  .set-protect-toggle:hover {{ color: var(--text); }}
  .suggest-list {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
    gap: 16px;
    transition: opacity .18s ease;
  }}
  .suggest-list.is-pending {{
    opacity: 0.55;
    pointer-events: none;
  }}
  .suggest-card.dump {{
    border-color: rgba(251, 191, 36, 0.35);
    background: linear-gradient(165deg, rgba(251, 191, 36, 0.06), rgba(18, 14, 28, 0.5));
  }}
  .suggest-empty {{
    grid-column: 1 / -1;
    padding: 22px 16px;
    text-align: center;
    color: var(--muted);
    font-size: 13px;
    border: 1px dashed var(--line);
    border-radius: 14px;
    line-height: 1.45;
  }}
  .suggest-card {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 16px;
    padding: 18px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }}
  .suggest-swap {{
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 12px;
    align-items: start;
  }}
  .suggest-side {{
    text-align: center;
    min-width: 0;
  }}
  .suggest-arts {{
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 6px;
    margin: 0 auto 8px;
    min-height: 56px;
  }}
  .suggest-arts img, .suggest-arts .noimg {{
    width: 56px;
    height: 56px;
    object-fit: contain;
    border-radius: 10px;
    background: #0d0b14;
    display: block;
  }}
  .suggest-arts .noimg {{
    display: grid;
    place-items: center;
    color: var(--muted);
    font-size: 12px;
  }}
  .suggest-side .tag {{
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: var(--muted);
    margin-bottom: 6px;
  }}
  .suggest-side .name {{
    font-size: 14px;
    font-weight: 700;
    line-height: 1.4;
    text-align: center;
    overflow-wrap: anywhere;
    word-break: break-word;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 4;
    overflow: hidden;
  }}
  .suggest-side .name .name-piece {{
    font-size: inherit;
    font-weight: inherit;
    display: inline;
  }}
  .suggest-side .name .name-sep {{
    color: var(--muted);
    font-weight: 600;
    margin: 0 3px;
    display: inline;
  }}
  .suggest-side .name .name-mark {{
    display: inline;
  }}
  .suggest-side .val {{
    font-size: 15px;
    color: var(--purple-bright);
    font-weight: 800;
    margin-top: 6px;
  }}
  .suggest-arrow {{
    color: var(--purple-bright);
    font-weight: 800;
    font-size: 22px;
    padding-top: 40px;
  }}
  .suggest-why {{
    font-size: 12px;
    color: var(--muted);
    line-height: 1.45;
    min-height: 34px;
  }}
  .suggest-why strong {{
    color: var(--text);
    font-weight: 700;
  }}
  .suggest-use {{
    border: 1px solid var(--line-strong);
    border-radius: 10px;
    background: transparent;
    color: var(--text);
    font: inherit;
    font-weight: 700;
    font-size: 14px;
    padding: 12px;
    cursor: pointer;
  }}
  .suggest-use:hover {{
    border-color: var(--purple);
    color: var(--purple-bright);
  }}
  .target-box {{
    margin-bottom: 14px;
    padding: 12px;
    border: 1px solid var(--line);
    border-radius: 14px;
    background: var(--card);
  }}
  .target-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 10px;
  }}
  .target-top h3 {{
    margin: 0;
    font-size: 13px;
    font-weight: 800;
    letter-spacing: 0.02em;
    color: var(--purple-bright);
  }}
  .dump-box .target-top h3 {{
    color: #fbbf24;
  }}
  .dump-box {{
    margin-top: 4px;
    margin-bottom: 12px;
    border-color: rgba(251, 191, 36, 0.28);
  }}
  .target-actions {{
    display: flex;
    gap: 6px;
  }}
  .target-actions button {{
    border: 1px solid var(--line-strong);
    border-radius: 8px;
    background: transparent;
    color: var(--text);
    font: inherit;
    font-weight: 700;
    font-size: 11px;
    padding: 6px 10px;
    cursor: pointer;
  }}
  .target-actions button.primary {{
    background: var(--purple);
    border-color: var(--purple);
    color: #fff;
  }}
  .target-actions button:hover {{ border-color: var(--purple-bright); }}
  .target-chip-row {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    min-height: 36px;
  }}
  .target-empty {{
    font-size: 12px;
    color: var(--muted);
    line-height: 1.4;
  }}
  .target-chip {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 5px 8px 5px 5px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: #0d0b14;
    max-width: 100%;
  }}
  .target-chip img, .target-chip .noimg {{
    width: 26px;
    height: 26px;
    border-radius: 50%;
    object-fit: contain;
    background: #12101a;
  }}
  .target-chip .noimg {{
    display: grid;
    place-items: center;
    font-size: 9px;
    color: var(--muted);
  }}
  .target-chip .label {{
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 140px;
  }}
  .target-chip .val {{
    font-size: 10px;
    color: var(--muted);
    font-weight: 600;
  }}
  .target-chip .x {{
    border: none;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    padding: 0 2px;
  }}
  .target-chip .x:hover {{ color: var(--red); }}

  /* Inventory side panel */
  .inv-panel {{
    position: sticky;
    top: 16px;
    max-height: calc(100vh - 32px);
    overflow: auto;
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 18px;
    padding: 18px 16px 14px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }}
  .inv-head {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
  }}
  .inv-head h2 {{
    margin: 0;
    font-size: 15px;
    font-weight: 800;
    letter-spacing: -0.01em;
  }}
  .inv-count {{
    font-size: 12px;
    font-weight: 600;
    color: var(--muted);
  }}
  .inv-value-block {{
    padding-bottom: 12px;
    border-bottom: 1px solid var(--line);
  }}
  .inv-value-block .total {{
    font-size: 28px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    color: var(--purple-bright);
    line-height: 1;
  }}
  .inv-value-row {{
    margin-top: 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: 12px;
  }}
  .inv-delta {{
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    font-size: 14px;
  }}
  .inv-delta.up {{ color: var(--green); }}
  .inv-delta.down {{ color: var(--red); }}
  .inv-delta.flat {{ color: var(--muted); }}
  .inv-since {{
    color: var(--muted);
    font-weight: 600;
  }}
  .inv-status {{
    margin-top: 6px;
    font-size: 11px;
    color: var(--muted);
    min-height: 14px;
  }}
  .inv-status.dirty {{ color: #e0b3ff; }}
  .inv-actions {{
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 8px;
  }}
  .inv-actions button {{
    border: 1px solid var(--line-strong);
    border-radius: 10px;
    background: transparent;
    color: var(--text);
    font: inherit;
    font-weight: 700;
    font-size: 12px;
    padding: 9px 6px;
    cursor: pointer;
  }}
  .inv-actions button.primary {{
    background: var(--purple);
    border-color: var(--purple);
    color: #fff;
  }}
  .inv-actions button.save {{
    background: #1a1626;
  }}
  .inv-actions button:hover {{ border-color: var(--purple-bright); }}
  .inv-actions button.primary:hover {{ filter: brightness(1.08); border-color: var(--purple); }}
  .inv-list {{
    display: flex;
    flex-direction: column;
    gap: 2px;
    flex: 1;
  }}
  .inv-dump {{
    display: none;
    flex-direction: column;
    gap: 8px;
    padding: 10px;
    border-radius: 12px;
    border: 1px solid rgba(248, 113, 113, 0.35);
    background: rgba(248, 113, 113, 0.08);
  }}
  .inv-dump.show {{ display: flex; }}
  .inv-dump-head {{
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #f87171;
  }}
  .inv-dump-row {{
    display: grid;
    grid-template-columns: 32px 1fr auto;
    gap: 8px;
    align-items: center;
  }}
  .inv-dump-row img, .inv-dump-row .noimg {{
    width: 32px;
    height: 32px;
    object-fit: contain;
    border-radius: 7px;
    background: #0d0b14;
  }}
  .inv-dump-row .noimg {{
    display: grid;
    place-items: center;
    color: var(--muted);
    font-size: 9px;
  }}
  .inv-dump-row .name {{
    font-size: 12px;
    font-weight: 700;
    line-height: 1.2;
  }}
  .inv-dump-row .why {{
    font-size: 10px;
    color: #fca5a5;
    margin-top: 2px;
  }}
  .inv-dump-row button {{
    border: 1px solid rgba(248, 113, 113, 0.55);
    background: transparent;
    color: #fca5a5;
    font: inherit;
    font-weight: 700;
    font-size: 11px;
    padding: 7px 9px;
    border-radius: 8px;
    cursor: pointer;
    white-space: nowrap;
  }}
  .inv-dump-row button:hover {{
    background: rgba(248, 113, 113, 0.15);
    color: #fecaca;
  }}
  .inv-empty {{
    padding: 28px 10px;
    text-align: center;
    color: var(--muted);
    font-size: 12px;
    line-height: 1.45;
  }}
  .inv-row {{
    display: grid;
    grid-template-columns: 36px 1fr auto;
    gap: 10px;
    align-items: center;
    padding: 8px 4px;
    border-radius: 10px;
    cursor: pointer;
  }}
  .inv-row:hover {{ background: rgba(var(--purple-rgb), 0.08); }}
  .inv-row img, .inv-row .noimg {{
    width: 36px;
    height: 36px;
    border-radius: 8px;
    object-fit: contain;
    background: #0d0b14;
  }}
  .inv-row .noimg {{
    display: grid;
    place-items: center;
    font-size: 10px;
    color: var(--muted);
  }}
  .inv-row .name {{
    font-size: 12px;
    font-weight: 700;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .inv-row .meta {{
    font-size: 11px;
    color: var(--muted);
    margin-top: 1px;
  }}
  .inv-row .qty {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .inv-row .qty button {{
    width: 22px;
    height: 22px;
    border: 1px solid var(--line);
    border-radius: 6px;
    background: transparent;
    color: var(--text);
    font-size: 14px;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    display: grid;
    place-items: center;
  }}
  .inv-row .qty button:hover {{
    border-color: var(--purple);
    color: var(--purple-bright);
  }}
  .inv-row .qty span {{
    min-width: 16px;
    text-align: center;
    font-size: 12px;
    font-weight: 800;
    font-variant-numeric: tabular-nums;
  }}
  .inv-clear {{
    border: none;
    background: none;
    color: var(--muted);
    font: inherit;
    font-size: 11px;
    font-weight: 600;
    cursor: pointer;
    padding: 4px;
    text-align: center;
  }}
  .inv-clear:hover {{ color: var(--red); }}

  .graph-backdrop {{
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.72);
    display: none;
    align-items: center;
    justify-content: center;
    padding: 16px;
    z-index: 70;
  }}
  .graph-backdrop.open {{ display: flex; }}
  .graph-modal {{
    width: min(960px, 96vw);
    height: min(94vh, 980px);
    background: var(--card);
    border: 1px solid var(--line-strong);
    border-radius: 18px;
    box-shadow: 0 24px 60px rgba(0,0,0,0.55);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }}
  .graph-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    border-bottom: 1px solid var(--line);
    flex-shrink: 0;
  }}
  .graph-head h3 {{
    margin: 0;
    font-size: 18px;
    font-weight: 800;
    color: var(--purple-bright);
  }}
  .graph-body {{
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 18px;
    padding: 18px 20px 20px;
    overflow: hidden;
  }}
  .graph-top {{
    flex-shrink: 0;
  }}
  .graph-meta {{
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 10px 16px;
    margin-bottom: 12px;
    font-size: 13px;
    color: var(--muted);
  }}
  .graph-meta strong {{
    color: var(--text);
    font-weight: 800;
  }}
  .graph-meta .delta.up {{ color: var(--green-soft); }}
  .graph-meta .delta.down {{ color: #f87171; }}
  .chart-wrap {{
    position: relative;
    width: 100%;
    background: #0d0b14;
    border-radius: 12px;
    border: 1px solid var(--line);
    overflow: hidden;
  }}
  .chart-wrap.spark {{
    background: #141414;
    border-color: #2a2a2a;
    border-radius: 8px;
  }}
  .graph-svg,
  .chart-wrap .hspark {{
    width: 100%;
    height: 200px;
    display: block;
    background: transparent;
    border: none;
    border-radius: 0;
  }}
  .chart-wrap.spark .hspark {{
    height: 110px;
  }}
  .chart-hit {{
    position: absolute;
    width: 18px;
    height: 18px;
    margin: -9px 0 0 -9px;
    border: none;
    padding: 0;
    border-radius: 50%;
    background: transparent;
    cursor: crosshair;
    z-index: 2;
  }}
  .chart-dot {{
    position: absolute;
    width: 7px;
    height: 7px;
    margin: -3.5px 0 0 -3.5px;
    border-radius: 50%;
    background: var(--dot, var(--purple-bright));
    box-shadow: 0 0 0 2px rgba(13, 11, 20, 0.85);
    pointer-events: none;
    z-index: 1;
    opacity: 0.85;
    transition: transform .12s ease, opacity .12s ease;
  }}
  .chart-wrap.spark .chart-dot {{
    width: 6px;
    height: 6px;
    margin: -3px 0 0 -3px;
  }}
  .chart-dot.active {{
    transform: scale(1.55);
    opacity: 1;
    box-shadow: 0 0 0 3px rgba(13, 11, 20, 0.9), 0 0 12px rgba(var(--purple-rgb), 0.45);
  }}
  .chart-cross {{
    position: absolute;
    inset: 0;
    pointer-events: none;
    z-index: 1;
    opacity: 0;
  }}
  .chart-cross.on {{ opacity: 1; }}
  .chart-cross .vline,
  .chart-cross .hline {{
    position: absolute;
    background: rgba(var(--purple-bright-rgb), 0.28);
  }}
  .chart-cross .vline {{
    top: 0;
    bottom: 0;
    width: 1px;
  }}
  .chart-cross .hline {{
    left: 0;
    right: 0;
    height: 1px;
  }}
  .chart-tooltip {{
    position: absolute;
    z-index: 4;
    min-width: 128px;
    max-width: min(220px, calc(100% - 12px));
    padding: 8px 10px;
    border-radius: 10px;
    border: 1px solid var(--line-strong);
    background: linear-gradient(180deg, var(--card-2), var(--card));
    box-shadow: var(--shadow);
    color: var(--text);
    font-size: 12px;
    line-height: 1.35;
    pointer-events: none;
    opacity: 0;
    left: 0;
    top: 0;
    transform: none;
    transition: opacity .12s ease;
  }}
  .chart-tooltip.on {{ opacity: 1; }}
  .chart-tooltip .tt-when {{
    color: var(--muted);
    font-size: 11px;
    font-weight: 700;
    margin-bottom: 3px;
  }}
  .chart-tooltip .tt-val {{
    font-weight: 800;
    font-size: 14px;
  }}
  .chart-tooltip .tt-delta {{
    margin-top: 3px;
    font-size: 11px;
    font-weight: 700;
    color: var(--muted);
  }}
  .chart-tooltip .tt-delta.up {{ color: var(--green-soft); }}
  .chart-tooltip .tt-delta.down {{ color: #f87171; }}
  .graph-empty {{
    height: 200px;
    display: grid;
    place-items: center;
    color: var(--muted);
    font-size: 14px;
    text-align: center;
    padding: 20px;
    background: #0d0b14;
    border-radius: 12px;
    border: 1px solid var(--line);
  }}
  .inv-hist-section {{
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    border-top: 1px solid var(--line);
    padding-top: 16px;
  }}
  .inv-hist-section h4 {{
    margin: 0 0 6px;
    font-size: 14px;
    font-weight: 800;
    letter-spacing: 0.04em;
    color: var(--purple-bright);
    flex-shrink: 0;
  }}
  .inv-hist-hint {{
    margin: 0 0 12px;
    font-size: 12px;
    color: var(--muted);
    flex-shrink: 0;
  }}
  .inv-hist-list {{
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 12px;
    overflow: auto;
    padding-right: 6px;
  }}
  .inv-hist-empty {{
    color: var(--muted);
    font-size: 13px;
    line-height: 1.5;
    padding: 14px 4px;
  }}
  .inv-hist-card {{
    border: 1px solid var(--line);
    border-radius: 14px;
    background: #0d0b14;
    overflow: hidden;
    flex-shrink: 0;
  }}
  .inv-hist-card.open {{
    border-color: rgba(var(--purple-rgb), 0.55);
    box-shadow: 0 0 0 1px rgba(var(--purple-rgb), 0.2);
  }}
  .inv-hist-top {{
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px 18px;
    cursor: pointer;
    width: 100%;
    border: none;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
  }}
  .inv-hist-top:hover {{
    background: rgba(var(--purple-rgb), 0.08);
  }}
  .inv-hist-head-main {{
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
  }}
  .inv-hist-top .when {{
    font-size: 15px;
    font-weight: 800;
    line-height: 1.3;
  }}
  .inv-hist-top .val {{
    font-size: 18px;
    font-weight: 800;
    color: var(--purple-bright);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }}
  .inv-hist-head-sub {{
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }}
  .inv-hist-pill {{
    display: inline-flex;
    align-items: center;
    padding: 5px 10px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: rgba(255,255,255,0.03);
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
  }}
  .inv-hist-pill.delta-up {{
    color: var(--green-soft);
    border-color: rgba(52, 211, 153, 0.35);
    background: rgba(52, 211, 153, 0.08);
  }}
  .inv-hist-pill.delta-down {{
    color: #f87171;
    border-color: rgba(248, 113, 113, 0.35);
    background: rgba(248, 113, 113, 0.08);
  }}
  .inv-hist-pill.chev {{
    margin-left: auto;
    color: var(--purple-bright);
    border-color: rgba(var(--purple-rgb), 0.35);
  }}
  .inv-hist-body {{
    display: none;
    border-top: 1px solid var(--line);
    padding: 16px 18px 18px;
  }}
  .inv-hist-card.open .inv-hist-body {{
    display: block;
  }}
  .inv-hist-items {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 10px;
    max-height: min(42vh, 360px);
    overflow: auto;
    margin-bottom: 14px;
    padding: 2px;
  }}
  .inv-hist-row {{
    display: grid;
    grid-template-columns: 44px 1fr;
    grid-template-rows: auto auto;
    column-gap: 10px;
    row-gap: 2px;
    align-items: center;
    padding: 10px;
    border-radius: 12px;
    border: 1px solid var(--line);
    background: rgba(255,255,255,0.02);
    font-size: 13px;
  }}
  .inv-hist-row img, .inv-hist-row .noimg {{
    grid-row: 1 / span 2;
    width: 44px;
    height: 44px;
    object-fit: contain;
    border-radius: 8px;
    background: #16121f;
  }}
  .inv-hist-row .noimg {{
    display: grid;
    place-items: center;
    color: var(--muted);
    font-size: 11px;
  }}
  .inv-hist-row .name {{
    font-weight: 700;
    line-height: 1.25;
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
  }}
  .inv-hist-row .detail {{
    font-size: 12px;
    color: var(--muted);
    font-weight: 600;
  }}
  .inv-hist-row .detail strong {{
    color: var(--purple-bright);
    font-weight: 800;
  }}
  .inv-hist-actions {{
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }}
  .inv-hist-actions button {{
    border: 1px solid var(--line-strong);
    background: transparent;
    color: var(--text);
    font: inherit;
    font-weight: 700;
    font-size: 13px;
    padding: 10px 14px;
    border-radius: 10px;
    cursor: pointer;
  }}
  .inv-hist-actions button:hover {{
    border-color: var(--purple);
    color: var(--purple-bright);
  }}
  .inv-hist-actions .restore {{
    border-color: var(--green-soft);
    color: var(--green-soft);
  }}
  .inv-hist-actions .restore:hover {{
    background: rgba(52, 211, 153, 0.12);
  }}
  .inv-hist-note {{
    font-size: 12px;
    color: var(--muted);
    margin-top: 10px;
    line-height: 1.4;
  }}

  /* Modal */
  .modal-backdrop {{
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.72);
    display: none;
    align-items: center;
    justify-content: center;
    padding: 20px;
    z-index: 50;
  }}
  .modal-backdrop.open {{ display: flex; }}
  .modal {{
    width: min(920px, 100%);
    max-height: min(80vh, 760px);
    background: var(--card);
    border: 1px solid var(--line-strong);
    border-radius: 18px;
    box-shadow: 0 24px 60px rgba(0,0,0,0.55);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }}
  .modal-head {{
    padding: 16px 18px 12px;
    border-bottom: 1px solid var(--line);
    display: flex;
    gap: 10px;
    align-items: center;
    background: #0e0c16;
  }}
  .modal-head h3 {{
    margin: 0;
    font-size: 16px;
    font-weight: 800;
    white-space: nowrap;
    color: var(--purple-bright);
  }}
  .modal-head input {{
    flex: 1;
    border: 1px solid var(--line-strong);
    border-radius: 10px;
    padding: 10px 12px;
    font: inherit;
    font-size: 14px;
    background: #0d0b14;
    color: var(--text);
  }}
  .modal-head input::placeholder {{ color: #6f6688; }}
  .modal-head select {{
    border: 1px solid var(--line-strong);
    border-radius: 10px;
    padding: 10px 10px;
    font: inherit;
    font-size: 13px;
    background: #0d0b14;
    color: var(--text);
  }}
  .modal-close {{
    border: none;
    background: #2a2438;
    color: var(--text);
    width: 34px;
    height: 34px;
    border-radius: 10px;
    cursor: pointer;
    font-size: 18px;
  }}
  .modal-body {{
    display: grid;
    grid-template-columns: 1fr 200px;
    min-height: 0;
    flex: 1;
    overflow: hidden;
  }}
  .modal-body.no-mine {{
    grid-template-columns: 1fr;
  }}
  .modal-list {{
    overflow: auto;
    padding: 8px;
    min-width: 0;
  }}
  .picker-mine {{
    border-left: 1px solid var(--line);
    background: #0c0a12;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }}
  .picker-mine[hidden] {{ display: none; }}
  .picker-mine-head {{
    padding: 12px 12px 8px;
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.04em;
    color: var(--purple-bright);
    border-bottom: 1px solid var(--line);
  }}
  .picker-mine-list {{
    overflow: auto;
    padding: 6px;
    flex: 1;
  }}
  .mine-row {{
    display: grid;
    grid-template-columns: 32px 1fr;
    gap: 8px;
    align-items: center;
    padding: 7px 6px;
    border-radius: 8px;
    cursor: pointer;
    border: 1px solid transparent;
  }}
  .mine-row:hover {{
    background: rgba(var(--purple-rgb), 0.12);
    border-color: rgba(var(--purple-rgb), 0.3);
  }}
  .mine-row img, .mine-row .noimg {{
    width: 32px;
    height: 32px;
    border-radius: 7px;
    object-fit: contain;
    background: #12101a;
  }}
  .mine-row .noimg {{
    display: grid;
    place-items: center;
    font-size: 9px;
    color: var(--muted);
  }}
  .mine-row .name {{
    font-size: 11px;
    font-weight: 700;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .mine-row .meta {{
    font-size: 10px;
    color: var(--muted);
    margin-top: 1px;
  }}
  .picker-mine-empty {{
    padding: 16px 10px;
    text-align: center;
    color: var(--muted);
    font-size: 11px;
    line-height: 1.4;
  }}
  @media (max-width: 700px) {{
    .modal-body {{ grid-template-columns: 1fr; }}
    .picker-mine {{
      border-left: none;
      border-top: 1px solid var(--line);
      max-height: 160px;
    }}
  }}
  .item-row {{
    display: grid;
    grid-template-columns: 52px 1fr auto;
    gap: 12px;
    align-items: center;
    padding: 10px;
    border-radius: 12px;
    cursor: pointer;
    border: 1px solid transparent;
  }}
  .item-row:hover {{
    background: rgba(var(--purple-rgb), 0.1);
    border-color: rgba(var(--purple-rgb), 0.35);
  }}
  .item-row img, .item-row .noimg {{
    width: 52px;
    height: 52px;
    border-radius: 10px;
    object-fit: contain;
    background: #0d0b14;
    border: 1px solid var(--line);
  }}
  .item-row .noimg {{
    display: grid;
    place-items: center;
    font-size: 10px;
    color: var(--muted);
  }}
  .item-row .name {{ font-weight: 700; font-size: 14px; }}
  .item-row .meta {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
  .item-row .val {{
    font-weight: 800;
    font-variant-numeric: tabular-nums;
    color: var(--purple-bright);
  }}
  .modal-empty {{
    padding: 40px 16px;
    text-align: center;
    color: var(--muted);
  }}

  /* Item detail (Supreme Values style) */
  .detail-backdrop {{
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.62);
    display: none;
    align-items: center;
    justify-content: center;
    padding: 20px;
    z-index: 90;
  }}
  .detail-backdrop.open {{ display: flex; }}
  .detail {{
    width: min(560px, 100%);
    background: #0a0810;
    color: #f2f2f2;
    border: 1px solid var(--line-strong);
    border-radius: 10px;
    box-shadow: 0 28px 70px rgba(0,0,0,0.55), 0 0 0 1px rgba(var(--purple-rgb), 0.15);
    overflow: hidden;
    font-family: "Outfit", system-ui, sans-serif;
  }}
  .detail-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 16px 8px;
    border-bottom: 1px solid var(--line);
  }}
  .detail-top .title {{
    font-size: 15px;
    font-weight: 700;
    text-decoration: underline;
    text-underline-offset: 3px;
    color: var(--purple-bright);
  }}
  .detail-top .actions {{
    display: flex;
    gap: 8px;
    align-items: center;
  }}
  .detail-x {{
    border: none;
    background: transparent;
    color: #fff;
    font-size: 22px;
    line-height: 1;
    cursor: pointer;
    padding: 0 4px;
  }}
  .detail-body {{
    display: grid;
    grid-template-columns: 1.15fr 0.85fr;
    gap: 12px;
    padding: 16px 18px 12px;
    align-items: start;
  }}
  .detail-stats {{
    font-size: 14px;
    line-height: 1.55;
  }}
  .detail-stats .iname {{
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 2px;
    margin-bottom: 8px;
  }}
  .detail-stats .iname-label {{
    font-weight: 800;
    font-size: 16px;
    text-decoration: underline;
    text-underline-offset: 3px;
  }}
  .detail-stats .row {{ margin: 2px 0; }}
  .detail-stats .v {{ color: #7ec8ff; font-weight: 700; }}
  .detail-stats .na {{ color: #b8b8b8; font-weight: 600; }}
  .detail-stats .change {{ color: #6fdf7a; font-weight: 700; }}
  .detail-stats .change.down {{ color: #ff6b6b; }}
  .detail-history {{
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px solid #2a2a2a;
  }}
  .detail-history .hlabel {{
    font-size: 12px;
    font-weight: 700;
    color: #cfcfcf;
    margin-bottom: 8px;
  }}
  .detail-history .hspark {{
    width: 100%;
    height: 110px;
    display: block;
    background: transparent;
    border: none;
    border-radius: 0;
  }}
  .detail-history .hmeta {{
    margin-top: 8px;
    font-size: 11px;
    color: #9a9a9a;
    display: flex;
    flex-wrap: wrap;
    gap: 6px 12px;
  }}
  .detail-history .hmeta span strong {{
    color: #ddd;
    font-weight: 800;
  }}
  .detail-history .hmeta .delta.up {{ color: var(--green-soft); }}
  .detail-history .hmeta .delta.down {{ color: #f87171; }}
  .detail-history .hempty {{
    font-size: 12px;
    color: #888;
  }}
  .detail-art {{
    width: 100%;
    aspect-ratio: 1;
    object-fit: contain;
    background: radial-gradient(circle at 50% 40%, #1a1a1a 0%, #050505 70%);
    border-radius: 8px;
  }}
  .detail-art.missing {{
    display: grid;
    place-items: center;
    color: #666;
    font-size: 12px;
  }}
  .detail-foot {{
    border-top: 1px solid #2a2a2a;
    padding: 10px 18px 14px;
    font-size: 13px;
    color: #ddd;
  }}
  .detail-foot em {{ font-style: italic; color: #cfcfcf; }}

  @media (max-width: 1280px) {{
    .shell {{ grid-template-columns: minmax(0, 1fr) 280px; }}
    .trends-panel {{ order: 3; position: static; max-height: none; }}
  }}
  @media (max-width: 1100px) {{
    .shell {{ grid-template-columns: 1fr; }}
    .inv-panel {{ position: static; max-height: none; }}
    .trends-panel {{ position: static; max-height: none; }}
  }}
  @media (max-width: 900px) {{
    .compare {{ grid-template-columns: 1fr; }}
    .boards {{ grid-template-columns: 1fr; }}
    .center {{ padding-top: 8px; flex-direction: row; flex-wrap: wrap; }}
    .value-box {{ max-width: 220px; margin: 0 auto; }}
    .detail-body {{ grid-template-columns: 1fr; }}
  }}

  /* Theme picker (footer chrome) */
  .theme-bar {{
    position: fixed;
    z-index: 50;
    left: 14px;
    bottom: 14px;
    font-family: inherit;
  }}
  .theme-wrap {{
    position: relative;
  }}
  .theme-toggle {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    border: 1px solid var(--line-strong);
    background: linear-gradient(180deg, var(--card-2), var(--card));
    color: var(--text);
    font-family: inherit;
    font-weight: 700;
    font-size: 13px;
    padding: 10px 14px;
    border-radius: 12px;
    cursor: pointer;
    box-shadow: var(--shadow);
  }}
  .theme-toggle:hover,
  .theme-toggle[aria-expanded="true"] {{
    border-color: var(--purple);
    color: var(--purple-bright);
  }}
  .theme-toggle .theme-dot {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--theme-dot, var(--purple));
    box-shadow: 0 0 0 2px rgba(var(--purple-rgb), 0.28);
    flex-shrink: 0;
  }}
  .theme-panel {{
    position: absolute;
    left: 0;
    bottom: calc(100% + 10px);
    width: min(320px, calc(100vw - 28px));
    max-height: min(70vh, 560px);
    overflow-x: hidden;
    overflow-y: auto;
    padding: 14px;
    border-radius: 14px;
    border: 1px solid var(--line-strong);
    background: linear-gradient(180deg, var(--card-2), var(--card));
    box-shadow: var(--shadow);
  }}
  .theme-panel[hidden] {{ display: none; }}
  .theme-panel-label {{
    margin: 0 0 10px;
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
  }}
  .theme-panel-label.spaced {{
    margin-top: 14px;
  }}
  .theme-fx-toggle {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 14px;
    padding-top: 12px;
    border-top: 1px solid var(--line);
    cursor: pointer;
    user-select: none;
    font-size: 12px;
    font-weight: 700;
    color: var(--muted);
  }}
  .theme-fx-toggle-top {{
    margin-top: 0;
    margin-bottom: 4px;
    padding-top: 0;
    padding-bottom: 12px;
    border-top: none;
    border-bottom: 1px solid var(--line);
    color: var(--text);
  }}
  .theme-fx-toggle:hover {{ color: var(--text); }}
  .theme-fx-toggle input {{
    appearance: none;
    width: 34px;
    height: 20px;
    margin: 0;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: rgba(255, 255, 255, 0.06);
    position: relative;
    cursor: pointer;
    flex-shrink: 0;
    transition: background .15s ease, border-color .15s ease;
  }}
  .theme-fx-toggle input::after {{
    content: '';
    position: absolute;
    top: 2px;
    left: 2px;
    width: 14px;
    height: 14px;
    border-radius: 50%;
    background: #c4b5d4;
    transition: transform .15s ease, background .15s ease;
  }}
  .theme-fx-toggle input:checked {{
    background: color-mix(in srgb, var(--purple-bright) 55%, transparent);
    border-color: rgba(var(--purple-bright-rgb), 0.55);
  }}
  .theme-fx-toggle input:checked::after {{
    transform: translateX(14px);
    background: #fff;
  }}
  body[data-fx-off="1"] .bg-ambient,
  body[data-fx-off="1"] .bg-texture,
  body[data-fx-off="1"] .bg-effect,
  body[data-fx-off="1"] .weather-fx,
  body[data-fx-off="1"] .cursor-trail,
  body[data-fx-off="1"] .bg-cursor-glow {{
    display: none !important;
  }}
  .theme-presets {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }}
  .theme-swatch {{
    width: 28px;
    height: 28px;
    border-radius: 9px;
    border: 2px solid rgba(255, 255, 255, 0.12);
    background: var(--swatch);
    cursor: pointer;
    padding: 0;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.18);
  }}
  .theme-swatch.mix {{
    width: 34px;
    height: 34px;
    border-radius: 10px;
  }}
  .theme-swatch.black {{
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.22);
  }}
  .theme-swatch.black[data-black="matte"] {{ --swatch: #2c2c30; }}
  .theme-swatch.black[data-black="jet"] {{ --swatch: #0c0c0e; }}
  .theme-swatch.black[data-black="void"] {{ --swatch: #000000; }}
  .theme-swatch:hover {{
    border-color: rgba(255, 255, 255, 0.45);
    transform: translateY(-1px);
  }}
  .theme-swatch.active {{
    border-color: #fff;
    box-shadow: 0 0 0 2px rgba(var(--purple-rgb), 0.45), inset 0 1px 0 rgba(255,255,255,0.18);
  }}
  .theme-dot {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--theme-dot, var(--purple));
    box-shadow: 0 0 0 1px rgba(255,255,255,0.2);
  }}
  .theme-variants {{
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }}
  .theme-variant {{
    border: 1px solid var(--line);
    background: rgba(13, 11, 20, 0.55);
    color: var(--muted);
    font-family: inherit;
    font-weight: 700;
    font-size: 11px;
    padding: 7px 9px;
    border-radius: 9px;
    cursor: pointer;
    line-height: 1.1;
  }}
  .theme-variant:hover {{
    border-color: var(--purple);
    color: var(--purple-bright);
  }}
  .theme-variant.active {{
    border-color: var(--purple);
    color: var(--text);
    background: rgba(var(--purple-rgb), 0.16);
    box-shadow: 0 0 0 1px rgba(var(--purple-rgb), 0.25);
  }}
  .theme-advanced-btn {{
    margin-top: 12px;
    width: 100%;
    border: 1px solid var(--line);
    background: transparent;
    color: var(--muted);
    font-family: inherit;
    font-weight: 700;
    font-size: 12px;
    padding: 8px 10px;
    border-radius: 10px;
    cursor: pointer;
  }}
  .theme-advanced-btn:hover,
  .theme-advanced-btn[aria-expanded="true"] {{
    border-color: var(--purple);
    color: var(--purple-bright);
  }}
  .theme-advanced {{
    margin-top: 10px;
    padding-top: 10px;
    border-top: 1px solid var(--line);
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 8px;
    align-items: center;
  }}
  .theme-advanced[hidden] {{ display: none; }}
  .theme-advanced input[type="color"] {{
    width: 40px;
    height: 34px;
    padding: 0;
    border: 1px solid var(--line-strong);
    border-radius: 8px;
    background: transparent;
    cursor: pointer;
  }}
  .theme-advanced input[type="color"]::-webkit-color-swatch-wrapper {{ padding: 3px; }}
  .theme-advanced input[type="color"]::-webkit-color-swatch {{
    border: none;
    border-radius: 5px;
  }}
  .theme-hex {{
    width: 100%;
    height: 34px;
    border: 1px solid var(--line-strong);
    border-radius: 8px;
    background: #0d0b14;
    color: var(--text);
    font-family: inherit;
    font-weight: 700;
    font-size: 13px;
    padding: 0 10px;
  }}
  .theme-hex:focus {{
    outline: none;
    border-color: var(--purple);
    box-shadow: 0 0 0 1px rgba(var(--purple-rgb), 0.35);
  }}
  @media (prefers-reduced-motion: no-preference) {{
    .theme-swatch {{ transition: border-color .15s ease, transform .15s ease, box-shadow .15s ease; }}
    .theme-toggle {{ transition: border-color .15s ease, color .15s ease; }}
    .theme-variant {{ transition: border-color .15s ease, color .15s ease, background .15s ease; }}
  }}
</style>
</head>
<body>
  <div class="bg-ambient" id="bgAmbient" aria-hidden="true">
    <div class="bg-blob b1"></div>
    <div class="bg-blob b2"></div>
    <div class="bg-blob b3"></div>
    <div class="bg-blob b4"></div>
    <div class="bg-blob b5"></div>
    <div class="bg-blob b6"></div>
    <div class="bg-cursor-glow" id="bgCursorGlow"></div>
  </div>
  <div class="bg-texture" id="bgTexture" aria-hidden="true"></div>
  <div class="bg-effect" id="bgEffect" aria-hidden="true"></div>
  <div class="weather-fx" id="weatherFx" aria-hidden="true"></div>
  <div class="cursor-trail" id="cursorTrail" aria-hidden="true"></div>
  <div class="shell">
  <aside class="trends-panel" aria-label="Market trends">
    <h2>Market Pulse</h2>
    <div class="trends-block h-hot">
      <h3>Constantly rising</h3>
      <div class="trends-list" id="trendRisers"></div>
    </div>
    <div class="trends-block h-up">
      <h3>Recent raises</h3>
      <div class="trends-list" id="trendRaises"></div>
    </div>
    <div class="trends-block h-down">
      <h3>Recent drops</h3>
      <div class="trends-list" id="trendDrops"></div>
    </div>
  </aside>
  <div class="wrap">
    <div class="wrap-head">
      <h1>Lunix's AI Trade Assistant</h1>
      <label class="set-protect-toggle" title="Type anywhere to search — add to Your Offer or Their Offer">
        <input type="checkbox" id="quickSearchToggle" />
        Quick search
      </label>
    </div>
    <div class="quick-search" id="quickSearchWrap" hidden>
      <div class="quick-search-row">
        <input id="quickSearch" type="search" placeholder="Type to search items…" autocomplete="off" />
        <select id="quickRarity" aria-label="Rarity filter">
          <option value="">All rarities</option>
          <option>Ancient</option>
          <option>Godly</option>
          <option>Vintage</option>
          <option>Chroma</option>
          <option>Unique</option>
          <option>Legendary</option>
          <option>Rare</option>
          <option>Uncommon</option>
          <option>Common</option>
          <option>Set</option>
        </select>
      </div>
      <p class="quick-hint">Start typing anywhere · Add to offer = Your Offer · Add to request = Their Offer</p>
      <div class="quick-results" id="quickResults" hidden></div>
    </div>

    <section class="compare">
      <div class="value-box">
        <div class="num" id="yourValue">0</div>
        <div class="label">VALUE</div>
      </div>
      <div class="meter-wrap">
        <div class="meter"><div class="meter-fill" id="meterFill"></div></div>
        <p class="verdict fair" id="verdict">—</p>
      </div>
      <div class="value-box">
        <div class="num" id="theirValue">0</div>
        <div class="label">VALUE</div>
      </div>
    </section>

    <div class="trade-caution" id="tradeCaution" role="status" aria-live="polite"></div>

    <section class="boards">
      <div class="board">
        <h2>Your Offer</h2>
        <div class="grid" id="yourGrid"></div>
      </div>

      <div class="center">
        <button class="gen-offer" id="genOfferBtn" type="button" hidden>Generate Offer</button>
        <button class="gen-offer receive" id="genReceiveBtn" type="button" hidden>Generate Receive</button>
        <button class="gen-offer lower" id="lowerOfferBtn" type="button" hidden>Lower Offer</button>
        <button class="gen-offer higher" id="higherOfferBtn" type="button" hidden>Higher Offer</button>
        <button class="complete-offer" id="completeOfferBtn" type="button" hidden>Offer Completed</button>
        <div class="history-row">
          <button class="history-btn" id="undoBtn" type="button" disabled>Undo</button>
          <button class="history-btn" id="redoBtn" type="button" disabled>Redo</button>
        </div>
        <button class="trade-hist-btn" id="tradeHistBtn" type="button" title="View saved trades">
          Trade History
          <span class="trade-hist-badge" id="tradeHistBadge">0</span>
        </button>
        <button class="reset" id="resetBtn" type="button">Reset Trade</button>
      </div>

      <div class="board" id="theirBoard">
        <h2>Their Offer</h2>
        <div class="grid" id="theirGrid"></div>
      </div>
    </section>

    <section class="suggest" aria-label="Suggested trades">
      <div class="suggest-head">
        <h2>Suggested Trades</h2>
        <div class="suggest-toggles">
          <label class="set-protect-toggle" title="When on, complete sets stay intact — only extras and whole sets are used">
            <input type="checkbox" id="avoidSetBreaks" checked />
            Avoid set breaks
          </label>
          <label class="set-protect-toggle" title="Aim suggested receives at Market Pulse hot items and rising values">
            <input type="checkbox" id="autoTargetHot" />
            Auto-target hot/rising
          </label>
        </div>
      </div>
      <div class="target-box">
        <div class="target-top">
          <h3>TARGET ITEMS</h3>
          <div class="target-actions">
            <button class="primary" id="targetAddBtn" type="button">Add target</button>
            <button id="targetClearBtn" type="button">Clear</button>
          </div>
        </div>
        <div class="target-chip-row" id="targetList"></div>
      </div>
      <div class="target-box dump-box">
        <div class="target-top">
          <h3>ITEMS TO TRADE OFF</h3>
          <div class="target-actions">
            <button class="primary" id="dumpAddBtn" type="button">Add item</button>
            <button id="dumpClearBtn" type="button">Clear</button>
          </div>
        </div>
        <div class="target-chip-row" id="dumpList"></div>
      </div>
      <div class="suggest-list" id="suggestList"></div>
    </section>

  </div>

  <aside class="inv-panel" aria-label="My items">
    <div class="inv-head">
      <h2>My Items</h2>
      <span class="inv-count" id="invCount">0 items</span>
    </div>
    <div class="inv-value-block">
      <div class="total" id="invTotal">0</div>
      <div class="inv-value-row">
        <span class="inv-delta flat" id="invDelta">—</span>
        <span class="inv-since" id="invSince">all time —</span>
      </div>
      <div class="inv-status" id="invStatus" hidden></div>
    </div>
    <div class="inv-actions">
      <button class="primary" id="invAddBtn" type="button">Add</button>
      <button class="save" id="invSaveBtn" type="button">Save</button>
      <button id="invGraphBtn" type="button">Graph</button>
    </div>
    <div class="inv-dump" id="invDumpTips"></div>
    <div class="inv-list" id="invList"></div>
    <button class="inv-clear" id="invClearBtn" type="button">Clear all</button>
  </aside>
  </div>

  <div class="theme-bar">
    <div class="theme-wrap">
      <button class="theme-toggle" id="themeBtn" type="button" aria-expanded="false" aria-controls="themePanel">
        <span class="theme-dot" aria-hidden="true"></span>
        Themes
      </button>
      <div class="theme-panel" id="themePanel" role="dialog" aria-label="Theme settings" hidden>
        <label class="theme-fx-toggle theme-fx-toggle-top" title="Hide cursor trail, animated backgrounds, textures, and weather effects">
          <input type="checkbox" id="themeFxOff" />
          Disable effects
        </label>
        <p class="theme-panel-label spaced">Accent color</p>
        <div class="theme-presets" id="themePresets" role="list">
          <button type="button" class="theme-swatch" role="listitem" data-color="#a855f7" style="--swatch:#a855f7" aria-label="Violet" title="Violet"></button>
          <button type="button" class="theme-swatch" role="listitem" data-color="#f43f5e" style="--swatch:#f43f5e" aria-label="Rose" title="Rose"></button>
          <button type="button" class="theme-swatch" role="listitem" data-color="#f59e0b" style="--swatch:#f59e0b" aria-label="Amber" title="Amber"></button>
          <button type="button" class="theme-swatch" role="listitem" data-color="#10b981" style="--swatch:#10b981" aria-label="Emerald" title="Emerald"></button>
          <button type="button" class="theme-swatch" role="listitem" data-color="#38bdf8" style="--swatch:#38bdf8" aria-label="Sky" title="Sky"></button>
          <button type="button" class="theme-swatch" role="listitem" data-color="#e879f9" style="--swatch:#e879f9" aria-label="Magenta" title="Magenta"></button>
          <button type="button" class="theme-swatch" role="listitem" data-color="#fb7185" style="--swatch:#fb7185" aria-label="Coral" title="Coral"></button>
          <button type="button" class="theme-swatch" role="listitem" data-color="#6366f1" style="--swatch:#6366f1" aria-label="Indigo" title="Indigo"></button>
          <button type="button" class="theme-swatch chroma" role="listitem" data-color="#a855f7" data-chroma="1" aria-label="Chroma" title="Chroma"></button>
        </div>
        <p class="theme-panel-label spaced">Black</p>
        <div class="theme-presets" id="themeBlacks" role="list">
          <button type="button" class="theme-swatch black" role="listitem" data-color="#2c2c30" data-black="matte" style="--swatch:#2c2c30" aria-label="Matte Black" title="Matte Black"></button>
          <button type="button" class="theme-swatch black" role="listitem" data-color="#0c0c0e" data-black="jet" style="--swatch:#0c0c0e" aria-label="Jet Black" title="Jet Black"></button>
          <button type="button" class="theme-swatch black" role="listitem" data-color="#000000" data-black="void" style="--swatch:#000000" aria-label="Very Dark Black" title="Very Dark Black"></button>
        </div>
        <p class="theme-panel-label spaced">Mixtures</p>
        <div class="theme-presets" id="themeMixtures" role="list">
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#7c3aed" data-shift="#ea580c" style="--swatch:linear-gradient(135deg,#7c3aed,#ea580c)" aria-label="Violet Ember" title="Violet Ember"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#db2777" data-shift="#2563eb" style="--swatch:linear-gradient(135deg,#db2777,#2563eb)" aria-label="Magenta Blue" title="Magenta Blue"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#14532d" data-shift="#ca8a04" style="--swatch:linear-gradient(135deg,#14532d,#ca8a04)" aria-label="Forest Gold" title="Forest Gold"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#7f1d1d" data-shift="#111827" style="--swatch:linear-gradient(135deg,#7f1d1d,#111827)" aria-label="Crimson Night" title="Crimson Night"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#312e81" data-shift="#1e3a8a" style="--swatch:linear-gradient(135deg,#312e81,#1e3a8a)" aria-label="Indigo Navy" title="Indigo Navy"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#0f766e" data-shift="#a21caf" style="--swatch:linear-gradient(180deg,#0f766e,#a21caf)" aria-label="Teal Magenta" title="Teal Magenta"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#5b21b6" data-shift="#f59e0b" style="--swatch:linear-gradient(180deg,#5b21b6,#f59e0b)" aria-label="Purple Solar" title="Purple Solar"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#0e7490" data-shift="#1d4ed8" style="--swatch:linear-gradient(135deg,#0e7490,#1d4ed8)" aria-label="Teal Royal" title="Teal Royal"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#4d7c0f" data-shift="#78350f" style="--swatch:linear-gradient(135deg,#4d7c0f,#78350f)" aria-label="Olive Earth" title="Olive Earth"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#7c2d12" data-shift="#92400e" style="--swatch:linear-gradient(135deg,#7c2d12,#92400e)" aria-label="Ember Wood" title="Ember Wood"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#64748b" data-shift="#3b82f6" style="--swatch:linear-gradient(135deg,#64748b,#3b82f6)" aria-label="Slate Sky" title="Slate Sky"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#86efac" data-shift="#fde68a" style="--swatch:linear-gradient(180deg,#fde68a,#86efac)" aria-label="Mint Lemon" title="Mint Lemon"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#93c5fd" data-shift="#ddd6fe" style="--swatch:linear-gradient(135deg,#93c5fd,#ddd6fe)" aria-label="Sky Lavender" title="Sky Lavender"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#fdba74" data-shift="#fde68a" style="--swatch:linear-gradient(180deg,#fde68a,#fdba74)" aria-label="Peach Cream" title="Peach Cream"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#f0abfc" data-shift="#fef08a" style="--swatch:linear-gradient(180deg,#fef08a,#f0abfc)" aria-label="Mauve Glow" title="Mauve Glow"></button>
          <button type="button" class="theme-swatch mix" role="listitem" data-color="#1e40af" data-shift="#1d4ed8" style="--swatch:linear-gradient(135deg,#1e3a8a,#2563eb)" aria-label="Royal Blue" title="Royal Blue"></button>
        </div>
        <p class="theme-panel-label spaced">Background</p>
        <div class="theme-variants" id="themeVariants" role="list">
          <button type="button" class="theme-variant" role="listitem" data-variant="aurora" aria-label="Aurora">Aurora</button>
          <button type="button" class="theme-variant" role="listitem" data-variant="mesh" aria-label="Mesh">Mesh</button>
          <button type="button" class="theme-variant" role="listitem" data-variant="blobs" aria-label="Soft blobs">Soft blobs</button>
          <button type="button" class="theme-variant" role="listitem" data-variant="pulse" aria-label="Subtle pulse">Subtle pulse</button>
          <button type="button" class="theme-variant" role="listitem" data-variant="rainy" aria-label="Rainy window">Rainy window</button>
          <button type="button" class="theme-variant" role="listitem" data-variant="minimal" aria-label="Minimal">Minimal</button>
        </div>
        <p class="theme-panel-label spaced">Texture</p>
        <div class="theme-variants" id="themeTextures" role="list">
          <button type="button" class="theme-variant" role="listitem" data-texture="none" aria-label="None">None</button>
          <button type="button" class="theme-variant" role="listitem" data-texture="grain" aria-label="Grain">Grain</button>
          <button type="button" class="theme-variant" role="listitem" data-texture="grid" aria-label="Grid">Grid</button>
          <button type="button" class="theme-variant" role="listitem" data-texture="carbon" aria-label="Carbon">Carbon</button>
          <button type="button" class="theme-variant" role="listitem" data-texture="ripple" aria-label="Ripple">Ripple</button>
          <button type="button" class="theme-variant" role="listitem" data-texture="diagonal" aria-label="Diagonal">Diagonal</button>
        </div>
        <p class="theme-panel-label spaced">Effects</p>
        <div class="theme-variants" id="themeEffects" role="list">
          <button type="button" class="theme-variant" role="listitem" data-effect="none" aria-label="None">None</button>
          <button type="button" class="theme-variant" role="listitem" data-effect="stars" aria-label="Stars">Stars</button>
          <button type="button" class="theme-variant" role="listitem" data-effect="snow" aria-label="Snow">Snow</button>
          <button type="button" class="theme-variant" role="listitem" data-effect="rain" aria-label="Rain">Rain</button>
        </div>
        <button class="theme-advanced-btn" id="themeAdvBtn" type="button" aria-expanded="false" aria-controls="themeAdvanced">Advanced</button>
        <div class="theme-advanced" id="themeAdvanced" hidden>
          <input type="color" id="themeColor" value="#a855f7" aria-label="Custom theme color" />
          <input class="theme-hex" id="themeHex" type="text" maxlength="7" spellcheck="false" placeholder="#a855f7" aria-label="Theme hex color" />
        </div>
      </div>
    </div>
  </div>

  <div class="graph-backdrop" id="tradeHistModal" role="dialog" aria-modal="true">
    <div class="graph-modal trade-hist-modal">
      <div class="graph-head">
        <h3>Trade history</h3>
        <button class="modal-close" id="tradeHistClose" type="button" aria-label="Close">×</button>
      </div>
      <div class="trade-hist-body">
        <aside class="trade-hist-sidebar">
          <div class="trade-hist-sidebar-head">
            <div class="trade-hist-meta">
              <span>Saved: <strong id="tradeHistCount">0</strong></span>
              <span>Cap: <strong>40</strong></span>
            </div>
            <input class="trade-hist-filter" id="tradeHistFilter" type="search" placeholder="Filter trades" autocomplete="off" />
          </div>
          <div class="trade-hist-list" id="tradeHistList"></div>
        </aside>
        <section class="trade-hist-detail" id="tradeHistDetail"></section>
      </div>
    </div>
  </div>

  <div class="graph-backdrop prev-trade-backdrop" id="prevTradeModal" role="dialog" aria-modal="true">
    <div class="graph-modal">
      <div class="graph-head">
        <h3 id="prevTradeTitle">Previous trade</h3>
        <button class="modal-close" id="prevTradeClose" type="button" aria-label="Close">×</button>
      </div>
      <div class="prev-trade-body">
        <div class="prev-trade-meta" id="prevTradeMeta"></div>
        <div class="prev-trade-compare" id="prevTradeCompare"></div>
        <div class="prev-trade-boards">
          <div class="prev-trade-board">
            <h2>Your Offer</h2>
            <p class="side-totals" id="prevTradeYourTotals"></p>
            <div class="prev-trade-grid" id="prevTradeYourGrid"></div>
          </div>
          <div class="prev-trade-board">
            <h2>Their Offer</h2>
            <p class="side-totals" id="prevTradeTheirTotals"></p>
            <div class="prev-trade-grid" id="prevTradeTheirGrid"></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="graph-backdrop" id="graphModal" role="dialog" aria-modal="true">
    <div class="graph-modal">
      <div class="graph-head">
        <h3>Inventory history</h3>
        <button class="modal-close" id="graphClose" type="button" aria-label="Close">×</button>
      </div>
      <div class="graph-body">
        <div class="graph-top">
          <div class="graph-meta">
            <span>Saves: <strong id="graphPoints">0</strong></span>
            <span>Min: <strong id="graphMin">—</strong></span>
            <span>Max: <strong id="graphMax">—</strong></span>
            <span>Latest: <strong id="graphLatest">—</strong></span>
            <span>Change: <strong id="graphDelta" class="delta">—</strong></span>
          </div>
          <div id="graphChart"></div>
        </div>
        <div class="inv-hist-section">
          <h4>SNAPSHOTS</h4>
          <div class="inv-hist-list" id="invHistList"></div>
        </div>
      </div>
    </div>
  </div>

  <div class="modal-backdrop" id="modal" role="dialog" aria-modal="true">
    <div class="modal">
      <div class="modal-head">
        <h3 id="pickerTitle">Add item</h3>
        <input id="search" type="search" placeholder="Search Supreme Values…" autocomplete="off" />
        <select id="rarityFilter">
          <option value="">All rarities</option>
          <option>Ancient</option>
          <option>Godly</option>
          <option>Vintage</option>
          <option>Chroma</option>
          <option>Unique</option>
          <option>Legendary</option>
          <option>Rare</option>
          <option>Uncommon</option>
          <option>Common</option>
          <option>Set</option>
        </select>
        <button class="modal-close" id="modalClose" type="button" aria-label="Close">×</button>
      </div>
      <div class="modal-body" id="modalBody">
        <div class="modal-list" id="modalList"></div>
        <aside class="picker-mine" id="pickerMine" aria-label="My items">
          <div class="picker-mine-head">MY ITEMS</div>
          <div class="picker-mine-list" id="pickerMineList"></div>
        </aside>
      </div>
    </div>
  </div>

  <div class="detail-backdrop" id="detail" role="dialog" aria-modal="true">
    <div class="detail">
      <div class="detail-top">
        <div class="title">Extra Features:</div>
        <div class="actions">
          <button class="detail-x" id="detailClose" type="button" aria-label="Close">×</button>
        </div>
      </div>
      <div class="detail-body">
        <div class="detail-stats">
          <div class="iname" id="dName">—</div>
          <div class="row">Value - <span class="v" id="dValue">—</span> <span class="na" id="dValueTag">[N/A]</span></div>
          <div class="row">Stability - <span id="dStability">—</span></div>
          <div class="row">Demand - <span id="dDemand">—</span> • Rarity - <span id="dRarityScore">—</span></div>
          <div class="row">Origin - <span id="dOrigin">—</span></div>
          <div class="row">Change in Value - <span class="change" id="dChange">—</span></div>
          <div class="detail-history" id="dHistory">
            <div class="hlabel">Value history</div>
            <div id="dHistoryBody"></div>
          </div>
        </div>
        <img class="detail-art" id="dArt" alt="" referrerpolicy="no-referrer" />
      </div>
      <div class="detail-foot">Aliases - <em id="dAliases">—</em></div>
    </div>
  </div>

<script>
  const CATALOG = {data_json};
  const TRENDING = {trending_json};

(function initTheme() {{
  const THEME_KEY = 'lunix-mm2-theme-color';
  const THEME_SHIFT_KEY = 'lunix-mm2-theme-shift';
  const THEME_BLACK_KEY = 'lunix-mm2-theme-black';
  const THEME_CHROMA_KEY = 'lunix-mm2-theme-chroma';
  const VARIANT_KEY = 'lunix-mm2-bg-variant';
  const TEXTURE_KEY = 'lunix-mm2-bg-texture';
  const EFFECT_KEY = 'lunix-mm2-bg-effect';
  const FX_OFF_KEY = 'lunix-mm2-fx-off';
  const DEFAULT_THEME = '#a855f7';
  const DEFAULT_VARIANT = 'aurora';
  const DEFAULT_TEXTURE = 'none';
  const DEFAULT_EFFECT = 'none';
  const VARIANTS = ['aurora', 'mesh', 'blobs', 'pulse', 'rainy', 'minimal'];
  const TEXTURES = ['none', 'grain', 'grid', 'carbon', 'ripple', 'diagonal'];
  const EFFECTS = ['none', 'stars', 'snow', 'rain'];
  const LEGACY_EFFECT_TEXTURES = ['stars', 'snow', 'rain'];
  const CHROMA_PERIOD_MS = 16000;
  const CHROMA_TICK_MS = 100;
  const BLACK_PROFILES = {{
    matte: {{
      accent: {{ r: 58, g: 58, b: 64 }},
      bright: {{ r: 186, g: 186, b: 196 }},
      deep: {{ r: 36, g: 36, b: 40 }},
      pale: {{ r: 220, g: 220, b: 228 }},
      shift: {{ r: 90, g: 90, b: 98 }},
      warm: {{ r: 72, g: 68, b: 64 }},
      soft: {{ r: 150, g: 150, b: 158 }},
      bg: {{ r: 20, g: 20, b: 22 }},
      bgTop: {{ r: 28, g: 28, b: 30 }},
      bgBottom: {{ r: 14, g: 14, b: 16 }},
      card: {{ r: 30, g: 30, b: 32 }},
      card2: {{ r: 38, g: 38, b: 42 }},
      line: {{ r: 54, g: 54, b: 58 }},
      lineStrong: {{ r: 72, g: 72, b: 78 }},
      muted: {{ r: 148, g: 148, b: 156 }},
      text: {{ r: 240, g: 240, b: 245 }},
    }},
    jet: {{
      accent: {{ r: 36, g: 36, b: 40 }},
      bright: {{ r: 210, g: 210, b: 216 }},
      deep: {{ r: 16, g: 16, b: 18 }},
      pale: {{ r: 228, g: 228, b: 234 }},
      shift: {{ r: 56, g: 56, b: 62 }},
      warm: {{ r: 48, g: 44, b: 40 }},
      soft: {{ r: 120, g: 120, b: 128 }},
      bg: {{ r: 8, g: 8, b: 10 }},
      bgTop: {{ r: 12, g: 12, b: 14 }},
      bgBottom: {{ r: 4, g: 4, b: 6 }},
      card: {{ r: 16, g: 16, b: 18 }},
      card2: {{ r: 22, g: 22, b: 24 }},
      line: {{ r: 40, g: 40, b: 44 }},
      lineStrong: {{ r: 56, g: 56, b: 60 }},
      muted: {{ r: 132, g: 132, b: 140 }},
      text: {{ r: 244, g: 244, b: 248 }},
    }},
    void: {{
      accent: {{ r: 22, g: 22, b: 24 }},
      bright: {{ r: 230, g: 230, b: 235 }},
      deep: {{ r: 0, g: 0, b: 0 }},
      pale: {{ r: 236, g: 236, b: 240 }},
      shift: {{ r: 40, g: 40, b: 44 }},
      warm: {{ r: 32, g: 28, b: 28 }},
      soft: {{ r: 96, g: 96, b: 104 }},
      bg: {{ r: 0, g: 0, b: 0 }},
      bgTop: {{ r: 4, g: 4, b: 5 }},
      bgBottom: {{ r: 0, g: 0, b: 0 }},
      card: {{ r: 8, g: 8, b: 9 }},
      card2: {{ r: 12, g: 12, b: 14 }},
      line: {{ r: 28, g: 28, b: 30 }},
      lineStrong: {{ r: 42, g: 42, b: 46 }},
      muted: {{ r: 120, g: 120, b: 128 }},
      text: {{ r: 248, g: 248, b: 250 }},
    }},
  }};
  const root = document.documentElement;
  const body = document.body;
  const btn = document.getElementById('themeBtn');
  const panel = document.getElementById('themePanel');
  const advBtn = document.getElementById('themeAdvBtn');
  const adv = document.getElementById('themeAdvanced');
  const colorInput = document.getElementById('themeColor');
  const hexInput = document.getElementById('themeHex');
  const swatches = Array.from(document.querySelectorAll('.theme-swatch'));
  const variantBtns = Array.from(document.querySelectorAll('#themeVariants .theme-variant'));
  const textureBtns = Array.from(document.querySelectorAll('#themeTextures .theme-variant'));
  const effectBtns = Array.from(document.querySelectorAll('#themeEffects .theme-variant'));
  const fxOffToggle = document.getElementById('themeFxOff');
  if (!btn || !panel) return;

  let activeShiftHex = '';
  let activeBlackMode = '';
  let activeChroma = false;
  let chromaTimer = 0;
  let chromaStart = 0;
  const chromaReduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function clamp(n, a, b) {{ return Math.min(b, Math.max(a, n)); }}
  function hexToRgb(hex) {{
    let h = String(hex || '').trim().replace(/^#/, '');
    if (h.length === 3) h = h.split('').map((c) => c + c).join('');
    if (!/^[0-9a-fA-F]{{6}}$/.test(h)) return null;
    const n = parseInt(h, 16);
    return {{ r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 }};
  }}
  function rgbToHex(r, g, b) {{
    return '#' + [r, g, b].map((v) => clamp(Math.round(v), 0, 255).toString(16).padStart(2, '0')).join('');
  }}
  function mixRgb(a, b, t) {{
    return {{
      r: a.r + (b.r - a.r) * t,
      g: a.g + (b.g - a.g) * t,
      b: a.b + (b.b - a.b) * t,
    }};
  }}
  function relativeLuma({{ r, g, b }}) {{
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  }}
  function rgbToHsl({{ r, g, b }}) {{
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    let h = 0, s = 0;
    const l = (max + min) / 2;
    if (max !== min) {{
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      switch (max) {{
        case r: h = ((g - b) / d + (g < b ? 6 : 0)); break;
        case g: h = ((b - r) / d + 2); break;
        default: h = ((r - g) / d + 4); break;
      }}
      h /= 6;
    }}
    return {{ h: h * 360, s, l }};
  }}
  function hslToRgb(h, s, l) {{
    h = ((h % 360) + 360) % 360;
    const c = (1 - Math.abs(2 * l - 1)) * s;
    const x = c * (1 - Math.abs((h / 60) % 2 - 1));
    const m = l - c / 2;
    let r = 0, g = 0, b = 0;
    if (h < 60) {{ r = c; g = x; }}
    else if (h < 120) {{ r = x; g = c; }}
    else if (h < 180) {{ g = c; b = x; }}
    else if (h < 240) {{ g = x; b = c; }}
    else if (h < 300) {{ r = x; b = c; }}
    else {{ r = c; b = x; }}
    return {{ r: (r + m) * 255, g: (g + m) * 255, b: (b + m) * 255 }};
  }}
  function shiftHue(rgb, deg, sMul, lMul) {{
    const hsl = rgbToHsl(rgb);
    return hslToRgb(hsl.h + deg, clamp(hsl.s * (sMul == null ? 1 : sMul), 0, 1), clamp(hsl.l * (lMul == null ? 1 : lMul), 0.08, 0.92));
  }}
  function normalizeAccent(rgb) {{
    const L = relativeLuma(rgb);
    if (L < 0.28) return mixRgb(rgb, {{ r: 255, g: 255, b: 255 }}, 0.28);
    if (L > 0.78) return mixRgb(rgb, {{ r: 0, g: 0, b: 0 }}, 0.22);
    return rgb;
  }}
  function normalizeMixColor(rgb) {{
    // Keep mixture swatch colors close to the icon; only lift near-black / crush near-white
    const L = relativeLuma(rgb);
    if (L < 0.1) return mixRgb(rgb, {{ r: 255, g: 255, b: 255 }}, 0.16);
    if (L > 0.9) return mixRgb(rgb, {{ r: 0, g: 0, b: 0 }}, 0.1);
    return rgb;
  }}
  function setRgbVar(name, {{ r, g, b }}) {{
    root.style.setProperty(name, `${{Math.round(r)}}, ${{Math.round(g)}}, ${{Math.round(b)}}`);
  }}
  function setHexVar(name, {{ r, g, b }}) {{
    root.style.setProperty(name, rgbToHex(r, g, b));
  }}

  function stopChromaAnim() {{
    if (chromaTimer) {{
      clearInterval(chromaTimer);
      chromaTimer = 0;
    }}
  }}

  function paintChromaHue(hue) {{
    // Continuous HSL hue cycle — seamless wrap at 360°
    const h = ((hue % 360) + 360) % 360;
    const base = hslToRgb(h, 0.78, 0.58);
    const bright = hslToRgb(h + 8, 0.86, 0.7);
    const deep = hslToRgb(h - 6, 0.72, 0.4);
    const shift = hslToRgb(h + 42, 0.76, 0.56);
    const warm = hslToRgb(h + 200, 0.7, 0.54);
    const soft = mixRgb(bright, {{ r: 255, g: 255, b: 255 }}, 0.35);
    const pale = mixRgb(base, {{ r: 255, g: 255, b: 255 }}, 0.72);
    root.style.setProperty('--purple', rgbToHex(base.r, base.g, base.b));
    root.style.setProperty('--purple-bright', rgbToHex(bright.r, bright.g, bright.b));
    root.style.setProperty('--purple-deep', rgbToHex(deep.r, deep.g, deep.b));
    root.style.setProperty('--purple-pale', rgbToHex(pale.r, pale.g, pale.b));
    setRgbVar('--purple-rgb', base);
    setRgbVar('--purple-bright-rgb', bright);
    setRgbVar('--purple-deep-rgb', deep);
    setRgbVar('--accent-shift-rgb', shift);
    setRgbVar('--accent-warm-rgb', warm);
    setRgbVar('--accent-soft-rgb', soft);
  }}

  function applyChromaTick() {{
    if (!activeChroma) return;
    const elapsed = performance.now() - chromaStart;
    const hue = (elapsed / CHROMA_PERIOD_MS) * 360;
    paintChromaHue(hue);
  }}

  function startChromaAnim() {{
    stopChromaAnim();
    chromaStart = performance.now();
    if (chromaReduceMotion) {{
      paintChromaHue(280); // static violet
      return;
    }}
    paintChromaHue(0);
    chromaTimer = setInterval(applyChromaTick, CHROMA_TICK_MS);
  }}

  function applyTheme(hex, {{ persist = true, shiftHex = null, blackMode = null, chromaMode = null }} = {{}}) {{
    const wantChroma = !!chromaMode;
    if (wantChroma) {{
      activeShiftHex = '';
      activeBlackMode = '';
      activeChroma = true;
      body.removeAttribute('data-theme-mix');
      body.removeAttribute('data-theme-black');
      body.setAttribute('data-theme-chroma', '1');
      root.style.setProperty(
        '--theme-dot',
        'linear-gradient(90deg,#ff6b6b,#fbbf24,#34d399,#38bdf8,#a855f7,#f472b6,#ff6b6b)'
      );

      // Soft dark surfaces tinted mid-spectrum
      const mid = {{ r: 168, g: 85, b: 247 }};
      const bg = mixRgb({{ r: 7, g: 6, b: 12 }}, mid, 0.1);
      const bgTop = mixRgb({{ r: 11, g: 9, b: 20 }}, mid, 0.14);
      const bgBottom = mixRgb({{ r: 3, g: 2, b: 8 }}, mid, 0.08);
      const card = mixRgb({{ r: 18, g: 16, b: 26 }}, mid, 0.12);
      const card2 = mixRgb({{ r: 26, g: 22, b: 38 }}, mid, 0.14);
      const line = mixRgb({{ r: 42, g: 36, b: 56 }}, mid, 0.22);
      const lineStrong = mixRgb({{ r: 59, g: 51, b: 82 }}, mid, 0.28);
      const pale = mixRgb(mid, {{ r: 255, g: 255, b: 255 }}, 0.72);
      const muted = mixRgb({{ r: 154, g: 144, b: 179 }}, pale, 0.18);
      const text = mixRgb({{ r: 244, g: 239, b: 255 }}, pale, 0.08);
      setHexVar('--bg', bg);
      setHexVar('--bg-top', bgTop);
      setHexVar('--bg-bottom', bgBottom);
      setHexVar('--card', card);
      setHexVar('--card-2', card2);
      setHexVar('--line', line);
      setHexVar('--line-strong', lineStrong);
      setHexVar('--muted', muted);
      setHexVar('--text', text);

      if (colorInput) colorInput.value = '#a855f7';
      if (hexInput) hexInput.value = '#a855f7';
      swatches.forEach((el) => {{
        el.classList.toggle('active', el.dataset.chroma === '1');
      }});
      startChromaAnim();
      if (persist) {{
        try {{
          localStorage.setItem(THEME_KEY, '#a855f7');
          localStorage.setItem(THEME_CHROMA_KEY, '1');
          localStorage.removeItem(THEME_SHIFT_KEY);
          localStorage.removeItem(THEME_BLACK_KEY);
        }} catch (_) {{}}
      }}
      return true;
    }}

    activeChroma = false;
    stopChromaAnim();
    body.removeAttribute('data-theme-chroma');
    if (persist) {{
      try {{ localStorage.removeItem(THEME_CHROMA_KEY); }} catch (_) {{}}
    }}

    const mode = blackMode && BLACK_PROFILES[blackMode] ? blackMode : '';
    if (mode) {{
      const p = BLACK_PROFILES[mode];
      const base = p.accent;
      const bright = p.bright;
      const deep = p.deep;
      const pale = p.pale;
      const shift = p.shift;
      const warm = p.warm;
      const soft = p.soft;
      const baseHex = rgbToHex(base.r, base.g, base.b);
      activeShiftHex = '';
      activeBlackMode = mode;

      root.style.setProperty('--purple', baseHex);
      root.style.setProperty('--purple-bright', rgbToHex(bright.r, bright.g, bright.b));
      root.style.setProperty('--purple-deep', rgbToHex(deep.r, deep.g, deep.b));
      root.style.setProperty('--purple-pale', rgbToHex(pale.r, pale.g, pale.b));
      setRgbVar('--purple-rgb', base);
      setRgbVar('--purple-bright-rgb', bright);
      setRgbVar('--purple-deep-rgb', deep);
      setRgbVar('--accent-shift-rgb', shift);
      setRgbVar('--accent-warm-rgb', warm);
      setRgbVar('--accent-soft-rgb', soft);
      root.style.setProperty('--theme-dot', baseHex);
      body.removeAttribute('data-theme-mix');
      body.setAttribute('data-theme-black', mode);

      setHexVar('--bg', p.bg);
      setHexVar('--bg-top', p.bgTop);
      setHexVar('--bg-bottom', p.bgBottom);
      setHexVar('--card', p.card);
      setHexVar('--card-2', p.card2);
      setHexVar('--line', p.line);
      setHexVar('--line-strong', p.lineStrong);
      setHexVar('--muted', p.muted);
      setHexVar('--text', p.text);

      if (colorInput) colorInput.value = baseHex;
      if (hexInput) hexInput.value = baseHex;
      swatches.forEach((el) => {{
        el.classList.toggle('active', (el.dataset.black || '') === mode);
      }});
      if (persist) {{
        try {{
          localStorage.setItem(THEME_KEY, baseHex);
          localStorage.setItem(THEME_BLACK_KEY, mode);
          localStorage.removeItem(THEME_SHIFT_KEY);
        }} catch (_) {{}}
      }}
      return true;
    }}

    const parsed = hexToRgb(hex);
    if (!parsed) return false;
    const shiftParsed = shiftHex ? hexToRgb(shiftHex) : null;
    const isMix = !!shiftParsed;
    const inputHex = rgbToHex(parsed.r, parsed.g, parsed.b);
    const storedShiftHex = isMix
      ? rgbToHex(shiftParsed.r, shiftParsed.g, shiftParsed.b)
      : '';
    const base = isMix ? normalizeMixColor(parsed) : normalizeAccent(parsed);
    const shift = isMix
      ? normalizeMixColor(shiftParsed)
      : shiftHue(base, 38, 0.92, 1.05);
    const bright = isMix
      ? mixRgb(base, {{ r: 255, g: 255, b: 255 }}, 0.22)
      : mixRgb(base, {{ r: 255, g: 255, b: 255 }}, 0.28);
    // Mixtures: second swatch color drives deep/warm so chrome matches the gradient icon
    const deep = isMix
      ? mixRgb(shift, {{ r: 0, g: 0, b: 0 }}, 0.08)
      : mixRgb(base, {{ r: 0, g: 0, b: 0 }}, 0.22);
    const pale = mixRgb(base, {{ r: 255, g: 255, b: 255 }}, isMix ? 0.62 : 0.72);
    const warm = isMix
      ? mixRgb(shift, shiftHue(base, -36, 0.85, 1.02), 0.55)
      : shiftHue(base, -48, 0.88, 1.02);
    const soft = isMix
      ? mixRgb(mixRgb(bright, shift, 0.35), {{ r: 255, g: 255, b: 255 }}, 0.28)
      : mixRgb(bright, {{ r: 255, g: 255, b: 255 }}, 0.35);
    const baseHex = rgbToHex(base.r, base.g, base.b);
    const shiftCssHex = rgbToHex(shift.r, shift.g, shift.b);
    activeShiftHex = storedShiftHex;
    activeBlackMode = '';

    root.style.setProperty('--purple', baseHex);
    root.style.setProperty('--purple-bright', rgbToHex(bright.r, bright.g, bright.b));
    root.style.setProperty('--purple-deep', isMix ? shiftCssHex : rgbToHex(deep.r, deep.g, deep.b));
    root.style.setProperty('--purple-pale', rgbToHex(pale.r, pale.g, pale.b));
    setRgbVar('--purple-rgb', base);
    setRgbVar('--purple-bright-rgb', bright);
    setRgbVar('--purple-deep-rgb', isMix ? shift : deep);
    setRgbVar('--accent-shift-rgb', shift);
    setRgbVar('--accent-warm-rgb', warm);
    setRgbVar('--accent-soft-rgb', soft);
    root.style.setProperty(
      '--theme-dot',
      isMix ? 'linear-gradient(135deg, ' + baseHex + ', ' + shiftCssHex + ')' : baseHex
    );
    body.toggleAttribute('data-theme-mix', isMix);
    body.removeAttribute('data-theme-black');

    // Soft surface tint — mixtures pull both colors into the surfaces
    const bg = isMix
      ? mixRgb(mixRgb({{ r: 7, g: 6, b: 12 }}, base, 0.12), shift, 0.1)
      : mixRgb({{ r: 7, g: 6, b: 12 }}, base, 0.1);
    const bgTop = isMix
      ? mixRgb(mixRgb({{ r: 11, g: 9, b: 20 }}, base, 0.16), shift, 0.1)
      : mixRgb({{ r: 11, g: 9, b: 20 }}, base, 0.14);
    const bgBottom = isMix
      ? mixRgb(mixRgb({{ r: 3, g: 2, b: 8 }}, shift, 0.12), base, 0.06)
      : mixRgb({{ r: 3, g: 2, b: 8 }}, base, 0.08);
    const card = isMix
      ? mixRgb(mixRgb({{ r: 18, g: 16, b: 26 }}, base, 0.14), shift, 0.08)
      : mixRgb({{ r: 18, g: 16, b: 26 }}, base, 0.12);
    const card2 = isMix
      ? mixRgb(mixRgb({{ r: 26, g: 22, b: 38 }}, base, 0.14), shift, 0.1)
      : mixRgb({{ r: 26, g: 22, b: 38 }}, base, 0.14);
    const line = isMix
      ? mixRgb(mixRgb({{ r: 42, g: 36, b: 56 }}, base, 0.2), shift, 0.14)
      : mixRgb({{ r: 42, g: 36, b: 56 }}, base, 0.22);
    const lineStrong = isMix
      ? mixRgb(mixRgb({{ r: 59, g: 51, b: 82 }}, base, 0.24), shift, 0.16)
      : mixRgb({{ r: 59, g: 51, b: 82 }}, base, 0.28);
    const muted = mixRgb({{ r: 154, g: 144, b: 179 }}, pale, 0.18);
    const text = mixRgb({{ r: 244, g: 239, b: 255 }}, pale, 0.08);
    setHexVar('--bg', bg);
    setHexVar('--bg-top', bgTop);
    setHexVar('--bg-bottom', bgBottom);
    setHexVar('--card', card);
    setHexVar('--card-2', card2);
    setHexVar('--line', line);
    setHexVar('--line-strong', lineStrong);
    setHexVar('--muted', muted);
    setHexVar('--text', text);

    if (colorInput) colorInput.value = baseHex;
    if (hexInput) hexInput.value = baseHex;
    swatches.forEach((el) => {{
      const c = (el.dataset.color || '').toLowerCase();
      const s = (el.dataset.shift || '').toLowerCase();
      const match = isMix
        ? c === inputHex.toLowerCase() && s === storedShiftHex.toLowerCase()
        : c === inputHex.toLowerCase() && !el.dataset.shift && !el.dataset.black && !el.dataset.chroma;
      el.classList.toggle('active', match);
    }});
    if (persist) {{
      try {{
        localStorage.setItem(THEME_KEY, inputHex);
        if (isMix) localStorage.setItem(THEME_SHIFT_KEY, storedShiftHex);
        else localStorage.removeItem(THEME_SHIFT_KEY);
        localStorage.removeItem(THEME_BLACK_KEY);
      }} catch (_) {{}}
    }}
    return true;
  }}

  function applyVariant(name, {{ persist = true }} = {{}}) {{
    const v = VARIANTS.includes(name) ? name : DEFAULT_VARIANT;
    body.setAttribute('data-bg-variant', v);
    variantBtns.forEach((el) => {{
      el.classList.toggle('active', el.dataset.variant === v);
    }});
    if (persist) {{
      try {{ localStorage.setItem(VARIANT_KEY, v); }} catch (_) {{}}
    }}
    return v;
  }}

  function applyTexture(name, {{ persist = true }} = {{}}) {{
    const t = TEXTURES.includes(name) ? name : DEFAULT_TEXTURE;
    if (t === 'none') body.removeAttribute('data-bg-texture');
    else body.setAttribute('data-bg-texture', t);
    textureBtns.forEach((el) => {{
      el.classList.toggle('active', (el.dataset.texture || 'none') === t);
    }});
    if (persist) {{
      try {{ localStorage.setItem(TEXTURE_KEY, t); }} catch (_) {{}}
    }}
    return t;
  }}

  function applyEffect(name, {{ persist = true }} = {{}}) {{
    const e = EFFECTS.includes(name) ? name : DEFAULT_EFFECT;
    if (e === 'none') body.removeAttribute('data-bg-effect');
    else body.setAttribute('data-bg-effect', e);
    effectBtns.forEach((el) => {{
      el.classList.toggle('active', (el.dataset.effect || 'none') === e);
    }});
    if (persist) {{
      try {{ localStorage.setItem(EFFECT_KEY, e); }} catch (_) {{}}
    }}
    return e;
  }}

  function applyFxOff(on, {{ persist = true }} = {{}}) {{
    const off = !!on;
    if (off) body.setAttribute('data-fx-off', '1');
    else body.removeAttribute('data-fx-off');
    if (fxOffToggle) fxOffToggle.checked = off;
    if (persist) {{
      try {{ localStorage.setItem(FX_OFF_KEY, off ? '1' : '0'); }} catch (_) {{}}
    }}
    return off;
  }}

  function openPanel() {{
    panel.hidden = false;
    btn.setAttribute('aria-expanded', 'true');
  }}
  function closePanel() {{
    panel.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    if (adv) {{
      adv.hidden = true;
      if (advBtn) advBtn.setAttribute('aria-expanded', 'false');
    }}
  }}
  function togglePanel() {{
    if (panel.hidden) openPanel();
    else closePanel();
  }}

  btn.addEventListener('click', (e) => {{
    e.stopPropagation();
    togglePanel();
  }});
  panel.addEventListener('click', (e) => e.stopPropagation());
  document.addEventListener('click', () => {{
    if (!panel.hidden) closePanel();
  }});

  swatches.forEach((el) => {{
    el.addEventListener('click', () => {{
      applyTheme(el.dataset.color, {{
        shiftHex: el.dataset.shift || null,
        blackMode: el.dataset.black || null,
        chromaMode: el.dataset.chroma === '1',
      }});
    }});
  }});
  variantBtns.forEach((el) => {{
    el.addEventListener('click', () => applyVariant(el.dataset.variant));
  }});
  textureBtns.forEach((el) => {{
    el.addEventListener('click', () => applyTexture(el.dataset.texture || 'none'));
  }});
  effectBtns.forEach((el) => {{
    el.addEventListener('click', () => applyEffect(el.dataset.effect || 'none'));
  }});
  if (fxOffToggle) {{
    fxOffToggle.addEventListener('change', () => applyFxOff(!!fxOffToggle.checked));
  }}

  if (advBtn && adv) {{
    advBtn.addEventListener('click', () => {{
      const open = adv.hidden;
      adv.hidden = !open;
      advBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
      if (open && colorInput) colorInput.focus();
    }});
  }}
  if (colorInput) {{
    colorInput.addEventListener('input', () => applyTheme(colorInput.value));
  }}
  if (hexInput) {{
    const commitHex = () => {{
      let v = hexInput.value.trim();
      if (!v.startsWith('#')) v = '#' + v;
      if (!applyTheme(v)) hexInput.value = colorInput ? colorInput.value : DEFAULT_THEME;
    }};
    hexInput.addEventListener('change', commitHex);
    hexInput.addEventListener('keydown', (e) => {{
      if (e.key === 'Enter') {{
        e.preventDefault();
        commitHex();
      }}
    }});
  }}

  window.__closeThemePanel = closePanel;

  let saved = DEFAULT_THEME;
  let savedShift = null;
  let savedBlack = null;
  let savedChroma = false;
  let savedVariant = DEFAULT_VARIANT;
  let savedTexture = DEFAULT_TEXTURE;
  let savedEffect = DEFAULT_EFFECT;
  let savedFxOff = false;
  try {{
    const raw = localStorage.getItem(THEME_KEY);
    if (raw && hexToRgb(raw)) saved = raw;
    const sr = localStorage.getItem(THEME_SHIFT_KEY);
    if (sr && hexToRgb(sr)) savedShift = sr;
    const br = localStorage.getItem(THEME_BLACK_KEY);
    if (br && BLACK_PROFILES[br]) savedBlack = br;
    const cr = localStorage.getItem(THEME_CHROMA_KEY);
    if (cr === '1') savedChroma = true;
    const vr = localStorage.getItem(VARIANT_KEY);
    if (vr && VARIANTS.includes(vr)) savedVariant = vr;
    const er = localStorage.getItem(EFFECT_KEY);
    if (er && EFFECTS.includes(er)) savedEffect = er;
    const tr = localStorage.getItem(TEXTURE_KEY);
    if (tr && LEGACY_EFFECT_TEXTURES.includes(tr)) {{
      // Migrate stars/snow/rain that were previously stored as texture
      if (!er || !EFFECTS.includes(er) || er === 'none') savedEffect = tr;
      savedTexture = DEFAULT_TEXTURE;
      try {{
        localStorage.setItem(EFFECT_KEY, savedEffect);
        localStorage.setItem(TEXTURE_KEY, DEFAULT_TEXTURE);
      }} catch (_) {{}}
    }} else if (tr && TEXTURES.includes(tr)) {{
      savedTexture = tr;
    }}
    const fx = localStorage.getItem(FX_OFF_KEY);
    if (fx === '1') savedFxOff = true;
  }} catch (_) {{}}
  applyTheme(saved, {{
    persist: false,
    shiftHex: savedShift,
    blackMode: savedBlack,
    chromaMode: savedChroma,
  }});
  applyVariant(savedVariant, {{ persist: false }});
  applyTexture(savedTexture, {{ persist: false }});
  applyEffect(savedEffect, {{ persist: false }});
  applyFxOff(savedFxOff, {{ persist: false }});
}})();

(function initAmbient() {{
  const blobs = Array.from(document.querySelectorAll('.bg-blob'));
  const glow = document.getElementById('bgCursorGlow');
  const trailRoot = document.getElementById('cursorTrail');
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function fxOff() {{
    return document.body.getAttribute('data-fx-off') === '1';
  }}
  function rand(min, max) {{
    return min + Math.random() * (max - min);
  }}
  function placeBlob(el) {{
    const size = rand(28, 58);
    el.style.width = size + 'vw';
    el.style.height = size + 'vw';
    el._baseLeft = rand(-18, 78);
    el._baseTop = rand(-16, 72);
    el.style.left = el._baseLeft + 'vw';
    el.style.top = el._baseTop + 'vh';
    el.style.setProperty('--peak', String(rand(0.45, 0.95)));
    const duration = rand(5.5, 12);
    const delay = rand(-10, 2);
    el.style.animationDuration = duration + 's';
    el.style.animationDelay = delay + 's';
  }}
  function reshuffle() {{
    if (fxOff()) return;
    blobs.forEach(placeBlob);
  }}
  reshuffle();
  if (!reduceMotion) setInterval(reshuffle, 11000);

  if (reduceMotion || !glow || !trailRoot) return;

  const DOTS = 14;
  const dots = [];
  for (let i = 0; i < DOTS; i++) {{
    const d = document.createElement('div');
    d.className = 'trail-dot';
    trailRoot.appendChild(d);
    dots.push({{ el: d, x: -100, y: -100, life: 0 }});
  }}

  let mx = window.innerWidth / 2;
  let my = window.innerHeight / 2;
  let smx = mx;
  let smy = my;
  let trailI = 0;
  let lastTrail = 0;
  let hovering = false;

  window.addEventListener('mousemove', (e) => {{
    if (fxOff()) return;
    mx = e.clientX;
    my = e.clientY;
    hovering = true;
    glow.classList.add('on');
    const now = performance.now();
    if (now - lastTrail > 28) {{
      lastTrail = now;
      const dot = dots[trailI % dots.length];
      trailI += 1;
      dot.x = mx;
      dot.y = my;
      dot.life = 1;
      dot.el.style.transform = 'translate3d(' + mx + 'px,' + my + 'px,0) scale(1)';
      dot.el.style.opacity = '0.45';
    }}
  }}, {{ passive: true }});

  window.addEventListener('mouseleave', () => {{
    hovering = false;
    glow.classList.remove('on');
  }});

  function tick() {{
    if (fxOff()) {{
      glow.classList.remove('on');
      requestAnimationFrame(tick);
      return;
    }}
    smx += (mx - smx) * 0.12;
    smy += (my - smy) * 0.12;
    glow.style.transform = 'translate3d(' + smx + 'px,' + smy + 'px,0)';

    // Soft pull of ambient blobs toward the cursor
    const vw = Math.max(window.innerWidth, 1);
    const vh = Math.max(window.innerHeight, 1);
    const cx = (smx / vw) * 100;
    const cy = (smy / vh) * 100;
    for (const el of blobs) {{
      const baseL = el._baseLeft != null ? el._baseLeft : 0;
      const baseT = el._baseTop != null ? el._baseTop : 0;
      const pull = hovering ? 0.07 : 0.02;
      const left = baseL + (cx - baseL) * pull;
      const top = baseT + (cy - baseT) * pull;
      el.style.left = left + 'vw';
      el.style.top = top + 'vh';
    }}

    for (const dot of dots) {{
      if (dot.life <= 0) {{
        dot.el.style.opacity = '0';
        continue;
      }}
      dot.life -= 0.035;
      const s = 0.45 + dot.life * 0.55;
      dot.el.style.opacity = String(Math.max(0, dot.life * 0.4));
      dot.el.style.transform = 'translate3d(' + dot.x + 'px,' + dot.y + 'px,0) scale(' + s + ')';
    }}
    requestAnimationFrame(tick);
  }}
  requestAnimationFrame(tick);
}})();

(function initWeather() {{
  const root = document.getElementById('weatherFx');
  if (!root) return;
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduceMotion) return;

  function rand(min, max) {{
    return min + Math.random() * (max - min);
  }}
  function effect() {{
    if (document.body.getAttribute('data-fx-off') === '1') return '';
    return document.body.getAttribute('data-bg-effect') || '';
  }}

  const DROP_COUNT = 56;
  const SPLASH_COUNT = 28;
  const FLAKE_COUNT = 48;
  const drops = [];
  const splashes = [];
  const flakes = [];
  let splashI = 0;

  for (let i = 0; i < DROP_COUNT; i++) {{
    const el = document.createElement('div');
    el.className = 'rain-drop';
    root.appendChild(el);
    drops.push({{
      el,
      x: 0,
      y: -100,
      vy: 0,
      len: 14,
      active: false,
    }});
  }}
  for (let i = 0; i < SPLASH_COUNT; i++) {{
    const el = document.createElement('div');
    el.className = 'rain-splash';
    root.appendChild(el);
    splashes.push(el);
  }}
  for (let i = 0; i < FLAKE_COUNT; i++) {{
    const el = document.createElement('div');
    el.className = 'snow-flake';
    root.appendChild(el);
    flakes.push({{
      el,
      x: 0,
      y: -40,
      vy: 0,
      vx: 0,
      size: 4,
      phase: 0,
      active: false,
    }});
  }}

  function resetDrop(d, fromTop) {{
    const w = window.innerWidth;
    d.x = rand(-20, w + 20);
    d.y = fromTop ? rand(-120, -10) : rand(-window.innerHeight, -10);
    d.vy = rand(780, 1280);
    d.len = rand(12, 22);
    d.active = true;
    d.el.style.setProperty('--len', Math.round(d.len) + 'px');
    d.el.style.opacity = String(rand(0.35, 0.75));
  }}

  function resetFlake(f, fromTop) {{
    const w = window.innerWidth;
    f.x = rand(0, w);
    f.y = fromTop ? rand(-80, -8) : rand(-window.innerHeight, -8);
    f.vy = rand(28, 95);
    f.vx = rand(-18, 18);
    f.size = rand(2.5, 6.5);
    f.phase = rand(0, Math.PI * 2);
    f.active = true;
    f.el.style.setProperty('--sz', f.size.toFixed(1) + 'px');
    f.el.style.opacity = String(rand(0.35, 0.9));
  }}

  function spawnSplash(x, y, size) {{
    const el = splashes[splashI % splashes.length];
    splashI += 1;
    el.classList.remove('go');
    el.style.left = x + 'px';
    el.style.top = y + 'px';
    el.style.setProperty('--s', Math.round(size) + 'px');
    void el.offsetWidth;
    el.classList.add('go');
  }}

  // Seed particles
  drops.forEach((d) => resetDrop(d, false));
  flakes.forEach((f) => resetFlake(f, false));

  let pointerX = 0.5;
  let windSmoothed = 0;
  window.addEventListener('pointermove', (e) => {{
    const ww = Math.max(window.innerWidth, 1);
    pointerX = e.clientX / ww;
  }}, {{ passive: true }});

  let last = performance.now();
  function frame(now) {{
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    const mode = effect();
    const h = window.innerHeight;
    const w = window.innerWidth;
    const ground = h - 2;

    if (mode === 'rain') {{
      const windTarget = (pointerX - 0.5) * 2; // -1 .. 1 toward cursor X
      windSmoothed += (windTarget - windSmoothed) * Math.min(1, dt * 4);
      const drift = 55 + windSmoothed * 260;
      const lean = windSmoothed * 14;
      document.documentElement.style.setProperty('--rain-wind', windSmoothed.toFixed(2));
      for (const d of drops) {{
        if (!d.active) resetDrop(d, true);
        d.y += d.vy * dt;
        d.x += drift * dt;
        if (d.y + d.len >= ground) {{
          spawnSplash(d.x, ground - 1, rand(14, 34));
          resetDrop(d, true);
        }} else if (d.x > w + 40) {{
          d.x = -20;
        }} else if (d.x < -40) {{
          d.x = w + 20;
        }}
        d.el.style.transform =
          'translate3d(' + d.x + 'px,' + d.y + 'px,0) skewX(' + (-lean).toFixed(2) + 'deg) rotate(' + (lean * 0.4).toFixed(2) + 'deg)';
      }}
      for (const f of flakes) {{
        f.el.style.opacity = '0';
        f.active = false;
      }}
    }} else if (mode === 'snow') {{
      if (windSmoothed !== 0) {{
        windSmoothed = 0;
        document.documentElement.style.setProperty('--rain-wind', '0');
      }}
      for (const f of flakes) {{
        if (!f.active) resetFlake(f, true);
        f.phase += dt * 1.4;
        f.y += f.vy * dt;
        f.x += (f.vx + Math.sin(f.phase) * 22) * dt;
        if (f.y > h + 20) resetFlake(f, true);
        if (f.x < -20) f.x = w + 10;
        if (f.x > w + 20) f.x = -10;
        f.el.style.opacity = String(Math.min(0.95, 0.4 + f.size / 10));
        f.el.style.transform = 'translate3d(' + f.x + 'px,' + f.y + 'px,0)';
      }}
      for (const d of drops) {{
        d.el.style.opacity = '0';
        d.active = false;
      }}
    }} else {{
      if (windSmoothed !== 0) {{
        windSmoothed = 0;
        document.documentElement.style.setProperty('--rain-wind', '0');
      }}
      for (const d of drops) {{
        d.el.style.opacity = '0';
        d.active = false;
      }}
      for (const f of flakes) {{
        f.el.style.opacity = '0';
        f.active = false;
      }}
    }}

    requestAnimationFrame(frame);
  }}
  requestAnimationFrame(frame);
}})();

const SLOTS = 4; // MM2 trades allow 4 unique items per side
const INV_KEY = 'lunix_mm2_inv_v1';
const TARGET_KEY = 'lunix_mm2_targets_v1';
const DUMP_KEY = 'lunix_mm2_tradeoff_v1';
const SET_PROTECT_KEY = 'lunix_mm2_avoid_set_breaks_v1';
const AUTO_HOT_KEY = 'lunix_mm2_auto_target_hot_v1';
const QUICK_SEARCH_KEY = 'lunix_mm2_quick_search_v1';
const TRADE_HIST_KEY = 'lunix_mm2_trades_v1';
const TRADE_DISMISS_KEY = 'lunix_mm2_trade_dismiss_v1';
const TRADE_HIST_MAX = 40;
const TRADE_INFER_MAX_UNIQUE_SIDE = 8;
const TRADE_INFER_MAX_UNITS_SIDE = 40;
const TRADE_INFER_DUP_MS = 12 * 60 * 1000;
const byId = Object.fromEntries(CATALOG.map((item) => [item.id, item]));
const state = {{
  your: Array(SLOTS).fill(null),
  their: Array(SLOTS).fill(null),
  inv: [], // {{ id, qty }}
  targets: [], // {{ id, qty }}
  dumpList: [], // {{ id, qty }} — user-chosen items to trade off
  invHistory: [], // {{ t, v, items?: [{{ id, qty }}] }}
  tradeHistory: [], // {{ t, your, their, yourTotal, theirTotal, net, source?, key? }}
  tradeDismissed: [], // inferred keys the user removed
  lowerCycle: null, // {{ theirKey, list, index }}
  higherCycle: null,
  pickingFor: null, // 'your' | 'their' | 'inv' | 'targets' | 'dump'
  avoidSetBreaks: true,
  autoTargetHot: false,
  quickSearch: false,
}};

const HISTORY_MAX = 50;
let histStack = [];
let histPos = -1;
let histQuiet = false;

const yourGrid = document.getElementById('yourGrid');
const theirGrid = document.getElementById('theirGrid');
const yourValueEl = document.getElementById('yourValue');
const theirValueEl = document.getElementById('theirValue');
const meterFill = document.getElementById('meterFill');
const verdictEl = document.getElementById('verdict');
const modal = document.getElementById('modal');
const modalBody = document.getElementById('modalBody');
const modalList = document.getElementById('modalList');
const pickerMine = document.getElementById('pickerMine');
const pickerMineList = document.getElementById('pickerMineList');
const search = document.getElementById('search');
const rarityFilter = document.getElementById('rarityFilter');
const pickerTitle = document.getElementById('pickerTitle');
const quickSearchWrap = document.getElementById('quickSearchWrap');
const quickSearchInput = document.getElementById('quickSearch');
const quickRarity = document.getElementById('quickRarity');
const quickResults = document.getElementById('quickResults');
const quickSearchToggle = document.getElementById('quickSearchToggle');
const detail = document.getElementById('detail');
const invList = document.getElementById('invList');
const invDumpTips = document.getElementById('invDumpTips');
const invTotalEl = document.getElementById('invTotal');
const invDeltaEl = document.getElementById('invDelta');
const invSinceEl = document.getElementById('invSince');
const invStatusEl = document.getElementById('invStatus');
const invCountEl = document.getElementById('invCount');
const invSaveBtn = document.getElementById('invSaveBtn');
const graphModal = document.getElementById('graphModal');
const graphChart = document.getElementById('graphChart');
const invHistList = document.getElementById('invHistList');
const suggestList = document.getElementById('suggestList');
const targetList = document.getElementById('targetList');
const dumpListEl = document.getElementById('dumpList');
const genOfferBtn = document.getElementById('genOfferBtn');
const genReceiveBtn = document.getElementById('genReceiveBtn');
const lowerOfferBtn = document.getElementById('lowerOfferBtn');
const higherOfferBtn = document.getElementById('higherOfferBtn');
const completeOfferBtn = document.getElementById('completeOfferBtn');
const undoBtn = document.getElementById('undoBtn');
const redoBtn = document.getElementById('redoBtn');
const tradeHistBtn = document.getElementById('tradeHistBtn');
const tradeHistModal = document.getElementById('tradeHistModal');
const tradeHistList = document.getElementById('tradeHistList');
const tradeHistDetail = document.getElementById('tradeHistDetail');
const tradeHistFilter = document.getElementById('tradeHistFilter');
const tradeHistCountEl = document.getElementById('tradeHistCount');
const tradeHistBadge = document.getElementById('tradeHistBadge');
let tradeHistSelectedIdx = -1;
let tradeHistFilterText = '';
const prevTradeModal = document.getElementById('prevTradeModal');
const prevTradeTitle = document.getElementById('prevTradeTitle');
const prevTradeMeta = document.getElementById('prevTradeMeta');
const prevTradeCompare = document.getElementById('prevTradeCompare');
const prevTradeYourTotals = document.getElementById('prevTradeYourTotals');
const prevTradeTheirTotals = document.getElementById('prevTradeTheirTotals');
const prevTradeYourGrid = document.getElementById('prevTradeYourGrid');
const prevTradeTheirGrid = document.getElementById('prevTradeTheirGrid');

function cloneEntries(arr) {{
  return arr.map((e) => (e ? Object.assign({{}}, e) : null));
}}

function cloneInvHistory(hist) {{
  return hist.map((e) => ({{
    t: e.t,
    v: e.v,
    items: Array.isArray(e.items)
      ? e.items.map((i) => ({{ id: i.id, qty: i.qty }}))
      : undefined,
  }}));
}}

function takeSnapshot() {{
  return {{
    your: cloneEntries(state.your),
    their: cloneEntries(state.their),
    inv: state.inv.map((e) => Object.assign({{}}, e)),
    targets: state.targets.map((e) => Object.assign({{}}, e)),
    dumpList: state.dumpList.map((e) => Object.assign({{}}, e)),
    invHistory: cloneInvHistory(state.invHistory),
  }};
}}

function snapKey(snap) {{
  const sideKey = (arr) => arr.map((e) => (e ? e.id + ':' + e.qty : '-')).join(',');
  const listKey = (arr) => arr.map((e) => e.id + ':' + e.qty).join(',');
  const histKey = Array.isArray(snap.invHistory)
    ? String(snap.invHistory.length) + ':' + (snap.invHistory.length ? snap.invHistory[snap.invHistory.length - 1].t : 0)
    : '0';
  return (
    sideKey(snap.your) + '|' +
    sideKey(snap.their) + '|' +
    listKey(snap.inv) + '|' +
    listKey(snap.targets) + '|' +
    listKey(snap.dumpList) + '|' +
    histKey
  );
}}

function updateUndoRedoBtns() {{
  undoBtn.disabled = histPos <= 0;
  redoBtn.disabled = histPos < 0 || histPos >= histStack.length - 1;
}}

function commitHistory() {{
  if (histQuiet) return;
  const snap = takeSnapshot();
  const key = snapKey(snap);
  if (histPos >= 0 && histStack[histPos] && histStack[histPos]._key === key) {{
    updateUndoRedoBtns();
    return;
  }}
  snap._key = key;
  histStack = histStack.slice(0, histPos + 1);
  histStack.push(snap);
  if (histStack.length > HISTORY_MAX) histStack.shift();
  histPos = histStack.length - 1;
  updateUndoRedoBtns();
}}

function applySnapshot(snap) {{
  histQuiet = true;
  state.your = cloneEntries(snap.your);
  state.their = cloneEntries(snap.their);
  state.inv = snap.inv.map((e) => Object.assign({{}}, e));
  state.targets = snap.targets.map((e) => Object.assign({{}}, e));
  state.dumpList = Array.isArray(snap.dumpList)
    ? snap.dumpList.map((e) => Object.assign({{}}, e))
    : [];
  state.invHistory = cloneInvHistory(snap.invHistory);
  state.lowerCycle = null;
  state.higherCycle = null;
  persistInv();
  persistTargets();
  persistDumpList();
  render();
  histQuiet = false;
  updateUndoRedoBtns();
}}

function undoAction() {{
  if (histPos <= 0) return;
  histPos -= 1;
  applySnapshot(histStack[histPos]);
}}

function redoAction() {{
  if (histPos >= histStack.length - 1) return;
  histPos += 1;
  applySnapshot(histStack[histPos]);
}}

function fmt(n) {{
  const rounded = Math.round(n);
  return rounded.toLocaleString('en-US');
}}

function dash(v) {{
  return v == null || v === '' ? '—' : String(v);
}}

function setInvStatus(text, dirty) {{
  if (!invStatusEl) return;
  if (!text) {{
    invStatusEl.hidden = true;
    invStatusEl.textContent = '';
    invStatusEl.className = 'inv-status';
    return;
  }}
  invStatusEl.hidden = false;
  invStatusEl.className = 'inv-status' + (dirty ? ' dirty' : '');
  invStatusEl.textContent = text;
}}

function openDetail(item) {{
  const dName = document.getElementById('dName');
  dName.className = 'iname';
  dName.innerHTML = itemNameHtml(item, {{
    className: 'iname-label',
  }});
  document.getElementById('dValue').textContent = fmt(item.value);
  document.getElementById('dStability').textContent = dash(item.stability);
  document.getElementById('dDemand').textContent = dash(item.demand);
  document.getElementById('dRarityScore').textContent = dash(item.rarityScore);
  document.getElementById('dOrigin').textContent = dash(item.origin);
  const changeEl = document.getElementById('dChange');
  const change = item.change;
  changeEl.textContent = dash(change);
  changeEl.className = 'change';
  if (typeof change === 'string' && /\\(-|−|-[0-9]/.test(change)) changeEl.classList.add('down');
  const aliases = (item.aliases && item.aliases.length) ? item.aliases.join(', ') : '—';
  document.getElementById('dAliases').textContent = aliases;
  renderDetailHistory(item);
  const art = document.getElementById('dArt');
  if (item.image) {{
    art.src = item.image;
    art.style.display = 'block';
    art.className = 'detail-art';
  }} else {{
    art.removeAttribute('src');
    art.className = 'detail-art missing';
    art.alt = 'No image';
  }}
  detail.classList.add('open');
}}

function chartPointLabel(point, index, total) {{
  if (point && typeof point.label === 'string' && point.label) return point.label;
  if (point && Number.isFinite(point.t)) return formatChartDate(point.t);
  if (total <= 1) return 'Point 1';
  return 'Point ' + (index + 1) + ' of ' + total;
}}

/** Drop history points on a wildly different value scale (bad scrape contamination). */
const HISTORY_SCALE_FACTOR = 25;
function sanitizeValueHistory(hist, currentValue, changePct) {{
  if (!Array.isArray(hist)) return [];
  const refInt = Number.isFinite(currentValue) && Math.abs(currentValue - Math.round(currentValue)) < 1e-9;
  let points = hist.filter((p) => {{
    if (!p || !Number.isFinite(p.v) || p.v < 0) return false;
    // SV ticks are integers; reject reverse-% bootstrap fractions
    if (refInt && Math.abs(p.v - Math.round(p.v)) > 1e-6) return false;
    // Unlabeled points that exactly match value/(1+pct) are synthetic priors
    const unlabeled = !(p && typeof p.label === 'string' && p.label);
    if (unlabeled && Number.isFinite(currentValue) && currentValue > 0 && Number.isFinite(changePct) && Math.abs(changePct) > 1e-9) {{
      const expected = currentValue / (1 + changePct / 100);
      if (Math.abs(p.v - expected) <= Math.max(1e-6, Math.abs(expected) * 1e-9)) return false;
    }}
    return true;
  }});
  if (!points.length) return [];
  let ref = (Number.isFinite(currentValue) && currentValue > 0) ? currentValue : null;
  if (ref == null) {{
    const pos = points.map((p) => p.v).filter((v) => v > 0).sort((a, b) => a - b);
    if (pos.length) ref = pos[Math.floor(pos.length / 2)];
  }}
  if (ref > 0) {{
    const lo = ref / HISTORY_SCALE_FACTOR;
    const hi = ref * HISTORY_SCALE_FACTOR;
    points = points.filter((p) => {{
      if (p.v <= 0 && ref >= 1) return false;
      return p.v >= lo && p.v <= hi;
    }});
  }}
  // Coalesce consecutive equal values (repeated scrape tips)
  const out = [];
  for (const p of points) {{
    if (out.length && Math.abs(out[out.length - 1].v - p.v) < 1e-6) continue;
    out.push(p);
  }}
  return out;
}}

function itemValueHistory(item) {{
  if (!item) return [];
  return sanitizeValueHistory(item.history, item.value, itemChangePct(item));
}}

function mountInteractiveChart(container, hist, opts) {{
  opts = opts || {{}};
  const spark = !!opts.spark;
  const w = opts.w || (spark ? 320 : 640);
  const h = opts.h || (spark ? 110 : 220);
  const pad = opts.pad || (spark
    ? {{ t: 14, r: 12, b: 16, l: 12 }}
    : {{ t: 18, r: 16, b: 28, l: 54 }});
  const showAxes = opts.showAxes !== false && !spark;
  const showArea = opts.showArea !== false && !spark;
  const svgClass = spark ? 'hspark' : 'graph-svg';

  const vals = hist.map((p) => p.v);
  let min = Math.min.apply(null, vals);
  let max = Math.max.apply(null, vals);
  if (Math.abs(max - min) < 1) {{ min -= 1; max += 1; }}
  const span = max - min || 1;
  const iw = w - pad.l - pad.r;
  const ih = h - pad.t - pad.b;

  // Prefer real time spacing when timestamps exist; fall back to equal index gaps.
  const timed = hist.every((p) => Number.isFinite(p.t));
  let tMin = 0, tSpan = 1;
  if (timed) {{
    const ts = hist.map((p) => p.t);
    tMin = Math.min.apply(null, ts);
    const tMax = Math.max.apply(null, ts);
    tSpan = Math.max(tMax - tMin, 1);
  }}

  const pts = hist.map((p, i) => {{
    let x;
    if (hist.length === 1) x = pad.l + iw / 2;
    else if (timed) x = pad.l + ((p.t - tMin) / tSpan) * iw;
    else x = pad.l + (i / (hist.length - 1)) * iw;
    const y = pad.t + (1 - (p.v - min) / span) * ih;
    return {{ x, y, p, i }};
  }});
  const line = pts.map((p, i) => (i ? 'L' : 'M') + p.x.toFixed(1) + ',' + p.y.toFixed(1)).join(' ');
  const area = line +
    ' L' + pts[pts.length - 1].x.toFixed(1) + ',' + (pad.t + ih) +
    ' L' + pts[0].x.toFixed(1) + ',' + (pad.t + ih) + ' Z';
  const up = vals[vals.length - 1] >= vals[0];
  const stroke = up ? '#34d399' : (spark ? '#f87171' : '#f04444');
  const fill = up ? 'rgba(52,211,153,0.15)' : 'rgba(240,68,68,0.12)';
  const sw = spark ? '2.2' : '2.5';

  // Color each segment: drops red, solid raises green,
  // yellow only for a weak bounce after a drop (not a real climb).
  function segmentStroke(prevV, nextV, prevIndex) {{
    const d = nextV - prevV;
    const eps = Math.max(span * 0.01, Math.abs(prevV) * 0.003, 0.05);
    if (d < -eps) return '#f87171';
    if (d > eps) {{
      // Weak recovery: previous segment dropped, and this only partially clawed back
      if (prevIndex >= 1) {{
        const priorD = hist[prevIndex].v - hist[prevIndex - 1].v;
        if (priorD < -eps) {{
          const recovered = d / Math.abs(priorD);
          const pct = Math.abs(prevV) > 0.01 ? (d / Math.abs(prevV)) * 100 : 100;
          if (recovered < 0.9 && pct < 5) return '#fbbf24';
        }}
      }}
      return '#34d399';
    }}
    return '#94a3b8';
  }}

  let segPaths = '';
  const segColors = [];
  for (let i = 1; i < pts.length; i++) {{
    const col = segmentStroke(hist[i - 1].v, hist[i].v, i - 1);
    segColors.push(col);
    segPaths +=
      '<path d="M' + pts[i - 1].x.toFixed(1) + ',' + pts[i - 1].y.toFixed(1) +
      ' L' + pts[i].x.toFixed(1) + ',' + pts[i].y.toFixed(1) +
      '" fill="none" stroke="' + col + '" stroke-width="' + sw +
      '" stroke-linecap="round" stroke-linejoin="round" />';
  }}
  if (!segPaths) {{
    segPaths =
      '<path d="' + line + '" fill="none" stroke="' + stroke + '" stroke-width="' + sw +
      '" stroke-linecap="round" stroke-linejoin="round" />';
  }}

  let axes = '';
  if (showAxes) {{
    axes = [min, min + span / 2, max].map((v) => {{
      const y = pad.t + (1 - (v - min) / span) * ih;
      return '<text x="' + (pad.l - 8) + '" y="' + (y + 4) + '" text-anchor="end" fill="#9a90b3" font-size="11" font-family="Outfit,sans-serif">' +
        fmt(v) + '</text>' +
        '<line x1="' + pad.l + '" y1="' + y + '" x2="' + (w - pad.r) + '" y2="' + y + '" stroke="#2a2438" stroke-width="1" />';
    }}).join('');
    const hasDates = Number.isFinite(hist[0].t) && Number.isFinite(hist[hist.length - 1].t);
    if (hasDates) {{
      axes +=
        '<text x="' + pad.l + '" y="' + (h - 8) + '" fill="#9a90b3" font-size="11" font-family="Outfit,sans-serif">' +
          (hist[0].label || formatChartDate(hist[0].t, true)) + '</text>' +
        '<text x="' + (w - pad.r) + '" y="' + (h - 8) + '" text-anchor="end" fill="#9a90b3" font-size="11" font-family="Outfit,sans-serif">' +
          (hist[hist.length - 1].label || formatChartDate(hist[hist.length - 1].t, true)) + '</text>';
    }}
  }}

  const wrap = document.createElement('div');
  wrap.className = 'chart-wrap' + (spark ? ' spark' : '');
  wrap.innerHTML =
    '<svg class="' + svgClass + '" viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" aria-hidden="true">' +
      axes +
      (showArea ? '<path d="' + area + '" fill="' + fill + '" />' : '') +
      segPaths +
    '</svg>' +
    '<div class="chart-cross" aria-hidden="true"><div class="vline"></div><div class="hline"></div></div>' +
    '<div class="chart-tooltip" role="tooltip"></div>';

  const cross = wrap.querySelector('.chart-cross');
  const vline = cross.querySelector('.vline');
  const hline = cross.querySelector('.hline');
  const tip = wrap.querySelector('.chart-tooltip');
  const dots = [];
  const hits = [];

  pts.forEach((pt, idx) => {{
    const leftPct = (pt.x / w) * 100;
    const topPct = (pt.y / h) * 100;
    const dot = document.createElement('div');
    dot.className = 'chart-dot';
    dot.style.left = leftPct + '%';
    dot.style.top = topPct + '%';
    const dotCol = idx === 0
      ? (segColors[0] || stroke)
      : (segColors[idx - 1] || stroke);
    dot.style.setProperty('--dot', dotCol);
    wrap.appendChild(dot);
    dots.push(dot);

    const hit = document.createElement('button');
    hit.type = 'button';
    hit.className = 'chart-hit';
    hit.style.left = leftPct + '%';
    hit.style.top = topPct + '%';
    hit.setAttribute('aria-label', chartPointLabel(pt.p, pt.i, hist.length) + ', value ' + fmt(pt.p.v));
    wrap.appendChild(hit);
    hits.push(hit);
  }});

  function hideTip() {{
    tip.classList.remove('on');
    cross.classList.remove('on');
    dots.forEach((d) => d.classList.remove('active'));
  }}

  function showTip(idx) {{
    const pt = pts[idx];
    if (!pt) return;
    dots.forEach((d, i) => d.classList.toggle('active', i === idx));
    const leftPct = (pt.x / w) * 100;
    const topPct = (pt.y / h) * 100;
    vline.style.left = leftPct + '%';
    hline.style.top = topPct + '%';
    cross.classList.add('on');

    const prev = idx > 0 ? hist[idx - 1].v : null;
    let deltaHtml = '';
    if (prev != null && Number.isFinite(prev)) {{
      const d = pt.p.v - prev;
      const cls = d > 0 ? 'up' : (d < 0 ? 'down' : '');
      deltaHtml = '<div class="tt-delta ' + cls + '">' + signedFmt(d) + ' vs prev</div>';
    }}
    tip.innerHTML =
      '<div class="tt-when">' + chartPointLabel(pt.p, pt.i, hist.length) + '</div>' +
      '<div class="tt-val">' + fmt(pt.p.v) + '</div>' +
      deltaHtml;
    tip.classList.add('on');

    // Pin tooltip inside the chart frame (overflow is clipped)
    const place = () => {{
      const wrapW = wrap.clientWidth;
      const wrapH = wrap.clientHeight;
      if (wrapW < 8 || wrapH < 8) return;
      const tipW = tip.offsetWidth;
      const tipH = tip.offsetHeight;
      const edge = 6;
      const gap = 12;
      const px = (pt.x / w) * wrapW;
      const py = (pt.y / h) * wrapH;

      let left = px - tipW / 2;
      left = Math.max(edge, Math.min(left, wrapW - tipW - edge));

      let top = py - tipH - gap; // prefer above the point
      if (top < edge) top = py + gap; // flip below
      if (top + tipH > wrapH - edge) {{
        // Still overflowing: clamp inside, preferring space with more room
        const aboveSpace = py - edge;
        const belowSpace = wrapH - edge - py;
        if (aboveSpace >= belowSpace && aboveSpace >= tipH) top = py - tipH - gap;
        else if (belowSpace >= tipH) top = py + gap;
        else top = Math.max(edge, Math.min(py - tipH / 2, wrapH - tipH - edge));
      }}
      top = Math.max(edge, Math.min(top, wrapH - tipH - edge));

      tip.style.left = left + 'px';
      tip.style.top = top + 'px';
      tip.style.transform = 'none';
    }};
    place();
    requestAnimationFrame(place);
  }}

  hits.forEach((hit, idx) => {{
    hit.addEventListener('mouseenter', () => showTip(idx));
    hit.addEventListener('focus', () => showTip(idx));
    hit.addEventListener('mouseleave', hideTip);
    hit.addEventListener('blur', hideTip);
  }});
  wrap.addEventListener('mouseleave', hideTip);

  const rawMin = Math.min.apply(null, vals);
  const rawMax = Math.max.apply(null, vals);
  container.innerHTML = '';
  container.appendChild(wrap);

  return {{ min: rawMin, max: rawMax, first: vals[0], last: vals[vals.length - 1], up, stroke }};
}}

function renderDetailHistory(item) {{
  const body = document.getElementById('dHistoryBody');
  let hist = itemValueHistory(item);
  // Synthesize a prior point from recent % change when history is thin
  if (hist.length < 2) {{
    const pct = itemChangePct(item);
    if (pct !== 0 && item.value > 0) {{
      const prev = item.value / (1 + pct / 100);
      if (Number.isFinite(prev) && prev > 0) {{
        hist = [{{ v: prev, label: 'Estimated prior' }}, {{ v: item.value, label: 'Current' }}];
      }}
    }}
  }}
  if (hist.length < 2) {{
    body.innerHTML = '<div class="hempty">No history points yet — re-scrape values to build a series.</div>';
    return;
  }}
  const stats = mountInteractiveChart(body, hist, {{ spark: true, showArea: false, showAxes: false }});
  const delta = stats.last - stats.first;
  const deltaCls = delta > 0 ? 'up' : (delta < 0 ? 'down' : '');
  const meta = document.createElement('div');
  meta.className = 'hmeta';
  meta.innerHTML =
    '<span>' + hist.length + ' points</span>' +
    '<span>Min <strong>' + fmt(stats.min) + '</strong></span>' +
    '<span>Max <strong>' + fmt(stats.max) + '</strong></span>' +
    '<span>Latest <strong>' + fmt(stats.last) + '</strong></span>' +
    '<span class="delta ' + deltaCls + '">' + signedFmt(delta) + '</span>';
  body.appendChild(meta);
}}

function itemChangePct(item) {{
  if (!item) return 0;
  if (typeof item.changePct === 'number' && Number.isFinite(item.changePct)) return item.changePct;
  return parseChangePct(item.change);
}}

function itemChangeAbs(item) {{
  if (!item) return 0;
  return parseChangeAbs(item.change, item.value, itemChangePct(item));
}}

/**
 * Most recent value move from item history (preferred), else SV change fields.
 * abs = signed absolute change, changedAt = unix seconds (0 if unknown).
 */
function itemLastValueMove(item) {{
  const hist = itemValueHistory(item);
  for (let i = hist.length - 1; i >= 1; i--) {{
    const delta = hist[i].v - hist[i - 1].v;
    if (Math.abs(delta) < 0.05) continue;
    const prev = hist[i - 1].v;
    return {{
      abs: delta,
      pct: prev > 0 ? (delta / prev) * 100 : 0,
      changedAt: Number.isFinite(hist[i].t) ? hist[i].t : 0,
    }};
  }}
  return {{
    abs: itemChangeAbs(item),
    pct: itemChangePct(item),
    changedAt: 0,
  }};
}}

function historyRiseScore(item) {{
  const hist = itemValueHistory(item);
  if (hist.length >= 3) {{
    let rises = 0;
    for (let i = 1; i < hist.length; i++) {{
      if (hist[i].v > hist[i - 1].v + 0.05) rises += 1;
      else if (hist[i].v < hist[i - 1].v - 0.05) rises -= 1;
    }}
    const net = hist[hist.length - 1].v - hist[0].v;
    return rises + (net > 0 ? 1.5 : 0);
  }}
  const pct = itemChangePct(item);
  return pct > 0 ? pct / 2 : 0;
}}

/** Higher = more confidently dropping / worth trading off. */
function itemDropSignal(item) {{
  if (!item || item.value < 1) return null;
  const pct = itemChangePct(item);
  const lost = parseChangeAbs(item.change, item.value, pct);
  const hist = itemValueHistory(item);

  // Major recent drop: at least 5% off, or a large absolute hit (scales with value)
  const majorAbs = Math.max(50, item.value * 0.05);
  const majorDrop = (Number.isFinite(lost) && lost <= -majorAbs) || pct <= -5;

  // 3+ drops among the last 4 value changes (needs 5 history points)
  let dropsInLast4 = 0;
  if (hist.length >= 5) {{
    for (let i = hist.length - 4; i < hist.length; i++) {{
      if (hist[i].v < hist[i - 1].v - 0.05) dropsInLast4 += 1;
    }}
  }}
  const frequentDrops = dropsInLast4 >= 3;

  if (!majorDrop && !frequentDrops) return null;

  let score = 0;
  if (majorDrop) {{
    score += Math.abs(pct);
    score += Math.min(12, Math.abs(lost) / Math.max(item.value, 1) * 100);
  }}
  if (frequentDrops) score += dropsInLast4 * 2.5;
  if (item.value >= 250) score += 1.5;

  let why = '';
  if (majorDrop) why = 'down ' + fmt(Math.abs(lost || (item.value * Math.abs(pct) / 100)));
  else why = dropsInLast4 + ' drops in last 4';

  return {{ score, why, pct, lost, majorDrop, dropsInLast4 }};
}}

function historyDropScore(item) {{
  const hist = itemValueHistory(item);
  if (hist.length >= 3) {{
    let drops = 0;
    for (let i = 1; i < hist.length; i++) {{
      if (hist[i].v < hist[i - 1].v - 0.05) drops += 1;
      else if (hist[i].v > hist[i - 1].v + 0.05) drops -= 1;
    }}
    const net = hist[hist.length - 1].v - hist[0].v;
    return drops + (net < 0 ? 1.5 : 0);
  }}
  const pct = itemChangePct(item);
  return pct < 0 ? Math.abs(pct) / 2 : 0;
}}

/**
 * Outlook mark next to item names:
 * fire / rise2 / rise / flat / drop / drop2 / caution
 */
function itemOutlook(item) {{
  if (!item) return 'flat';
  const drop = itemDropSignal(item);
  const rise = historyRiseScore(item);
  const fall = historyDropScore(item);
  const pct = itemChangePct(item);
  const move = itemLastValueMove(item);
  const lastAbs = move && Number.isFinite(move.abs) ? move.abs : 0;
  const stab = item.stability;
  const trending = itemIsHot(item);

  // Drop side wins when a clear drop signal exists
  if (drop) {{
    if (drop.score >= 10 || (drop.majorDrop && drop.dropsInLast4 >= 3)) return 'caution';
    if (drop.score >= 6 || drop.majorDrop || drop.dropsInLast4 >= 3) return 'drop2';
    return 'drop';
  }}

  if (trending) return 'fire';
  if (rise >= 4.5 || (pct >= 3 && rise >= 2) || (stab === 'Doing Well' && pct >= 1.5)) return 'fire';
  if (rise >= 3 || pct >= 1.5 || ((stab === 'Doing Well' || stab === 'Underpaid For') && pct > 0.4)) {{
    return 'rise2';
  }}
  if (rise >= 1.5 || pct > 0.25 || lastAbs > 0.05) return 'rise';

  if (fall >= 3 || pct <= -1.5 || lastAbs < -Math.max(25, item.value * 0.03)) return 'drop2';
  if (fall >= 1.5 || pct < -0.25 || lastAbs < -0.05) return 'drop';

  return 'flat';
}}

const OUTLOOK_MARK = {{
  fire: {{ cls: 'hot', glyph: '🔥', title: 'Very likely to raise' }},
  rise2: {{ cls: 'rise2', glyph: '↑↑', title: 'Likely to raise' }},
  rise: {{ cls: 'rise', glyph: '↑', title: 'May raise' }},
  flat: {{ cls: 'flat', glyph: '─', title: 'Hard to predict' }},
  drop: {{ cls: 'drop', glyph: '↓', title: 'May drop' }},
  drop2: {{ cls: 'drop2', glyph: '↓↓', title: 'Likely to drop' }},
  caution: {{ cls: 'caution', glyph: '⚠', title: 'Very likely to drop' }},
}};

function loadDumpIntoYourOffer(item) {{
  if (!item) return;
  // Prefer stacking onto existing slot; otherwise use an empty unique slot
  const existing = state.your.find((e) => e && e.id === item.id);
  if (existing) {{
    existing.qty = Math.min(99, existing.qty + 1);
    existing._bump = true;
  }} else {{
    const idx = firstEmpty('your');
    if (idx === -1) {{
      alert('Your Offer is full (4 unique items). Clear a slot first.');
      return;
    }}
    state.your[idx] = {{
      id: item.id,
      name: item.name,
      value: item.value,
      image: item.image,
      qty: 1,
      _enter: true,
    }};
  }}
  state.lowerCycle = null;
  state.higherCycle = null;
  renderTradeOnly();
  window.scrollTo({{ top: 0, behavior: 'smooth' }});
}}

const TRENDING_IDS = new Set(
  (TRENDING || []).map((t) => t && t.id).filter(Boolean)
);

function itemNameHtml(item, opts) {{
  opts = opts || {{}};
  const chroma = item && (item.rarity === 'Chroma' || isChromaSet(item));
  const outlook = opts.outlook || itemOutlook(item);
  const hot = outlook === 'fire' || !!opts.hot;
  // Chroma rainbow wins over fire gradient when both apply
  let cls = opts.className || 'name';
  if (chroma) cls += ' chroma-name';
  else if (hot) cls += ' hot-name';
  let marks = '';
  if (opts.marks !== false) {{
    const mark = OUTLOOK_MARK[outlook] || OUTLOOK_MARK.flat;
    marks = '<span class="name-mark ' + mark.cls + '" title="' + mark.title + '" aria-label="' + mark.title + '">' +
      mark.glyph + '</span>';
  }}
  const safe = String((item && item.name) || '—');
  return '<span class="' + cls + '">' + safe + '</span>' + marks;
}}

/** True hot = Market Pulse trending / "hot" tier — not ordinary raises. */
function itemIsHot(item) {{
  if (!item || !item.id) return false;
  if (itemDropSignal(item)) return false;
  return TRENDING_IDS.has(item.id);
}}

function renderInvDumpTips() {{
  if (!invDumpTips) return;
  invDumpTips.innerHTML = '';
  invDumpTips.classList.remove('show');
  if (!state.inv.length) return;

  const tips = [];
  for (const entry of state.inv) {{
    if (!entry) continue;
    const item = byId[entry.id];
    if (!item) continue;
    const sig = itemDropSignal(item);
    if (!sig) continue;
    tips.push({{ item, entry, sig }});
  }}
  tips.sort((a, b) => b.sig.score - a.sig.score || a.sig.lost - b.sig.lost);
  const top = tips.slice(0, 3);
  if (!top.length) return;

  invDumpTips.classList.add('show');
  const head = document.createElement('div');
  head.className = 'inv-dump-head';
  head.textContent = 'Trade these off';
  invDumpTips.appendChild(head);

  for (const tip of top) {{
    const row = document.createElement('div');
    row.className = 'inv-dump-row';
    const art = tip.item.image
      ? '<img src="' + tip.item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
      : '<div class="noimg">?</div>';
    row.innerHTML =
      art +
      '<div><div class="dump-title">' + itemNameHtml(tip.item, {{ className: 'name' }}) + '</div>' +
      '<div class="why">' + tip.sig.why + '</div></div>';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Offer';
    btn.addEventListener('click', (e) => {{
      e.stopPropagation();
      loadDumpIntoYourOffer(tip.item);
    }});
    row.appendChild(btn);
    row.addEventListener('click', (e) => {{
      if (e.target === btn) return;
      openDetail(tip.item);
    }});
    row.style.cursor = 'pointer';
    invDumpTips.appendChild(row);
  }}
}}

function renderTrendRow(item, pctLabel, pctClass, opts) {{
  opts = opts || {{}};
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'trend-row';
  const art = item.image
    ? '<img src="' + item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
    : '<div class="noimg">?</div>';
  const when = opts.when ? formatChartDate(opts.when, true) : '';
  const metaBits = [fmt(item.value)];
  if (when) metaBits.push(when);
  else if (item.stability) metaBits.push(item.stability);
  btn.innerHTML =
    art +
    '<div><div class="tname-wrap">' + itemNameHtml(item, {{
      className: 'tname',
    }}) + '</div>' +
    '<div class="tmeta">' + metaBits.join(' · ') + '</div></div>' +
    '<div class="tpct ' + pctClass + '">' + pctLabel + '</div>';
  btn.addEventListener('click', () => openDetail(item));
  return btn;
}}

function renderTrendsPanel() {{
  const raisesEl = document.getElementById('trendRaises');
  const dropsEl = document.getElementById('trendDrops');
  const risersEl = document.getElementById('trendRisers');
  raisesEl.innerHTML = '';
  dropsEl.innerHTML = '';
  risersEl.innerHTML = '';

  const elite = CATALOG.filter((item) => (
    item && item.value >= 250 && SUGGEST_RARITIES.has(item.rarity)
  ));
  const scored = elite.map((item) => {{
    const move = itemLastValueMove(item);
    return {{ item, pct: move.pct, abs: move.abs, changedAt: move.changedAt }};
  }});

  // Newest value moves first (not largest).
  const raises = scored.filter((r) => r.abs > 0.05)
    .sort((a, b) => b.changedAt - a.changedAt || b.abs - a.abs || b.pct - a.pct)
    .slice(0, 6);
  const drops = scored.filter((r) => r.abs < -0.05)
    .sort((a, b) => b.changedAt - a.changedAt || a.abs - b.abs || a.pct - b.pct)
    .slice(0, 6);

  if (!raises.length) raisesEl.innerHTML = '<div class="trends-empty">No recent raises.</div>';
  else raises.forEach((r) => raisesEl.appendChild(renderTrendRow(r.item, signedFmt(r.abs), 'up', {{
    hot: itemIsHot(r.item),
    when: r.changedAt,
  }})));

  if (!drops.length) dropsEl.innerHTML = '<div class="trends-empty">No recent drops.</div>';
  else drops.forEach((r) => dropsEl.appendChild(renderTrendRow(r.item, signedFmt(r.abs), 'down', {{
    caution: !!itemDropSignal(r.item),
    when: r.changedAt,
  }})));

  // Constantly rising: history streak + SV trending + stability
  const risers = elite
    .map((item) => {{
      let score = historyRiseScore(item);
      if (TRENDING_IDS.has(item.id)) score += 4;
      if (item.stability === 'Doing Well' || item.stability === 'Underpaid For') score += 1;
      return {{ item, score, pct: itemChangePct(item), abs: itemChangeAbs(item) }};
    }})
    .filter((r) => r.score >= 2 || TRENDING_IDS.has(r.item.id))
    .sort((a, b) => b.score - a.score || b.abs - a.abs || b.pct - a.pct)
    .slice(0, 6);

  if (!risers.length) {{
    risersEl.innerHTML = '<div class="trends-empty">No strong risers right now.</div>';
  }} else {{
    risers.forEach((r) => {{
      const isHot = itemIsHot(r.item);
      const label = isHot
        ? 'hot'
        : (r.abs > 0 ? signedFmt(r.abs) : '↑');
      risersEl.appendChild(renderTrendRow(r.item, label, 'up', {{ hot: isHot }}));
    }});
  }}
}}

function closeDetail() {{
  detail.classList.remove('open');
}}

function sideTotal(side) {{
  return state[side].reduce((sum, entry) => {{
    if (!entry) return sum;
    return sum + entry.value * entry.qty;
  }}, 0);
}}

function updateHeader() {{
  const yours = sideTotal('your');
  const theirs = sideTotal('their');
  yourValueEl.textContent = fmt(yours);
  theirValueEl.textContent = fmt(theirs);

  const total = yours + theirs;
  let pct = 50;
  if (total > 0) pct = (yours / total) * 100;
  pct = Math.max(2, Math.min(98, pct));
  meterFill.style.width = pct + '%';

  verdictEl.className = 'verdict';
  if (yours === 0 && theirs === 0) {{
    verdictEl.classList.add('fair');
    verdictEl.textContent = '—';
    meterFill.style.background = 'linear-gradient(90deg, var(--purple-deep), var(--purple-bright))';
    return;
  }}

  const diff = theirs - yours;
  const abs = Math.abs(diff);
  // Always show the real absolute gap (high-value trades used to collapse
  // anything under ~2% relative to "0", hiding large listed differences).
  if (abs < 0.5) {{
    verdictEl.classList.add('fair');
    verdictEl.textContent = '0';
    meterFill.style.background = 'linear-gradient(90deg, var(--purple-deep), var(--purple-bright))';
  }} else if (diff > 0) {{
    verdictEl.classList.add('win');
    verdictEl.textContent = '+' + fmt(diff);
    meterFill.style.background = 'var(--green)';
  }} else {{
    verdictEl.classList.add('loss');
    verdictEl.textContent = '-' + fmt(abs);
    meterFill.style.background = 'var(--red)';
  }}
}}

function updateTradeCaution() {{
  const el = document.getElementById('tradeCaution');
  const theirBoard = document.getElementById('theirBoard');
  const losers = [];
  for (const entry of state.their) {{
    if (!entry) continue;
    const item = byId[entry.id];
    if (!item) continue;
    const sig = itemDropSignal(item);
    if (!sig) continue;
    losers.push({{
      name: item.name,
      pct: sig.pct,
      lost: sig.lost,
      why: sig.why,
    }});
  }}
  losers.sort((a, b) => (a.lost || 0) - (b.lost || 0)); // biggest absolute loss first

  if (!losers.length) {{
    el.classList.remove('show');
    el.innerHTML = '';
    if (theirBoard) theirBoard.classList.remove('caution-side');
    return;
  }}

  const bits = losers.slice(0, 3).map((row) => {{
    const lossLabel = row.lost < 0 ? ('-' + fmt(Math.abs(row.lost))) : row.why;
    return row.name + ' <span class="drop">' + lossLabel + '</span>';
  }});
  const extra = losers.length > 3 ? ' · +' + (losers.length - 3) + ' more' : '';
  el.innerHTML =
    '<strong>Caution</strong> — item' + (losers.length === 1 ? '' : 's') +
    ' you\\'re receiving recently lost value: ' + bits.join(', ') + extra;
  el.classList.add('show');
  if (theirBoard) theirBoard.classList.add('caution-side');
}}

function firstEmpty(side) {{
  return state[side].findIndex((x) => !x);
}}

function removeTradeEntry(side, index, slotEl) {{
  const finish = () => {{
    state[side][index] = null;
    paintTradeSlot(side, index);
    updateHeader();
    updateTradeCaution();
    updateGenOfferBtn();
    commitHistoryDeferred();
  }};
  if (!slotEl || (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches)) {{
    finish();
    return;
  }}
  if (slotEl.classList.contains('slot-exit')) return;
  slotEl.classList.add('slot-exit');
  window.setTimeout(finish, 160);
}}

function bumpTradeTotals() {{
  updateHeader();
  updateTradeCaution();
  updateGenOfferBtn();
  commitHistoryDeferred();
}}

function paintTradeSlot(side, index) {{
  const grid = side === 'your' ? yourGrid : theirGrid;
  if (!grid) return;
  while (grid.children.length < SLOTS) {{
    const placeholder = document.createElement('div');
    placeholder.className = 'slot empty';
    grid.appendChild(placeholder);
  }}
  const next = buildTradeSlotEl(side, index);
  const prev = grid.children[index];
  if (prev) grid.replaceChild(next, prev);
  else grid.appendChild(next);
}}

function paintTradeBoards(opts) {{
  opts = opts || {{}};
  // Prefer surgical updates when only a few slots changed; full rebuild is fine for loads/resets
  if (opts.full || yourGrid.children.length !== SLOTS || theirGrid.children.length !== SLOTS) {{
    renderSide('your', yourGrid);
    renderSide('their', theirGrid);
  }} else {{
    for (let i = 0; i < SLOTS; i++) {{
      paintTradeSlot('your', i);
      paintTradeSlot('their', i);
    }}
  }}
  updateHeader();
  updateTradeCaution();
  updateGenOfferBtn();
}}

function buildTradeSlotEl(side, i) {{
  const entry = state[side][i];
  const slot = document.createElement('div');
  slot.className = 'slot ' + (entry ? 'filled' : 'empty');
  slot.dataset.side = side;
  slot.dataset.index = String(i);
  if (entry && entry._enter) {{
    slot.classList.add('slot-enter');
    delete entry._enter;
  }} else if (entry && entry._bump) {{
    slot.classList.add('slot-bump');
    delete entry._bump;
  }}

  if (!entry) {{
    slot.innerHTML = '<div class="plus">+</div>';
    slot.addEventListener('click', () => openPicker(side));
    return slot;
  }}

  const img = entry.image
    ? '<img class="art" src="' + entry.image + '" alt="" decoding="async" referrerpolicy="no-referrer" />'
    : '<div class="art" style="display:grid;place-items:center;color:#9aa3b2;font-size:11px">No img</div>';
  slot.innerHTML =
    '<button class="remove" type="button" title="Remove">×</button>' +
    img +
    '<div class="qty">' +
      '<button type="button" data-act="dec">−</button>' +
      '<input type="number" min="1" max="99" value="' + entry.qty + '" />' +
      '<button type="button" data-act="inc">+</button>' +
    '</div>';

  const input = slot.querySelector('input');
  const bumpQtyUi = () => {{
    input.value = entry.qty;
    slot.classList.remove('slot-bump');
    void slot.offsetWidth;
    slot.classList.add('slot-bump');
    bumpTradeTotals();
  }};

  slot.querySelector('.remove').addEventListener('click', (e) => {{
    e.stopPropagation();
    removeTradeEntry(side, i, slot);
  }});
  slot.querySelector('[data-act="dec"]').addEventListener('click', (e) => {{
    e.stopPropagation();
    if (entry.qty <= 1) {{
      removeTradeEntry(side, i, slot);
      return;
    }}
    entry.qty -= 1;
    bumpQtyUi();
  }});
  slot.querySelector('[data-act="inc"]').addEventListener('click', (e) => {{
    e.stopPropagation();
    entry.qty = Math.min(99, entry.qty + 1);
    bumpQtyUi();
  }});
  input.addEventListener('click', (e) => e.stopPropagation());
  input.addEventListener('change', () => {{
    let n = parseInt(input.value, 10);
    if (!Number.isFinite(n) || n < 1) n = 1;
    entry.qty = Math.min(99, n);
    bumpQtyUi();
  }});
  slot.addEventListener('click', (e) => {{
    if (e.target.closest('.qty') || e.target.closest('.remove')) return;
    const full = byId[entry.id];
    if (full) openDetail(full);
  }});
  slot.addEventListener('contextmenu', (e) => {{
    e.preventDefault();
    removeTradeEntry(side, i, slot);
  }});
  slot.title = 'Click for details · Right-click to remove';
  slot.style.cursor = 'pointer';
  return slot;
}}

function renderSide(side, grid) {{
  const frag = document.createDocumentFragment();
  for (let i = 0; i < SLOTS; i++) frag.appendChild(buildTradeSlotEl(side, i));
  grid.replaceChildren(frag);
}}

function invTotal() {{
  return state.inv.reduce((sum, entry) => {{
    const item = byId[entry.id];
    if (!item) return sum;
    return sum + item.value * entry.qty;
  }}, 0);
}}

function signedFmt(n) {{
  const abs = Math.abs(Math.round(n));
  if (abs < 0.5) return '0';
  return (n > 0 ? '+' : '-') + fmt(abs);
}}

function persistInv() {{
  try {{
    localStorage.setItem(INV_KEY, JSON.stringify({{
      items: state.inv,
      history: state.invHistory,
    }}));
  }} catch (_) {{}}
}}

function persistTargets() {{
  try {{
    localStorage.setItem(TARGET_KEY, JSON.stringify({{ items: state.targets }}));
  }} catch (_) {{}}
}}

function persistDumpList() {{
  try {{
    localStorage.setItem(DUMP_KEY, JSON.stringify({{ items: state.dumpList }}));
  }} catch (_) {{}}
}}

function persistTradeHistory() {{
  try {{
    localStorage.setItem(TRADE_HIST_KEY, JSON.stringify({{ trades: state.tradeHistory }}));
  }} catch (_) {{}}
  updateTradeHistBadge();
}}

function updateTradeHistBadge() {{
  const n = state.tradeHistory.length;
  const label = String(n);
  if (tradeHistBadge) tradeHistBadge.textContent = label;
  if (tradeHistCountEl) tradeHistCountEl.textContent = label;
  if (tradeHistBtn) {{
    tradeHistBtn.setAttribute(
      'aria-label',
      n === 1 ? 'Trade History, 1 saved trade' : 'Trade History, ' + n + ' saved trades'
    );
  }}
}}

function normalizeTradeSide(side) {{
  if (!Array.isArray(side)) return [];
  return side
    .filter((e) => e && e.id)
    .map((e) => ({{
      id: e.id,
      qty: Math.max(1, Math.min(99, parseInt(e.qty, 10) || 1)),
      value: Number.isFinite(e.value) ? e.value : 0,
    }}));
}}

function tradeSideFingerprint(side) {{
  return normalizeTradeSide(side)
    .map((e) => e.id + ':' + e.qty)
    .sort()
    .join(',');
}}

function tradeFingerprint(your, their) {{
  return tradeSideFingerprint(your) + '>' + tradeSideFingerprint(their);
}}

function persistTradeDismissed() {{
  try {{
    localStorage.setItem(
      TRADE_DISMISS_KEY,
      JSON.stringify({{ keys: state.tradeDismissed.slice(-120) }})
    );
  }} catch (_) {{}}
}}

function loadTradeDismissed() {{
  try {{
    const raw = localStorage.getItem(TRADE_DISMISS_KEY);
    if (!raw) {{
      state.tradeDismissed = [];
      return;
    }}
    const data = JSON.parse(raw);
    const keys = Array.isArray(data.keys) ? data.keys : [];
    state.tradeDismissed = keys.filter((k) => typeof k === 'string' && k).slice(-120);
  }} catch (_) {{
    state.tradeDismissed = [];
  }}
}}

function dismissTradeKey(key) {{
  if (!key || typeof key !== 'string') return;
  if (state.tradeDismissed.includes(key)) return;
  state.tradeDismissed.push(key);
  if (state.tradeDismissed.length > 120) {{
    state.tradeDismissed = state.tradeDismissed.slice(-120);
  }}
  persistTradeDismissed();
}}

/** Prefer catalog history at/near ts (ms). Falls back to current catalog value. */
function itemValueNearTime(id, tMs) {{
  const item = byId[id];
  if (!item) return 0;
  const current = Number.isFinite(item.value) ? item.value : 0;
  const hist = itemValueHistory(item);
  if (!hist.length) return current;

  const targetSec = tMs < 1e12 ? tMs : tMs / 1000;
  let bestBefore = null;
  let bestBeforeDist = Infinity;
  let bestAfter = null;
  let bestAfterDist = Infinity;
  let bestAny = null;
  let bestAnyDist = Infinity;

  for (const p of hist) {{
    if (!p || !Number.isFinite(p.t) || !Number.isFinite(p.v)) continue;
    const pt = p.t < 1e12 ? p.t : p.t / 1000;
    const dist = Math.abs(pt - targetSec);
    if (dist < bestAnyDist) {{
      bestAnyDist = dist;
      bestAny = p;
    }}
    if (pt <= targetSec) {{
      const d = targetSec - pt;
      if (d < bestBeforeDist) {{
        bestBeforeDist = d;
        bestBefore = p;
      }}
    }} else {{
      const d = pt - targetSec;
      if (d < bestAfterDist) {{
        bestAfterDist = d;
        bestAfter = p;
      }}
    }}
  }}

  if (bestBefore && bestBeforeDist <= 120 * 86400) return bestBefore.v;
  if (bestAfter && bestAfterDist <= 2 * 86400) return bestAfter.v;
  if (bestAny && bestAnyDist <= 120 * 86400) return bestAny.v;
  return current;
}}

function invQtyMap(items) {{
  const m = new Map();
  if (!Array.isArray(items)) return m;
  for (const e of items) {{
    if (!e || !e.id) continue;
    const qty = Math.max(0, parseInt(e.qty, 10) || 0);
    if (qty < 1) continue;
    m.set(e.id, (m.get(e.id) || 0) + qty);
  }}
  return m;
}}

function diffInvSnapshots(beforeItems, afterItems) {{
  const before = invQtyMap(beforeItems);
  const after = invQtyMap(afterItems);
  const gave = [];
  const got = [];
  const ids = new Set([...before.keys(), ...after.keys()]);
  for (const id of ids) {{
    const delta = (after.get(id) || 0) - (before.get(id) || 0);
    if (delta < 0) gave.push({{ id, qty: -delta }});
    else if (delta > 0) got.push({{ id, qty: delta }});
  }}
  gave.sort((a, b) => a.id.localeCompare(b.id));
  got.sort((a, b) => a.id.localeCompare(b.id));
  return {{ gave, got }};
}}

function sideUnitCount(side) {{
  return side.reduce((s, e) => s + (e.qty || 1), 0);
}}

function looksLikeInferredTrade(gave, got) {{
  if (!gave.length || !got.length) return false;
  if (gave.length > TRADE_INFER_MAX_UNIQUE_SIDE || got.length > TRADE_INFER_MAX_UNIQUE_SIDE) {{
    return false;
  }}
  if (sideUnitCount(gave) > TRADE_INFER_MAX_UNITS_SIDE || sideUnitCount(got) > TRADE_INFER_MAX_UNITS_SIDE) {{
    return false;
  }}
  // Skip one-sided bulk edits that only look two-sided because of tiny qty noise
  // (already requires both sides nonempty).
  // Skip if every changed id is unknown to the catalog (noise / deleted items).
  const knownGave = gave.filter((e) => byId[e.id]);
  const knownGot = got.filter((e) => byId[e.id]);
  if (!knownGave.length || !knownGot.length) return false;
  return true;
}}

function decorateTradeSide(side, tMs) {{
  return side.map((e) => ({{
    id: e.id,
    qty: e.qty,
    value: itemValueNearTime(e.id, tMs),
  }}));
}}

function tradeMatchesExisting(entry, existing) {{
  const fp = tradeFingerprint(entry.your, entry.their);
  for (const tr of existing) {{
    if (entry.key && tr.key && entry.key === tr.key) return true;
    if (Math.abs(tr.t - entry.t) > TRADE_INFER_DUP_MS) continue;
    if (tradeFingerprint(tr.your, tr.their) === fp) return true;
  }}
  return false;
}}

function trimTradeHistory() {{
  state.tradeHistory.sort((a, b) => a.t - b.t);
  if (state.tradeHistory.length > TRADE_HIST_MAX) {{
    state.tradeHistory = state.tradeHistory.slice(-TRADE_HIST_MAX);
  }}
}}

/** Infer trades from consecutive inventory snapshots that look like give+get. */
function syncInferredTradesFromInvHistory() {{
  const hist = state.invHistory.filter((p) => p && Number.isFinite(p.t) && Array.isArray(p.items));
  if (hist.length < 2) return false;

  const dismissed = new Set(state.tradeDismissed);
  let changed = false;

  for (let i = 1; i < hist.length; i++) {{
    const before = hist[i - 1];
    const after = hist[i];
    const key = 'inv:' + before.t + ':' + after.t;
    if (dismissed.has(key)) continue;
    if (state.tradeHistory.some((tr) => tr.key === key)) continue;

    const {{ gave, got }} = diffInvSnapshots(before.items, after.items);
    if (!looksLikeInferredTrade(gave, got)) continue;

    const t = after.t;
    const your = decorateTradeSide(gave, t);
    const their = decorateTradeSide(got, t);
    const yourTotal = your.reduce((s, e) => s + e.value * e.qty, 0);
    const theirTotal = their.reduce((s, e) => s + e.value * e.qty, 0);
    const entry = {{
      t,
      your,
      their,
      yourTotal,
      theirTotal,
      net: theirTotal - yourTotal,
      source: 'inventory',
      key,
    }};

    if (tradeMatchesExisting(entry, state.tradeHistory)) continue;

    state.tradeHistory.push(entry);
    changed = true;
  }}

  if (changed) {{
    trimTradeHistory();
    persistTradeHistory();
  }}
  return changed;
}}

function loadTradeHistory() {{
  try {{
    const raw = localStorage.getItem(TRADE_HIST_KEY);
    if (!raw) {{
      state.tradeHistory = [];
      return;
    }}
    const data = JSON.parse(raw);
    const trades = Array.isArray(data.trades) ? data.trades : [];
    state.tradeHistory = trades
      .filter((tr) => tr && Number.isFinite(tr.t))
      .map((tr) => {{
        const your = normalizeTradeSide(tr.your);
        const their = normalizeTradeSide(tr.their);
        const yourTotal = Number.isFinite(tr.yourTotal)
          ? tr.yourTotal
          : your.reduce((s, e) => s + e.value * e.qty, 0);
        const theirTotal = Number.isFinite(tr.theirTotal)
          ? tr.theirTotal
          : their.reduce((s, e) => s + e.value * e.qty, 0);
        const net = Number.isFinite(tr.net) ? tr.net : (theirTotal - yourTotal);
        const source = tr.source === 'inventory' ? 'inventory' : 'offer';
        const out = {{ t: tr.t, your, their, yourTotal, theirTotal, net, source }};
        if (typeof tr.key === 'string' && tr.key) out.key = tr.key;
        return out;
      }})
      .filter((tr) => tr.your.length && tr.their.length)
      .slice(-TRADE_HIST_MAX);
  }} catch (_) {{
    state.tradeHistory = [];
  }}
}}

function snapshotTradeSide(side) {{
  return state[side]
    .filter(Boolean)
    .map((e) => ({{
      id: e.id,
      qty: e.qty || 1,
      value: Number.isFinite(e.value) ? e.value : ((byId[e.id] && byId[e.id].value) || 0),
    }}));
}}

function pushTradeHistoryEntry() {{
  const your = snapshotTradeSide('your');
  const their = snapshotTradeSide('their');
  if (!your.length || !their.length) return null;
  const yourTotal = your.reduce((s, e) => s + e.value * e.qty, 0);
  const theirTotal = their.reduce((s, e) => s + e.value * e.qty, 0);
  const entry = {{
    t: Date.now(),
    your,
    their,
    yourTotal,
    theirTotal,
    net: theirTotal - yourTotal,
    source: 'offer',
  }};
  state.tradeHistory.push(entry);
  trimTradeHistory();
  persistTradeHistory();
  return entry;
}}

function sideValueNow(side) {{
  return side.reduce((sum, e) => {{
    const item = byId[e.id];
    const v = item ? item.value : 0;
    return sum + v * (e.qty || 1);
  }}, 0);
}}

function netClass(n) {{
  if (!Number.isFinite(n) || Math.abs(n) < 0.5) return 'fair';
  return n > 0 ? 'win' : 'loss';
}}

function netLabel(n) {{
  if (!Number.isFinite(n) || Math.abs(n) < 0.5) return '0';
  return signedFmt(n);
}}

function openTradeHistory() {{
  syncInferredTradesFromInvHistory();
  renderTradeHistory();
  tradeHistModal.classList.add('open');
}}

function closeTradeHistory() {{
  closePrevTrade();
  tradeHistModal.classList.remove('open');
}}

function closePrevTrade() {{
  if (prevTradeModal) prevTradeModal.classList.remove('open');
}}

function prevTradeSlotCard(entry) {{
  const item = byId[entry.id];
  const name = item ? item.name : entry.id;
  const image = item ? item.image : '';
  const qty = entry.qty || 1;
  const thenUnit = Number.isFinite(entry.value) ? entry.value : 0;
  const nowUnit = item ? item.value : 0;
  const thenV = thenUnit * qty;
  const nowV = nowUnit * qty;
  const delta = nowV - thenV;
  let deltaHtml = '';
  if (Math.abs(delta) >= 0.5) {{
    const cls = delta > 0 ? 'up' : 'down';
    deltaHtml = '<span class="delta ' + cls + '">' + signedFmt(delta) + '</span>';
  }}
  const art = image
    ? '<img class="art" src="' + image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
    : '<div class="art" style="display:grid;place-items:center;color:#9aa3b2;font-size:11px">No img</div>';
  const slot = document.createElement('div');
  slot.className = 'slot filled prev-trade-slot';
  slot.title = name;
  slot.innerHTML =
    art +
    '<div class="slot-name">' + name + '</div>' +
    '<div class="slot-qty">×' + qty + '</div>' +
    '<div class="slot-vals">' +
      '<span>then <strong>' + fmt(thenV) + '</strong></span>' +
      '<span>now <strong>' + fmt(nowV) + '</strong>' +
        (deltaHtml ? ' · ' + deltaHtml : '') +
      '</span>' +
    '</div>';
  if (item) {{
    slot.style.cursor = 'pointer';
    slot.addEventListener('click', () => openDetail(item));
  }}
  return slot;
}}

function fillPrevTradeGrid(grid, side) {{
  grid.innerHTML = '';
  if (!side.length) {{
    grid.innerHTML = '<div class="prev-trade-empty">No items</div>';
    return;
  }}
  const frag = document.createDocumentFragment();
  for (const e of side) frag.appendChild(prevTradeSlotCard(e));
  grid.appendChild(frag);
}}

function openPrevTrade(tr) {{
  if (!prevTradeModal || !tr) return;
  const yourNow = sideValueNow(tr.your);
  const theirNow = sideValueNow(tr.their);
  const netNow = theirNow - yourNow;
  const hindsight = netNow - tr.net;

  if (prevTradeTitle) {{
    prevTradeTitle.textContent = tr.source === 'inventory'
      ? 'Previous trade · From inventory'
      : 'Previous trade';
  }}
  if (prevTradeMeta) {{
    const hCls = netClass(hindsight);
    const hText = Math.abs(hindsight) < 0.5
      ? 'Even vs then'
      : (hindsight > 0 ? 'Better ' : 'Worse ') + signedFmt(hindsight);
    prevTradeMeta.innerHTML =
      '<span>When: <strong>' + formatFullDate(tr.t) + '</strong></span>' +
      (tr.source === 'inventory'
        ? '<span>Source: <strong>Inventory snapshot</strong></span>'
        : '<span>Source: <strong>Offer Completed</strong></span>') +
      '<span>Hindsight: <strong class="hindsight ' + hCls + '">' + hText + '</strong></span>';
  }}

  if (prevTradeCompare) {{
    prevTradeCompare.innerHTML =
      '<div class="value-box">' +
        '<div class="num">' + fmt(tr.yourTotal) + '</div>' +
        '<div class="label">YOUR THEN</div>' +
        '<div class="sub">now <strong>' + fmt(yourNow) + '</strong></div>' +
      '</div>' +
      '<div class="meter-wrap">' +
        '<p class="verdict ' + netClass(tr.net) + '">Net ' + netLabel(tr.net) + '</p>' +
        '<p class="verdict ' + netClass(netNow) + '" style="font-size:15px;margin-top:6px">Now ' + netLabel(netNow) + '</p>' +
      '</div>' +
      '<div class="value-box">' +
        '<div class="num">' + fmt(tr.theirTotal) + '</div>' +
        '<div class="label">THEIR THEN</div>' +
        '<div class="sub">now <strong>' + fmt(theirNow) + '</strong></div>' +
      '</div>';
  }}

  if (prevTradeYourTotals) {{
    prevTradeYourTotals.innerHTML =
      'Then <strong>' + fmt(tr.yourTotal) + '</strong> · Now <strong>' + fmt(yourNow) + '</strong>';
  }}
  if (prevTradeTheirTotals) {{
    prevTradeTheirTotals.innerHTML =
      'Then <strong>' + fmt(tr.theirTotal) + '</strong> · Now <strong>' + fmt(theirNow) + '</strong>';
  }}

  fillPrevTradeGrid(prevTradeYourGrid, tr.your);
  fillPrevTradeGrid(prevTradeTheirGrid, tr.their);
  prevTradeModal.classList.add('open');
}}

function tradeHistItemCard(entry) {{
  const item = byId[entry.id];
  const name = item ? item.name : entry.id;
  const image = item ? item.image : '';
  const qty = entry.qty || 1;
  const value = (Number.isFinite(entry.value) ? entry.value : 0) * qty;
  const art = image
    ? '<img src="' + image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
    : '<div class="noimg">?</div>';
  const card = document.createElement('div');
  card.className = 'trade-hist-item-card' + (item ? ' clickable' : '');
  card.innerHTML =
    '<div class="art-wrap">' + art + '</div>' +
    '<div class="iname" title="' + name + '">' + name + '</div>' +
    (qty > 1 ? '<div class="qty">×' + qty + '</div>' : '') +
    '<div class="vals"><strong>' + fmt(value) + '</strong></div>';
  if (item) {{
    card.addEventListener('click', () => openDetail(item));
  }}
  return card;
}}

function fillTradeHistCards(container, side) {{
  container.innerHTML = '';
  if (!side.length) {{
    container.innerHTML = '<div class="trade-hist-empty" style="padding:18px 8px">No items</div>';
    return;
  }}
  const frag = document.createDocumentFragment();
  for (const e of side) frag.appendChild(tradeHistItemCard(e));
  container.appendChild(frag);
}}

function tradeMatchesFilter(tr, q) {{
  if (!q) return true;
  const bits = [formatFullDate(tr.t)];
  for (const e of tr.your.concat(tr.their)) {{
    const item = byId[e.id];
    bits.push(e.id);
    if (item) bits.push(item.name);
  }}
  return bits.join(' ').toLowerCase().includes(q);
}}

function renderTradeHistDetail(tr, idx) {{
  if (!tradeHistDetail) return;
  if (!tr) {{
    tradeHistDetail.innerHTML =
      '<div class="trade-hist-detail-empty">Select a trade to view it.</div>';
    return;
  }}

  tradeHistDetail.innerHTML =
    '<div class="trade-hist-detail-head">' +
      '<div>' +
        '<h4>' + formatFullDate(tr.t) + '</h4>' +
      '</div>' +
      '<div class="trade-hist-detail-actions" data-actions></div>' +
    '</div>' +
    '<div class="trade-hist-summary">' +
      '<div class="box">' +
        '<div class="num">' + fmt(tr.yourTotal) + '</div>' +
        '<div class="label">GAVE</div>' +
      '</div>' +
      '<div class="mid">' +
        '<p class="verdict ' + netClass(tr.net) + '">' + netLabel(tr.net) + '</p>' +
        '<div class="hint">Net</div>' +
      '</div>' +
      '<div class="box">' +
        '<div class="num">' + fmt(tr.theirTotal) + '</div>' +
        '<div class="label">GOT</div>' +
      '</div>' +
    '</div>' +
    '<div class="trade-hist-section">' +
      '<div class="trade-hist-section-top"><h5>Gave</h5></div>' +
      '<div class="trade-hist-cards" data-cards="your"></div>' +
    '</div>' +
    '<div class="trade-hist-section">' +
      '<div class="trade-hist-section-top"><h5>Got</h5></div>' +
      '<div class="trade-hist-cards" data-cards="their"></div>' +
    '</div>';

  fillTradeHistCards(tradeHistDetail.querySelector('[data-cards="your"]'), tr.your);
  fillTradeHistCards(tradeHistDetail.querySelector('[data-cards="their"]'), tr.their);

  const actionsEl = tradeHistDetail.querySelector('[data-actions]');
  const delBtn = document.createElement('button');
  delBtn.type = 'button';
  delBtn.textContent = 'Remove';
  delBtn.addEventListener('click', () => {{
    if (!confirm('Remove this trade from history?')) return;
    closePrevTrade();
    const removed = state.tradeHistory[idx];
    if (removed && removed.source === 'inventory' && removed.key) {{
      dismissTradeKey(removed.key);
    }}
    state.tradeHistory.splice(idx, 1);
    if (tradeHistSelectedIdx === idx) tradeHistSelectedIdx = -1;
    else if (tradeHistSelectedIdx > idx) tradeHistSelectedIdx -= 1;
    persistTradeHistory();
    renderTradeHistory();
  }});
  actionsEl.appendChild(delBtn);
}}

function selectTradeHistory(idx) {{
  tradeHistSelectedIdx = idx;
  const tr = idx >= 0 ? state.tradeHistory[idx] : null;
  tradeHistList.querySelectorAll('.trade-hist-card').forEach((el) => {{
    el.classList.toggle('active', Number(el.dataset.idx) === idx);
  }});
  renderTradeHistDetail(tr, idx);
}}

function renderTradeHistory() {{
  updateTradeHistBadge();
  tradeHistList.innerHTML = '';
  const q = (tradeHistFilterText || '').trim().toLowerCase();

  if (!state.tradeHistory.length) {{
    tradeHistList.innerHTML =
      '<div class="trade-hist-empty">No saved trades yet.<br/>' +
      'Complete a trade with <strong>Offer Completed</strong>, or save inventory ' +
      'snapshots (before/after a trade) so we can infer one.</div>';
    renderTradeHistDetail(null, -1);
    return;
  }}

  const frag = document.createDocumentFragment();
  let firstVisible = -1;
  let selectedVisible = false;

  for (let i = state.tradeHistory.length - 1; i >= 0; i--) {{
    const tr = state.tradeHistory[i];
    if (!tradeMatchesFilter(tr, q)) continue;
    if (firstVisible < 0) firstVisible = i;
    if (i === tradeHistSelectedIdx) selectedVisible = true;

    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'trade-hist-card' + (i === tradeHistSelectedIdx ? ' active' : '');
    card.dataset.idx = String(i);
    card.innerHTML =
      '<div class="trade-hist-card-main">' +
        '<span class="when">' + formatFullDate(tr.t) + '</span>' +
      '</div>' +
      '<div class="trade-hist-card-side">' +
        '<span class="trade-hist-pill ' + netClass(tr.net) + '">' + signedFmt(tr.net) + '</span>' +
      '</div>';
    card.addEventListener('click', () => selectTradeHistory(i));
    frag.appendChild(card);
  }}

  if (!frag.childNodes.length) {{
    tradeHistList.innerHTML =
      '<div class="trade-hist-empty">No trades match your filter.</div>';
    renderTradeHistDetail(null, -1);
    return;
  }}

  tradeHistList.appendChild(frag);

  const pick = selectedVisible ? tradeHistSelectedIdx : firstVisible;
  selectTradeHistory(pick);
}}

function loadInv() {{
  try {{
    const raw = localStorage.getItem(INV_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    const items = Array.isArray(data.items) ? data.items : [];
    state.inv = items
      .filter((e) => e && e.id && byId[e.id])
      .map((e) => ({{
        id: e.id,
        qty: Math.max(1, Math.min(999, parseInt(e.qty, 10) || 1)),
      }}));
    state.invHistory = Array.isArray(data.history)
      ? data.history
          .filter((h) => h && Number.isFinite(h.v) && Number.isFinite(h.t))
          .map((h) => ({{
            t: h.t,
            v: h.v,
            items: Array.isArray(h.items)
              ? h.items
                  .filter((e) => e && e.id && byId[e.id])
                  .map((e) => ({{
                    id: e.id,
                    qty: Math.max(1, Math.min(999, parseInt(e.qty, 10) || 1)),
                  }}))
              : undefined,
          }}))
          .slice(-80)
      : [];
  }} catch (_) {{
    state.inv = [];
    state.invHistory = [];
  }}
}}

function loadTargets() {{
  try {{
    const raw = localStorage.getItem(TARGET_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    const items = Array.isArray(data.items) ? data.items : [];
    state.targets = items
      .filter((e) => e && e.id && byId[e.id])
      .map((e) => ({{
        id: e.id,
        qty: Math.max(1, Math.min(9, parseInt(e.qty, 10) || 1)),
      }}));
  }} catch (_) {{
    state.targets = [];
  }}
}}

function loadDumpList() {{
  try {{
    const raw = localStorage.getItem(DUMP_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    const items = Array.isArray(data.items) ? data.items : [];
    state.dumpList = items
      .filter((e) => e && e.id && byId[e.id])
      .map((e) => ({{
        id: e.id,
        qty: Math.max(1, Math.min(9, parseInt(e.qty, 10) || 1)),
      }}));
  }} catch (_) {{
    state.dumpList = [];
  }}
}}

function renderDumpList() {{
  if (!dumpListEl) return;
  dumpListEl.innerHTML = '';
  if (!state.dumpList.length) {{
    dumpListEl.innerHTML = '<div class="target-empty">Auto-detects drops · or add your own</div>';
    persistDumpList();
    return;
  }}
  const frag = document.createDocumentFragment();
  for (const entry of state.dumpList) {{
    const item = byId[entry.id];
    if (!item) continue;
    const chip = document.createElement('div');
    chip.className = 'target-chip';
    const art = item.image
      ? '<img src="' + item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
      : '<div class="noimg">?</div>';
    chip.innerHTML =
      art +
      '<span class="label" title="' + item.name + '">' + item.name + '</span>' +
      '<span class="val">' + fmt(item.value) + '</span>' +
      '<button class="x" type="button" aria-label="Remove">×</button>';
    chip.querySelector('.x').addEventListener('click', (e) => {{
      e.stopPropagation();
      state.dumpList = state.dumpList.filter((t) => t.id !== entry.id);
      render();
      commitHistory();
    }});
    chip.addEventListener('click', () => openDetail(item));
    chip.style.cursor = 'pointer';
    frag.appendChild(chip);
  }}
  dumpListEl.appendChild(frag);
  persistDumpList();
}}

function renderTargets() {{
  targetList.innerHTML = '';
  if (!state.targets.length) {{
    targetList.innerHTML = '<div class="target-empty">No targets</div>';
    persistTargets();
    return;
  }}
  const frag = document.createDocumentFragment();
  for (const entry of state.targets) {{
    const item = byId[entry.id];
    if (!item) continue;
    const chip = document.createElement('div');
    chip.className = 'target-chip';
    const art = item.image
      ? '<img src="' + item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
      : '<div class="noimg">?</div>';
    chip.innerHTML =
      art +
      '<span class="label" title="' + item.name + '">' + item.name + '</span>' +
      '<span class="val">' + fmt(item.value) + '</span>' +
      '<button class="x" type="button" aria-label="Remove">×</button>';
    chip.querySelector('.x').addEventListener('click', (e) => {{
      e.stopPropagation();
      state.targets = state.targets.filter((t) => t.id !== entry.id);
      render();
      commitHistory();
    }});
    chip.addEventListener('click', () => openDetail(item));
    chip.style.cursor = 'pointer';
    frag.appendChild(chip);
  }}
  targetList.appendChild(frag);
  persistTargets();
}}

function lastSavedValue() {{
  const hist = state.invHistory;
  if (!hist.length) return null;
  return hist[hist.length - 1].v;
}}

function isInvDirty() {{
  if (!state.invHistory.length) return state.inv.length > 0;
  const last = state.invHistory[state.invHistory.length - 1];
  if (Math.abs(invTotal() - last.v) >= 0.5) return true;
  if (Array.isArray(last.items) && invItemsKey(last.items) !== currentInvItemsKey()) return true;
  return false;
}}

function invItemsKey(items) {{
  if (!items || !items.length) return '';
  return items
    .map((e) => e.id + ':' + (e.qty || 1))
    .sort()
    .join('|');
}}

function currentInvItemsKey() {{
  return invItemsKey(state.inv);
}}

function cloneCurrentInvItems() {{
  return state.inv.map((e) => ({{ id: e.id, qty: e.qty || 1 }}));
}}

function pushInvHistoryPoint(total) {{
  state.invHistory.push({{
    t: Date.now(),
    v: total,
    items: cloneCurrentInvItems(),
  }});
  if (state.invHistory.length > 80) state.invHistory = state.invHistory.slice(-80);
}}

function saveInvSnapshot() {{
  const total = invTotal();
  const last = state.invHistory.length ? state.invHistory[state.invHistory.length - 1] : null;
  const sameValue = last != null && Math.abs(last.v - total) < 0.5;
  const sameItems = last != null && invItemsKey(last.items) === currentInvItemsKey();
  if (last && sameValue && sameItems) {{
    setInvStatus('Already saved');
    return;
  }}
  pushInvHistoryPoint(total);
  persistInv();
  syncInferredTradesFromInvHistory();
  updateInvPanel();
  commitHistory();
  setInvStatus('Saved · ' + new Date().toLocaleString());
}}

/** Inventory snapshots use Date.now() (ms); item value history uses unix seconds. */
function toJsDate(ts) {{
  if (!Number.isFinite(ts)) return null;
  // < ~year 2001 in ms means this is almost certainly seconds
  const ms = ts < 1e12 ? ts * 1000 : ts;
  const d = new Date(ms);
  return Number.isNaN(d.getTime()) ? null : d;
}}

function formatShortDate(ts) {{
  try {{
    const d = toJsDate(ts);
    if (!d) return '';
    return d.toLocaleDateString(undefined, {{ month: 'short', day: 'numeric' }});
  }} catch (_) {{
    return '';
  }}
}}

function formatFullDate(ts) {{
  try {{
    const d = toJsDate(ts);
    if (!d) return String(ts);
    return d.toLocaleString();
  }} catch (_) {{
    return String(ts);
  }}
}}

function formatChartDate(ts, short) {{
  try {{
    const d = toJsDate(ts);
    if (!d) return '';
    if (short) return d.toLocaleDateString(undefined, {{ month: 'short', day: 'numeric', year: 'numeric' }});
    return d.toLocaleDateString(undefined, {{ year: 'numeric', month: 'short', day: 'numeric' }});
  }} catch (_) {{
    return '';
  }}
}}

function histItemCount(point) {{
  if (!point || !Array.isArray(point.items)) return null;
  return point.items.reduce((s, e) => s + (e.qty || 1), 0);
}}

function renderInvHistoryList() {{
  const hist = state.invHistory;
  invHistList.innerHTML = '';
  if (!hist.length) {{
    invHistList.innerHTML = '<div class="inv-hist-empty">No snapshots yet</div>';
    return;
  }}

  const frag = document.createDocumentFragment();
  let firstCard = null;
  for (let i = hist.length - 1; i >= 0; i--) {{
    const point = hist[i];
    const prev = i > 0 ? hist[i - 1] : null;
    const delta = prev ? point.v - prev.v : null;
    const count = histItemCount(point);
    const card = document.createElement('div');
    card.className = 'inv-hist-card';
    if (!firstCard) firstCard = card;

    let deltaClass = '';
    let deltaText = 'Starting save';
    if (delta != null) {{
      if (Math.abs(delta) < 0.5) {{
        deltaText = 'No value change';
      }} else if (delta > 0) {{
        deltaClass = ' delta-up';
        deltaText = signedFmt(delta) + ' vs prior';
      }} else {{
        deltaClass = ' delta-down';
        deltaText = signedFmt(delta) + ' vs prior';
      }}
    }}
    const countText = count == null
      ? 'Value only'
      : (count + ' item' + (count === 1 ? '' : 's'));
    const uniqueText = Array.isArray(point.items)
      ? (point.items.length + ' unique')
      : null;

    card.innerHTML =
      '<button class="inv-hist-top" type="button">' +
        '<div class="inv-hist-head-main">' +
          '<span class="when">' + formatFullDate(point.t) + '</span>' +
          '<span class="val">' + fmt(point.v) + '</span>' +
        '</div>' +
        '<div class="inv-hist-head-sub">' +
          '<span class="inv-hist-pill">' + countText + '</span>' +
          (uniqueText ? '<span class="inv-hist-pill">' + uniqueText + '</span>' : '') +
          '<span class="inv-hist-pill' + deltaClass + '">' + deltaText + '</span>' +
          '<span class="inv-hist-pill chev">Show items</span>' +
        '</div>' +
      '</button>' +
      '<div class="inv-hist-body">' +
        '<div class="inv-hist-items"></div>' +
        '<div class="inv-hist-actions"></div>' +
        '<div class="inv-hist-note"></div>' +
      '</div>';

    const itemsEl = card.querySelector('.inv-hist-items');
    const actionsEl = card.querySelector('.inv-hist-actions');
    const noteEl = card.querySelector('.inv-hist-note');
    const chev = card.querySelector('.inv-hist-pill.chev');

    if (!Array.isArray(point.items)) {{
      itemsEl.innerHTML = '<div class="inv-hist-empty">This older save only stored total value.</div>';
      noteEl.textContent = 'New saves keep the full item list.';
    }} else if (!point.items.length) {{
      itemsEl.innerHTML = '<div class="inv-hist-empty">Inventory was empty at this save.</div>';
    }} else {{
      const rows = point.items
        .map((e) => ({{ entry: e, item: byId[e.id] }}))
        .filter((r) => r.item)
        .sort((a, b) => (b.item.value * b.entry.qty) - (a.item.value * a.entry.qty));
      for (const row of rows) {{
        const line = document.createElement('div');
        line.className = 'inv-hist-row';
        const art = row.item.image
          ? '<img src="' + row.item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
          : '<div class="noimg">?</div>';
        line.innerHTML =
          art +
          '<div class="name" title="' + row.item.name + '">' + row.item.name + '</div>' +
          '<div class="detail">×' + row.entry.qty + ' · <strong>' + fmt(row.item.value * row.entry.qty) + '</strong></div>';
        itemsEl.appendChild(line);
      }}
    }}

    if (Array.isArray(point.items)) {{
      const restoreBtn = document.createElement('button');
      restoreBtn.type = 'button';
      restoreBtn.className = 'restore';
      restoreBtn.textContent = 'Restore inventory';
      restoreBtn.addEventListener('click', (e) => {{
        e.stopPropagation();
        restoreInvFromHistory(i);
      }});
      actionsEl.appendChild(restoreBtn);
    }}

    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.textContent = 'Delete save';
    delBtn.addEventListener('click', (e) => {{
      e.stopPropagation();
      if (!confirm('Delete this inventory snapshot?')) return;
      state.invHistory.splice(i, 1);
      persistInv();
      renderGraph();
      commitHistory();
    }});
    actionsEl.appendChild(delBtn);

    card.querySelector('.inv-hist-top').addEventListener('click', () => {{
      const opening = !card.classList.contains('open');
      invHistList.querySelectorAll('.inv-hist-card.open').forEach((other) => {{
        other.classList.remove('open');
        const otherChev = other.querySelector('.inv-hist-pill.chev');
        if (otherChev) otherChev.textContent = 'Show items';
      }});
      if (opening) {{
        card.classList.add('open');
        if (chev) chev.textContent = 'Hide items';
        card.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
      }} else if (chev) {{
        chev.textContent = 'Show items';
      }}
    }});

    frag.appendChild(card);
  }}
  invHistList.appendChild(frag);

  // Open the latest snapshot by default
  if (firstCard) {{
    firstCard.classList.add('open');
    const chev = firstCard.querySelector('.inv-hist-pill.chev');
    if (chev) chev.textContent = 'Hide items';
  }}
}}

function restoreInvFromHistory(index) {{
  const point = state.invHistory[index];
  if (!point || !Array.isArray(point.items)) {{
    alert('This snapshot has no item list to restore.');
    return;
  }}
  if (!confirm('Replace My Items with this snapshot from ' + formatFullDate(point.t) + '?')) return;
  state.inv = point.items
    .filter((e) => e && e.id && byId[e.id])
    .map((e) => ({{
      id: e.id,
      qty: Math.max(1, Math.min(999, parseInt(e.qty, 10) || 1)),
    }}));
  persistInv();
  render();
  commitHistory();
  setInvStatus('Restored — Save to keep', true);
  closeGraph();
}}

function renderGraph() {{
  const hist = state.invHistory;
  const pointsEl = document.getElementById('graphPoints');
  const latestEl = document.getElementById('graphLatest');
  const minEl = document.getElementById('graphMin');
  const maxEl = document.getElementById('graphMax');
  const deltaEl = document.getElementById('graphDelta');

  pointsEl.textContent = String(hist.length);
  if (hist.length < 1) {{
    latestEl.textContent = '—';
    minEl.textContent = '—';
    maxEl.textContent = '—';
    deltaEl.textContent = '—';
    deltaEl.className = 'delta';
  }}

  if (hist.length < 2) {{
    if (hist.length === 1) {{
      latestEl.textContent = fmt(hist[0].v);
      minEl.textContent = fmt(hist[0].v);
      maxEl.textContent = fmt(hist[0].v);
      deltaEl.textContent = '0';
      deltaEl.className = 'delta';
    }}
    graphChart.innerHTML = '<div class="graph-empty">Save at least twice after trades to build a graph.</div>';
  }} else {{
    const stats = mountInteractiveChart(graphChart, hist, {{
      w: 640,
      h: 220,
      showArea: true,
      showAxes: true,
    }});
    latestEl.textContent = fmt(stats.last);
    minEl.textContent = fmt(Math.min.apply(null, hist.map((p) => p.v)));
    maxEl.textContent = fmt(Math.max.apply(null, hist.map((p) => p.v)));
    const delta = stats.last - stats.first;
    deltaEl.textContent = signedFmt(delta);
    deltaEl.className = 'delta ' + (delta > 0 ? 'up' : (delta < 0 ? 'down' : ''));
  }}

  renderInvHistoryList();
}}

function openGraph() {{
  renderGraph();
  graphModal.classList.add('open');
}}

function closeGraph() {{
  graphModal.classList.remove('open');
}}

function updateInvPanel() {{
  const total = invTotal();
  const n = state.inv.reduce((s, e) => s + e.qty, 0);
  invTotalEl.textContent = fmt(total);
  invCountEl.textContent = n + (n === 1 ? ' item' : ' items');

  const hist = state.invHistory;
  const last = lastSavedValue();
  const dirty = isInvDirty();

  if (last == null) {{
    invDeltaEl.className = 'inv-delta flat';
    invDeltaEl.textContent = '—';
    invSinceEl.textContent = 'all time —';
  }} else {{
    const delta = total - last;
    const first = hist[0].v;
    const since = total - first;
    // Show live draft vs last save; all-time uses last save trail start vs current
    invDeltaEl.className = 'inv-delta ' + (delta > 0.5 ? 'up' : delta < -0.5 ? 'down' : 'flat');
    invDeltaEl.textContent = signedFmt(delta) + ' vs save';
    invSinceEl.textContent = 'all time ' + signedFmt(since);
  }}

  if (dirty) {{
    setInvStatus('Unsaved', true);
    invSaveBtn.textContent = 'Save*';
  }} else if (hist.length) {{
    setInvStatus('Saved · ' + formatShortDate(hist[hist.length - 1].t));
    invSaveBtn.textContent = 'Save';
  }} else {{
    setInvStatus('');
    invSaveBtn.textContent = 'Save';
  }}

  invList.innerHTML = '';
  if (!state.inv.length) {{
    invList.innerHTML = '<div class="inv-empty">No items yet</div>';
    renderInvDumpTips();
    persistInv();
    return;
  }}

  const sorted = state.inv
    .map((entry, index) => ({{ entry, index, item: byId[entry.id] }}))
    .filter((row) => row.item)
    .sort((a, b) => {{
      const va = a.item.value * a.entry.qty;
      const vb = b.item.value * b.entry.qty;
      if (vb !== va) return vb - va;
      return b.item.value - a.item.value;
    }});

  const frag = document.createDocumentFragment();
  for (const rowInfo of sorted) {{
    const entry = rowInfo.entry;
    const item = rowInfo.item;
    const row = document.createElement('div');
    row.className = 'inv-row';
    const art = item.image
      ? '<img src="' + item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
      : '<div class="noimg">?</div>';
    row.innerHTML =
      art +
      '<div><div class="name-line">' + itemNameHtml(item, {{
        className: 'name',
      }}) + '</div>' +
      '<div class="meta">' + fmt(item.value * entry.qty) + '</div></div>' +
      '<div class="qty">' +
        '<button type="button" data-act="dec">−</button>' +
        '<span>' + entry.qty + '</span>' +
        '<button type="button" data-act="inc">+</button>' +
      '</div>';
    row.querySelector('[data-act="inc"]').addEventListener('click', (e) => {{
      e.stopPropagation();
      entry.qty = Math.min(999, entry.qty + 1);
      render();
      commitHistory();
    }});
    row.querySelector('[data-act="dec"]').addEventListener('click', (e) => {{
      e.stopPropagation();
      if (entry.qty <= 1) {{
        const idx = state.inv.indexOf(entry);
        if (idx >= 0) state.inv.splice(idx, 1);
      }} else {{
        entry.qty -= 1;
      }}
      render();
      commitHistory();
    }});
    row.addEventListener('click', (e) => {{
      if (e.target.closest('.qty')) return;
      openDetail(item);
    }});
    frag.appendChild(row);
  }}
  invList.appendChild(frag);
  renderInvDumpTips();
  persistInv();
}}

function parseChangePct(change) {{
  if (!change || typeof change !== 'string') return 0;
  const m = change.match(/([+\\-−])\\s*([0-9]+(?:\\.[0-9]+)?)%/);
  if (!m) return 0;
  const sign = (m[1] === '-' || m[1] === '−') ? -1 : 1;
  return sign * parseFloat(m[2]);
}}

/** Absolute value delta from SV change text like "(-1,000) -2.2%". */
function parseChangeAbs(change, value, pct) {{
  if (change && typeof change === 'string') {{
    const m = change.match(/\\(([+\\-−]?\\s*[0-9][0-9,]*(?:\\.[0-9]+)?)\\)/);
    if (m) {{
      const raw = m[1].replace(/[\\s,]/g, '').replace('−', '-');
      const n = parseFloat(raw);
      if (Number.isFinite(n)) return n;
    }}
  }}
  const p = typeof pct === 'number' ? pct : parseChangePct(change);
  if (!Number.isFinite(p) || !Number.isFinite(value) || value <= 0 || p === 0) return 0;
  // Infer prior value from % change, then delta
  const prev = value / (1 + p / 100);
  return value - prev;
}}

const SUGGEST_RARITIES = new Set(['Godly', 'Ancient', 'Chroma']);

function wantScore(item) {{
  if (!item) return -99;
  const pct = parseChangePct(item.change);
  const stabMap = {{
    'Underpaid For': 3.2,
    'Doing Well': 2.6,
    'Stable': 1.0,
    'Fluctuating': 0.1,
    'Receding': -2.4,
  }};
  const stab = stabMap[item.stability] || 0;
  const dem = item.demand != null ? item.demand * 0.45 : 1.2;
  return pct * 1.35 + stab + dem;
}}

function comboValue(items) {{
  return items.reduce((sum, item) => sum + item.value, 0);
}}

function comboWant(items) {{
  if (!items.length) return -99;
  return items.reduce((sum, item) => sum + wantScore(item), 0) / items.length;
}}

function comboAvgChange(items) {{
  if (!items.length) return 0;
  return items.reduce((sum, item) => sum + parseChangePct(item.change), 0) / items.length;
}}

function pickCombos(units, k) {{
  const out = [];
  const path = [];
  function rec(start) {{
    if (path.length === k) {{
      out.push(path.slice());
      return;
    }}
    for (let i = start; i < units.length; i++) {{
      path.push(units[i]);
      rec(i + 1);
      path.pop();
    }}
  }}
  rec(0);
  return out;
}}

function namesLine(items) {{
  return items.map((item) => item.name).join(' + ');
}}

function namesRichHtml(items) {{
  return items.map((item) => itemNameHtml(item, {{
    className: 'name-piece',
  }})).join('<span class="name-sep"> + </span>');
}}

function artsHtml(items) {{
  return '<div class="suggest-arts">' + items.map((item) => (
    item.image
      ? '<img src="' + item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
      : '<div class="noimg">?</div>'
  )).join('') + '</div>';
}}

function reasonBits(gives, gets) {{
  const bits = [];
  const gAbs = gives.reduce((s, i) => s + itemChangeAbs(i), 0) / Math.max(1, gives.length);
  const tAbs = gets.reduce((s, i) => s + itemChangeAbs(i), 0) / Math.max(1, gets.length);
  if (tAbs - gAbs >= 5) {{
    bits.push('better trend (' + signedFmt(tAbs) + ' vs ' + signedFmt(gAbs) + ')');
  }} else if (tAbs > 2) {{
    bits.push('rising ' + signedFmt(tAbs) + ' avg');
  }}
  const hot = gets.filter((item) => item.stability === 'Underpaid For' || item.stability === 'Doing Well');
  if (hot.length) bits.push(hot[0].stability);
  const demG = gives.reduce((s, i) => s + (i.demand || 0), 0) / gives.length;
  const demT = gets.reduce((s, i) => s + (i.demand || 0), 0) / gets.length;
  if (demT > demG + 0.4) bits.push('higher demand');
  bits.push(gives.length + 'v' + gets.length);
  const valueDiff = comboValue(gets) - comboValue(gives);
  if (Math.abs(valueDiff) < Math.max(25, comboValue(gives) * 0.015)) bits.push('near equal value');
  else if (valueDiff > 0) bits.push('+' + fmt(valueDiff) + ' listed');
  else bits.push(signedFmt(valueDiff) + ' listed');
  return bits.slice(0, 4).join(' · ') || 'Stronger performance signals';
}}

function uniqueCount(items) {{
  return new Set(items.map((item) => item.id)).size;
}}

function stackEntries(items) {{
  const map = new Map();
  for (const item of items) {{
    const prev = map.get(item.id);
    if (prev) prev.qty += 1;
    else {{
      map.set(item.id, {{
        id: item.id,
        name: item.name,
        value: item.value,
        image: item.image,
        qty: 1,
      }});
    }}
  }}
  return Array.from(map.values());
}}

function isChromaSet(item) {{
  if (!item || item.rarity !== 'Set') return false;
  if (/^chroma\b/i.test(item.name || '')) return true;
  const members = item.members || [];
  if (members.length < 2) return false;
  return members.every((id) => byId[id] && byId[id].rarity === 'Chroma');
}}

function rarityLabel(item) {{
  if (!item) return '—';
  if (isChromaSet(item)) return 'Chroma Set';
  return item.rarity || '—';
}}

function catalogSets() {{
  if (catalogSets._cache) return catalogSets._cache;
  catalogSets._cache = CATALOG
    .filter((item) => item.members && item.members.length >= 2)
    .map((item) => ({{
      id: item.id,
      name: item.name,
      members: item.members.filter((id) => byId[id]),
    }}))
    .filter((set) => set.members.length >= 2);
  return catalogSets._cache;
}}

function inventoryQtyMap() {{
  const map = new Map();
  for (const entry of state.inv) {{
    if (!entry) continue;
    const q = Math.max(0, parseInt(entry.qty, 10) || 1);
    map.set(entry.id, (map.get(entry.id) || 0) + q);
  }}
  return map;
}}

/** Keep one complete set intact; duplicates / extras are freely tradeable. */
function setAwareInventory() {{
  const owned = inventoryQtyMap();
  const reserved = new Map();
  const intactBundles = [];
  for (const set of catalogSets()) {{
    let complete = Infinity;
    for (const id of set.members) {{
      complete = Math.min(complete, owned.get(id) || 0);
    }}
    if (!Number.isFinite(complete) || complete < 1) continue;
    for (const id of set.members) {{
      reserved.set(id, (reserved.get(id) || 0) + complete);
    }}
    intactBundles.push({{
      setId: set.id,
      name: set.name,
      members: set.members.slice(),
      items: set.members.map((id) => byId[id]),
      count: complete,
    }});
  }}
  const tradeable = new Map();
  for (const [id, qty] of owned) {{
    const free = qty - (reserved.get(id) || 0);
    if (free > 0) tradeable.set(id, free);
  }}
  return {{ owned, reserved, tradeable, intactBundles }};
}}

function offerBreakOpts() {{
  return {{ allowBreakSets: !state.avoidSetBreaks }};
}}

function persistSetProtect() {{
  try {{
    localStorage.setItem(SET_PROTECT_KEY, state.avoidSetBreaks ? '1' : '0');
  }} catch (_) {{}}
}}

function loadSetProtect() {{
  try {{
    const raw = localStorage.getItem(SET_PROTECT_KEY);
    if (raw === '0') state.avoidSetBreaks = false;
    else if (raw === '1') state.avoidSetBreaks = true;
  }} catch (_) {{}}
  const el = document.getElementById('avoidSetBreaks');
  if (el) el.checked = !!state.avoidSetBreaks;
}}

function persistAutoTargetHot() {{
  try {{
    localStorage.setItem(AUTO_HOT_KEY, state.autoTargetHot ? '1' : '0');
  }} catch (_) {{}}
}}

function loadAutoTargetHot() {{
  try {{
    const raw = localStorage.getItem(AUTO_HOT_KEY);
    if (raw === '1') state.autoTargetHot = true;
    else if (raw === '0') state.autoTargetHot = false;
  }} catch (_) {{}}
  const el = document.getElementById('autoTargetHot');
  if (el) el.checked = !!state.autoTargetHot;
}}

/** Hot trending or clearly rising elite items — used as soft receive targets. */
function isHotRisingTarget(item) {{
  if (!item || !SUGGEST_RARITIES.has(item.rarity) || item.value < 1) return false;
  if (itemDropSignal(item)) return false;
  if (itemIsHot(item)) return true;
  const pct = itemChangePct(item);
  if (pct >= 1.5) return true;
  if (historyRiseScore(item) >= 3.5) return true;
  const stab = item.stability;
  if ((stab === 'Doing Well' || stab === 'Underpaid For') && pct > 0.4) return true;
  return false;
}}

function autoHotRisingTargets() {{
  return CATALOG
    .filter(isHotRisingTarget)
    .sort((a, b) => {{
      const sa = (itemIsHot(a) ? 5 : 0) + historyRiseScore(a) + itemChangePct(a) * 0.8;
      const sb = (itemIsHot(b) ? 5 : 0) + historyRiseScore(b) + itemChangePct(b) * 0.8;
      return sb - sa || wantScore(b) - wantScore(a) || b.value - a.value;
    }})
    .slice(0, 10);
}}

function buildSuggestions() {{
  const protect = setAwareInventory();
  const bag = [];
  const qtyMap = state.avoidSetBreaks ? protect.tradeable : protect.owned;
  // Prefer duplicates / extras so we don't orphan a complete set (unless toggle allows breaks)
  for (const [id, qty] of qtyMap) {{
    const item = byId[id];
    if (!item || !SUGGEST_RARITIES.has(item.rarity)) continue;
    const copies = Math.min(qty, 3);
    for (let i = 0; i < copies; i++) bag.push(item);
  }}
  // Whole sets are fine to suggest as a unit (not breaking)
  const setGiveCombos = [];
  if (state.avoidSetBreaks) {{
    for (const b of protect.intactBundles) {{
      if (b.members.length > SLOTS) continue;
      if (!b.items.every((item) => SUGGEST_RARITIES.has(item.rarity))) continue;
      setGiveCombos.push(b.items.slice());
    }}
  }}
  if (!bag.length && !setGiveCombos.length) return [];

  bag.sort((a, b) => b.value - a.value);
  const units = bag.slice(0, 14);

  const targetUnits = [];
  const targetSeen = new Set();
  let manualTargetCount = 0;
  for (const entry of state.targets) {{
    if (!entry) continue;
    const item = byId[entry.id];
    if (!item || !SUGGEST_RARITIES.has(item.rarity)) continue;
    const copies = Math.min(entry.qty || 1, 2);
    for (let i = 0; i < copies; i++) targetUnits.push(item);
    targetSeen.add(item.id);
    manualTargetCount += 1;
  }}
  if (state.autoTargetHot) {{
    for (const item of autoHotRisingTargets()) {{
      if (targetSeen.has(item.id)) continue;
      targetUnits.push(item);
      targetSeen.add(item.id);
    }}
  }}
  const hasTargets = targetUnits.length > 0;

  const poolAll = CATALOG.filter((item) => (
    SUGGEST_RARITIES.has(item.rarity) && item.value >= 1
  )).sort((a, b) => wantScore(b) - wantScore(a));
  const fillers = poolAll.slice(0, 28);

  const getCombos = [];
  if (hasTargets) {{
    // Manual targets can fill more slots; auto-only stays leaner for speed
    const maxTs = manualTargetCount > 0
      ? Math.min(4, targetUnits.length)
      : Math.min(2, targetUnits.length);
    for (let ts = 1; ts <= maxTs; ts++) {{
      for (const core of pickCombos(targetUnits, ts)) {{
        if (uniqueCount(core) > SLOTS) continue;
        getCombos.push(core.slice());
        const room = SLOTS - uniqueCount(core);
        if (room >= 1) {{
          for (const fill of fillers) {{
            if (core.some((item) => item.id === fill.id)) continue;
            const mixed = core.concat([fill]);
            if (uniqueCount(mixed) <= SLOTS) getCombos.push(mixed);
          }}
        }}
        if (room >= 2) {{
          for (const pair of pickCombos(fillers.slice(0, 16), 2)) {{
            if (pair.some((item) => core.some((c) => c.id === item.id))) continue;
            const mixed = core.concat(pair);
            if (uniqueCount(mixed) <= SLOTS) getCombos.push(mixed);
          }}
        }}
      }}
    }}
  }} else {{
    const pool1 = poolAll.slice(0, 80);
    const pool2 = poolAll.slice(0, 32);
    const pool3 = poolAll.slice(0, 20);
    const pool4 = poolAll.slice(0, 14);
    for (const item of pool1) getCombos.push([item]);
    for (const combo of pickCombos(pool2, 2)) getCombos.push(combo);
    for (const combo of pickCombos(pool3, 3)) getCombos.push(combo);
    for (const combo of pickCombos(pool4, 4)) getCombos.push(combo);
  }}

  const ideas = [];
  const giveCombosAll = [];
  for (let gs = 1; gs <= SLOTS; gs++) {{
    if (!units.length) break;
    for (const gives of pickCombos(units, gs)) {{
      if (uniqueCount(gives) > SLOTS) continue;
      giveCombosAll.push(gives);
    }}
  }}
  for (const gives of setGiveCombos) {{
    if (uniqueCount(gives) > SLOTS) continue;
    giveCombosAll.push(gives);
  }}

  for (const gives of giveCombosAll) {{
      if (uniqueCount(gives) > SLOTS) continue;
      const gv = comboValue(gives);
      if (gv < 1) continue;
      const giveIds = new Set(gives.map((item) => item.id));
      const giveWant = comboWant(gives);
      let best = null;
      for (const gets of getCombos) {{
        if (uniqueCount(gets) > SLOTS) continue;
        // Multi-item trades only (skip pure 1v1) unless aiming at a target
        if (gives.length === 1 && gets.length === 1 && !hasTargets) continue;
        if (gets.some((item) => giveIds.has(item.id))) continue;
        if (hasTargets && gives.some((item) => targetUnits.some((t) => t.id === item.id))) continue;
        const tv = comboValue(gets);
        const valueDiff = tv - gv;
        const ratio = tv / gv;
        const maxUnder = Math.min(gv * 0.015, 200);
        if (valueDiff < -maxUnder) continue;
        if (ratio > 1.12) continue;
        const getWant = comboWant(gets);
        const edge = getWant - giveWant;
        const minEdge = hasTargets ? 0.15 : 0.85;
        if (edge < minEdge && !(hasTargets && valueDiff >= 0 && edge > -0.5)) continue;
        if (!hasTargets && giveWant >= 4.8 && edge < 1.6) continue;
        const valueSlack = valueDiff / gv;
        const targetHits = hasTargets
          ? gets.filter((item) => targetUnits.some((t) => t.id === item.id)).length
          : 0;
        const hotHits = gets.filter((item) => itemIsHot(item) || isHotRisingTarget(item)).length;
        const targetBonus = hasTargets ? targetHits * 2.8 + (targetHits === uniqueCount(gets) ? 1.2 : 0) : 0;
        const hotBonus = state.autoTargetHot ? hotHits * 0.55 : hotHits * 0.15;
        const multiBonus = (uniqueCount(gives) + uniqueCount(gets) >= 3) ? 0.35 : 0.15;
        const fairBonus = valueDiff >= 0 ? 1.25 : -0.8;
        const score = edge * 2.3 + valueSlack * 8 + multiBonus + fairBonus + targetBonus + hotBonus + (uniqueCount(gets) > 1 ? 0.2 : 0);
        if (!best || score > best.score) {{
          best = {{ gives: gives.slice(), gets: gets.slice(), score, edge, gv, tv, targetHits, hotHits }};
        }}
      }}
      if (best) ideas.push(best);
  }}

  ideas.sort((a, b) => b.score - a.score);
  const used = new Set();
  const giveUses = new Map();
  const getUses = new Map();
  const out = [];
  for (const idea of ideas) {{
    const key = idea.gives.map((i) => i.id).sort().join('+') + '>' + idea.gets.map((i) => i.id).sort().join('+');
    if (used.has(key)) continue;
    const giveKey = idea.gives.map((i) => i.id).sort().join('+');
    const getKey = idea.gets.map((i) => i.id).sort().join('+');
    if ((giveUses.get(giveKey) || 0) >= 2) continue;
    if ((getUses.get(getKey) || 0) >= 2) continue;
    used.add(key);
    giveUses.set(giveKey, (giveUses.get(giveKey) || 0) + 1);
    getUses.set(getKey, (getUses.get(getKey) || 0) + 1);
    out.push(idea);
    if (out.length >= 16) break;
  }}
  return out;
}}

/** Suggest dumping dropping inventory items for stabler / rising packages. */
function buildDumpTradeIdeas() {{
  const protect = setAwareInventory();
  const dumpUnits = [];
  const dumpSeen = new Set();
  const pickedIds = new Set();

  for (const entry of state.dumpList) {{
    const item = byId[entry.id];
    if (!item || !SUGGEST_RARITIES.has(item.rarity) || item.value < 1) continue;
    const free = protect.tradeable.get(entry.id) || 0;
    const total = protect.owned.get(entry.id) || 0;
    const wantQty = Math.max(1, Math.min(9, entry.qty || 1));
    let copies;
    if (total > 0) {{
      const avail = state.avoidSetBreaks ? free : total;
      if (avail < 1) continue;
      copies = Math.min(avail, wantQty, 2);
    }} else {{
      copies = Math.min(wantQty, 2);
    }}
    const sig = itemDropSignal(item);
    for (let i = 0; i < copies; i++) dumpUnits.push({{ item, sig, picked: true }});
    dumpSeen.add(entry.id);
    pickedIds.add(entry.id);
  }}

  const autoQtyMap = state.avoidSetBreaks ? protect.tradeable : protect.owned;
  for (const [id, qty] of autoQtyMap) {{
    if (dumpSeen.has(id)) continue;
    const item = byId[id];
    if (!item || !SUGGEST_RARITIES.has(item.rarity) || item.value < 1) continue;
    const sig = itemDropSignal(item);
    if (!sig) continue;
    const copies = Math.min(qty, 2);
    for (let i = 0; i < copies; i++) dumpUnits.push({{ item, sig, picked: false }});
    dumpSeen.add(id);
  }}
  if (!dumpUnits.length) return [];

  dumpUnits.sort((a, b) => {{
    const sa = a.sig ? a.sig.score : (a.picked ? 2.5 : 0);
    const sb = b.sig ? b.sig.score : (b.picked ? 2.5 : 0);
    return sb - sa || (b.picked ? 1 : 0) - (a.picked ? 1 : 0) || b.item.value - a.item.value;
  }});
  const dumpItems = dumpUnits.map((row) => row.item).slice(0, 8);

  const receivePool = CATALOG.filter((item) => {{
    if (!SUGGEST_RARITIES.has(item.rarity) || item.value < 1) return false;
    if (itemDropSignal(item)) return false;
    const pct = itemChangePct(item);
    const stab = item.stability;
    const rising = pct > 0.2 || itemIsHot(item);
    const solid = stab === 'Doing Well' || stab === 'Underpaid For' || stab === 'Stable';
    return rising || solid || wantScore(item) >= 2;
  }}).sort((a, b) => wantScore(b) - wantScore(a) || b.value - a.value);

  const getCombos = [];
  const pool1 = receivePool.slice(0, 60);
  const pool2 = receivePool.slice(0, 24);
  const pool3 = receivePool.slice(0, 14);
  for (const item of pool1) getCombos.push([item]);
  for (const combo of pickCombos(pool2, 2)) getCombos.push(combo);
  for (const combo of pickCombos(pool3, 3)) getCombos.push(combo);

  const giveCombos = [];
  for (let gs = 1; gs <= Math.min(SLOTS, dumpItems.length); gs++) {{
    for (const gives of pickCombos(dumpItems, gs)) {{
      if (uniqueCount(gives) > SLOTS) continue;
      giveCombos.push(gives);
    }}
  }}

  const ideas = [];
  for (const gives of giveCombos) {{
    const gv = comboValue(gives);
    if (gv < 1) continue;
    const giveIds = new Set(gives.map((item) => item.id));
    const dumpScore = gives.reduce((s, item) => {{
      const sig = itemDropSignal(item);
      if (sig) return s + sig.score;
      if (pickedIds.has(item.id)) return s + 2.5;
      return s;
    }}, 0);
    let best = null;
    for (const gets of getCombos) {{
      if (uniqueCount(gets) > SLOTS) continue;
      if (gets.some((item) => giveIds.has(item.id))) continue;
      const tv = comboValue(gets);
      const valueDiff = tv - gv;
      if (valueDiff < -Math.min(gv * 0.02, 150)) continue;
      if (tv / gv > 1.14) continue;
      const getWant = comboWant(gets);
      const giveWant = comboWant(gives);
      const edge = getWant - giveWant;
      if (edge < 0.4 && valueDiff < 0) continue;
      const score = dumpScore * 1.4 + edge * 2 + (valueDiff / gv) * 6 + (valueDiff >= 0 ? 1.5 : 0);
      if (!best || score > best.score) {{
        best = {{
          gives: gives.slice(),
          gets: gets.slice(),
          score,
          gv,
          tv,
          dump: true,
          dumpWhy: gives.map((item) => {{
            const sig = itemDropSignal(item);
            if (sig) return sig.why;
            if (pickedIds.has(item.id)) return 'you chose to trade off';
            return '';
          }}).filter(Boolean).slice(0, 2).join(' · '),
        }};
      }}
    }}
    if (best) ideas.push(best);
  }}

  ideas.sort((a, b) => b.score - a.score);
  const used = new Set();
  const out = [];
  for (const idea of ideas) {{
    const key = idea.gives.map((i) => i.id).sort().join('+') + '>' + idea.gets.map((i) => i.id).sort().join('+');
    if (used.has(key)) continue;
    const giveKey = idea.gives.map((i) => i.id).sort().join('+');
    if (used.has('g:' + giveKey)) continue;
    used.add(key);
    used.add('g:' + giveKey);
    out.push(idea);
    if (out.length >= 10) break;
  }}
  return out;
}}

function applySuggestion(gives, gets) {{
  state.your = Array(SLOTS).fill(null);
  state.their = Array(SLOTS).fill(null);
  stackEntries(gives).slice(0, SLOTS).forEach((entry, i) => {{
    entry._enter = true;
    state.your[i] = entry;
  }});
  stackEntries(gets).slice(0, SLOTS).forEach((entry, i) => {{
    entry._enter = true;
    state.their[i] = entry;
  }});
  state.lowerCycle = null;
  state.higherCycle = null;
  renderTradeOnly();
  window.scrollTo({{ top: 0, behavior: 'smooth' }});
}}

function updateGenOfferBtn() {{
  const yoursHas = state.your.some(Boolean);
  const theirsHas = state.their.some(Boolean);
  genOfferBtn.hidden = !( !yoursHas && theirsHas );
  genReceiveBtn.hidden = !( yoursHas && !theirsHas );
  lowerOfferBtn.hidden = !( yoursHas && theirsHas );
  higherOfferBtn.hidden = !( yoursHas && theirsHas );
  completeOfferBtn.hidden = !( yoursHas && theirsHas );
}}

function applyCompletedTrade() {{
  const giving = state.your.filter(Boolean);
  const getting = state.their.filter(Boolean);
  if (!giving.length || !getting.length) {{
    alert('Fill both Your Offer and Their Offer first.');
    return;
  }}

  const need = new Map();
  for (const entry of giving) {{
    need.set(entry.id, (need.get(entry.id) || 0) + (entry.qty || 1));
  }}

  const missing = [];
  for (const [id, qty] of need) {{
    const have = state.inv.find((e) => e.id === id);
    const owned = have ? have.qty : 0;
    if (owned < qty) {{
      const item = byId[id];
      missing.push((item ? item.name : id) + ' (need ' + qty + ', have ' + owned + ')');
    }}
  }}
  if (missing.length) {{
    alert("My Items is short on what you're giving:\\n" + missing.join('\\n'));
    return;
  }}

  const giveNames = giving.map((e) => (e.qty > 1 ? e.qty + '× ' : '') + e.name).join(', ');
  const getNames = getting.map((e) => (e.qty > 1 ? e.qty + '× ' : '') + e.name).join(', ');
  if (!confirm(
    'Apply this trade to My Items?\\n\\n' +
    'Remove: ' + giveNames + '\\n' +
    'Add: ' + getNames + '\\n\\n' +
    'Boards will clear, value will be saved, and the trade goes to Trade History.'
  )) return;

  pushTradeHistoryEntry();

  for (const [id, qty] of need) {{
    const entry = state.inv.find((e) => e.id === id);
    if (!entry) continue;
    entry.qty -= qty;
    if (entry.qty <= 0) {{
      const idx = state.inv.indexOf(entry);
      if (idx >= 0) state.inv.splice(idx, 1);
    }}
  }}

  for (const entry of getting) {{
    const q = entry.qty || 1;
    const existing = state.inv.find((e) => e.id === entry.id);
    if (existing) existing.qty = Math.min(999, existing.qty + q);
    else state.inv.push({{ id: entry.id, qty: q }});
  }}

  // Drop targets you just obtained
  for (const entry of getting) {{
    const t = state.targets.find((e) => e.id === entry.id);
    if (!t) continue;
    t.qty -= (entry.qty || 1);
    if (t.qty <= 0) state.targets = state.targets.filter((e) => e.id !== entry.id);
  }}

  state.your = Array(SLOTS).fill(null);
  state.their = Array(SLOTS).fill(null);
  state.lowerCycle = null;
  state.higherCycle = null;

  const total = invTotal();
  const last = lastSavedValue();
  const sameValue = last != null && Math.abs(last - total) < 0.5;
  const sameItems = state.invHistory.length
    && invItemsKey(state.invHistory[state.invHistory.length - 1].items) === currentInvItemsKey();
  if (!sameValue || !sameItems) {{
    pushInvHistoryPoint(total);
  }}
  persistInv();
  persistTargets();
  syncInferredTradesFromInvHistory();
  render();
  commitHistory();
  setInvStatus('Trade applied · saved ' + new Date().toLocaleString());
}}

function inventoryOfferPool(excludeIds, opts) {{
  const allowBreak = !!(opts && opts.allowBreakSets);
  const protect = setAwareInventory();
  const qtyMap = allowBreak ? protect.owned : protect.tradeable;
  const pool = [];
  for (const [id, maxQty] of qtyMap) {{
    if (maxQty < 1) continue;
    const item = byId[id];
    if (!item || item.value < 1) continue;
    if (excludeIds && excludeIds.has(item.id)) continue;
    pool.push({{
      kind: 'item',
      item: item,
      maxQty: Math.max(1, Math.min(99, maxQty)),
    }});
  }}
  pool.sort((a, b) => b.item.value - a.item.value);
  return {{ pool: pool.slice(0, 14), protect }};
}}

function expandStackedCombo(picked) {{
  // picked: [{{item, qty}}, ...]
  const units = [];
  for (const row of picked) {{
    for (let i = 0; i < row.qty; i++) units.push(row.item);
  }}
  return units;
}}

function offerComboKey(combo) {{
  return stackEntries(combo)
    .map((e) => e.id + ':' + e.qty)
    .sort()
    .join('|');
}}

function currentYourComboKey() {{
  return state.your
    .filter(Boolean)
    .map((e) => e.id + ':' + e.qty)
    .sort()
    .join('|');
}}

function theirSideKey() {{
  return state.their
    .filter(Boolean)
    .map((e) => e.id + ':' + e.qty)
    .sort()
    .join('|');
}}

function collectOfferCombos(filterFn, opts) {{
  const allowBreak = !!(opts && opts.allowBreakSets);
  const theirIds = new Set(state.their.filter(Boolean).map((e) => e.id));
  const {{ pool, protect }} = inventoryOfferPool(theirIds, {{ allowBreakSets: allowBreak }});
  const out = [];
  const seen = new Set();

  function pushCombo(combo) {{
    const v = comboValue(combo);
    if (v < 1) return;
    if (filterFn && !filterFn(combo, v)) return;
    const key = offerComboKey(combo);
    if (seen.has(key)) return;
    seen.add(key);
    out.push({{
      combo: combo.slice(),
      v: v,
      want: comboWant(combo),
      key: key,
    }});
  }}

  function enumeratePool(itemPool, basePicked, slotsUsed) {{
    const room = SLOTS - slotsUsed;
    if (room < 1 && !basePicked.length) return;
    if (basePicked.length) pushCombo(expandStackedCombo(basePicked));
    if (room < 1 || !itemPool.length) return;
    for (let k = 1; k <= room; k++) {{
      for (const chosen of pickCombos(itemPool, k)) {{
        const picked = basePicked.slice();
        function walk(idx) {{
          if (idx === chosen.length) {{
            pushCombo(expandStackedCombo(picked));
            return;
          }}
          const row = chosen[idx];
          const maxQ = Math.min(row.maxQty, k === 1 && !basePicked.length ? 30 : k === 2 ? 16 : 10);
          for (let q = 1; q <= maxQ; q++) {{
            picked.push({{ item: row.item, qty: q }});
            walk(idx + 1);
            picked.pop();
          }}
        }}
        walk(0);
      }}
    }}
  }}

  // 4 unique item types max; stacks share a slot. Prefer extras so sets stay intact.
  enumeratePool(pool, [], 0);

  // Trading a whole set is OK (not breaking it) — include intact set ± loose fillers
  if (!allowBreak) {{
    for (const b of protect.intactBundles) {{
      if (b.members.length > SLOTS) continue;
      if (b.members.some((id) => theirIds.has(id))) continue;
      const maxSets = Math.min(b.count, 2);
      for (let n = 1; n <= maxSets; n++) {{
        const base = b.items.map((item) => ({{ item, qty: n }}));
        const leftover = [];
        for (const row of pool) {{
          if (b.members.includes(row.item.id)) continue;
          leftover.push(row);
        }}
        // Also allow stacking more of set members from true extras beyond this bundle use
        for (const id of b.members) {{
          const ownedQ = protect.owned.get(id) || 0;
          const extra = ownedQ - n;
          if (extra > 0) {{
            const slot = base.find((r) => r.item.id === id);
            if (slot) slot._extraMax = Math.min(extra, n === 1 ? 8 : 4);
          }}
        }}
        // Enumerate extra stacks on set members, then fillers
        function walkSetExtras(idx, picked) {{
          if (idx === base.length) {{
            enumeratePool(leftover, picked, b.members.length);
            return;
          }}
          const row = base[idx];
          const extraMax = row._extraMax || 0;
          for (let add = 0; add <= extraMax; add++) {{
            picked.push({{ item: row.item, qty: row.qty + add }});
            walkSetExtras(idx + 1, picked);
            picked.pop();
          }}
        }}
        walkSetExtras(0, []);
      }}
    }}
  }}

  return out;
}}

function applyYourOfferCombo(combo) {{
  state.your = Array(SLOTS).fill(null);
  stackEntries(combo).slice(0, SLOTS).forEach((entry, i) => {{
    entry._enter = true;
    state.your[i] = entry;
  }});
  renderTradeOnly();
}}

function applyTheirOfferCombo(combo) {{
  state.their = Array(SLOTS).fill(null);
  stackEntries(combo).slice(0, SLOTS).forEach((entry, i) => {{
    entry._enter = true;
    state.their[i] = entry;
  }});
  renderTradeOnly();
}}

/** Build catalog receive packages near a target value (for when only Your Offer is filled). */
function collectReceiveCombos(targetValue, excludeIds) {{
  const out = [];
  const seen = new Set();
  const poolAll = CATALOG.filter((item) => (
    SUGGEST_RARITIES.has(item.rarity)
    && item.value >= 1
    && item.value <= targetValue * 1.15
    && !excludeIds.has(item.id)
  )).sort((a, b) => wantScore(b) - wantScore(a) || b.value - a.value);

  const targetUnits = [];
  for (const entry of state.targets) {{
    if (!entry) continue;
    const item = byId[entry.id];
    if (!item || !SUGGEST_RARITIES.has(item.rarity)) continue;
    if (excludeIds.has(item.id)) continue;
    if (item.value > targetValue * 1.15) continue;
    const copies = Math.min(entry.qty || 1, 2);
    for (let i = 0; i < copies; i++) targetUnits.push(item);
  }}

  const getCombos = [];
  if (targetUnits.length) {{
    for (let ts = 1; ts <= Math.min(SLOTS, targetUnits.length); ts++) {{
      for (const core of pickCombos(targetUnits, ts)) {{
        if (uniqueCount(core) > SLOTS) continue;
        getCombos.push(core.slice());
        const room = SLOTS - uniqueCount(core);
        const fillers = poolAll.slice(0, 20);
        if (room >= 1) {{
          for (const fill of fillers) {{
            if (core.some((item) => item.id === fill.id)) continue;
            const mixed = core.concat([fill]);
            if (uniqueCount(mixed) <= SLOTS) getCombos.push(mixed);
          }}
        }}
        if (room >= 2) {{
          for (const pair of pickCombos(fillers.slice(0, 12), 2)) {{
            if (pair.some((item) => core.some((c) => c.id === item.id))) continue;
            const mixed = core.concat(pair);
            if (uniqueCount(mixed) <= SLOTS) getCombos.push(mixed);
          }}
        }}
      }}
    }}
  }}
  const pool1 = poolAll.slice(0, 80);
  const pool2 = poolAll.slice(0, 32);
  const pool3 = poolAll.slice(0, 18);
  const pool4 = poolAll.slice(0, 12);
  for (const item of pool1) getCombos.push([item]);
  for (const combo of pickCombos(pool2, 2)) getCombos.push(combo);
  for (const combo of pickCombos(pool3, 3)) getCombos.push(combo);
  for (const combo of pickCombos(pool4, 4)) getCombos.push(combo);

  // Intact chroma/godly sets as receive packages
  for (const set of catalogSets()) {{
    if (set.members.length > SLOTS) continue;
    const parts = set.members.map((id) => byId[id]).filter(Boolean);
    if (parts.length < 2) continue;
    if (!parts.every((item) => SUGGEST_RARITIES.has(item.rarity))) continue;
    if (parts.some((item) => excludeIds.has(item.id))) continue;
    getCombos.push(parts);
  }}

  for (const gets of getCombos) {{
    if (uniqueCount(gets) > SLOTS) continue;
    const v = comboValue(gets);
    if (v < 1) continue;
    const key = gets.map((item) => item.id).sort().join('|') + '#' + v;
    if (seen.has(key)) continue;
    seen.add(key);
    const hasTarget = gets.some((item) => state.targets.some((t) => t && t.id === item.id));
    out.push({{
      combo: gets,
      v,
      want: comboWant(gets),
      hasTarget,
      key,
    }});
  }}
  return out;
}}

function generateReceiveFromYours() {{
  const yourValue = sideTotal('your');
  if (yourValue <= 0 || !state.your.some(Boolean)) {{
    alert('Add items to Your Offer first.');
    return;
  }}
  if (state.their.some(Boolean)) {{
    alert('Clear Their Offer first.');
    return;
  }}

  const excludeIds = new Set(state.your.filter(Boolean).map((e) => e.id));
  const all = collectReceiveCombos(yourValue, excludeIds);
  if (!all.length) {{
    alert('No receive packages found near this value.');
    return;
  }}

  // Good trade for you: near equal to slightly over what you give
  const minFair = yourValue * 0.97;
  const maxFair = yourValue * 1.08;
  let pool = all.filter((row) => row.v >= minFair && row.v <= maxFair);
  if (!pool.length) {{
    pool = all.filter((row) => row.v >= yourValue * 0.9 && row.v <= yourValue * 1.12);
  }}
  if (!pool.length) pool = all.slice();

  pool.sort((a, b) => {{
    // Prefer target hits, then closest value (slightly over yours), then want score
    if (a.hasTarget !== b.hasTarget) return a.hasTarget ? -1 : 1;
    const da = Math.abs(a.v - yourValue * 1.02);
    const db = Math.abs(b.v - yourValue * 1.02);
    if (Math.abs(da - db) > 0.5) return da - db;
    if (b.want !== a.want) return b.want - a.want;
    return b.v - a.v;
  }});

  state.lowerCycle = null;
  state.higherCycle = null;
  applyTheirOfferCombo(pool[0].combo);
}}

function generateOfferAgainstTheir() {{
  const theirValue = sideTotal('their');
  if (theirValue <= 0 || !state.their.some(Boolean)) {{
    alert('Add items to Their Offer first.');
    return;
  }}
  if (state.your.some(Boolean)) {{
    alert('Clear Your Offer first.');
    return;
  }}
  if (!state.inv.length) {{
    alert('Add items to My Items so an offer can be built.');
    return;
  }}

  const maxFair = theirValue * 1.12;
  const breakOpts = offerBreakOpts();

  let all = collectOfferCombos((combo, v) => v <= maxFair, breakOpts);
  if (!all.length && !state.avoidSetBreaks) {{
    all = collectOfferCombos((combo, v) => v <= maxFair, {{ allowBreakSets: true }});
  }}
  if (!all.length) {{
    let fallback = collectOfferCombos(null, breakOpts);
    if (!fallback.length && !state.avoidSetBreaks) {{
      fallback = collectOfferCombos(null, {{ allowBreakSets: true }});
    }}
    if (!fallback.length) {{
      alert(state.avoidSetBreaks
        ? 'No offer combos without breaking a set. Turn off “Avoid set breaks” to unlock set pieces.'
        : 'No offer combos available from My Items.');
      return;
    }}
    fallback.sort((a, b) => {{
      const da = Math.abs(a.v - theirValue);
      const db = Math.abs(b.v - theirValue);
      if (da !== db) return da - db;
      return b.v - a.v;
    }});
    state.lowerCycle = null;
    state.higherCycle = null;
    applyYourOfferCombo(fallback[0].combo);
    return;
  }}

  // Prefer fair/near offers first; if all are under, still use the best (highest) you can give
  const minFair = theirValue * 0.97;
  const fair = all.filter((row) => row.v >= minFair);
  const pool = fair.length ? fair : all;

  pool.sort((a, b) => {{
    if (b.v !== a.v) return b.v - a.v;
    return b.want - a.want;
  }});

  state.lowerCycle = null;
  state.higherCycle = null;
  applyYourOfferCombo(pool[0].combo);
}}

function rebuildLowerCycle(theirValue, yourValue) {{
  const minKeep = theirValue * 0.72; // don't go absurdly low
  const filterFn = (combo, v) => {{
    if (v >= yourValue - 0.5) return false;
    if (v < minKeep) return false;
    if (v > theirValue * 1.01) return false;
    return true;
  }};
  let list = collectOfferCombos(filterFn, offerBreakOpts());
  if (!list.length && !state.avoidSetBreaks) {{
    list = collectOfferCombos(filterFn, {{ allowBreakSets: true }});
  }}
  // Highest remaining value first, then step down through every trade
  list.sort((a, b) => {{
    if (b.v !== a.v) return b.v - a.v;
    return b.want - a.want;
  }});
  state.lowerCycle = {{
    theirKey: theirSideKey(),
    baseYour: yourValue,
    list: list,
    index: 0,
  }};
  return state.lowerCycle;
}}

function generateLowerOffer() {{
  const theirValue = sideTotal('their');
  const yourValue = sideTotal('your');
  if (theirValue <= 0 || !state.their.some(Boolean)) {{
    alert('Add items to Their Offer first.');
    return;
  }}
  if (!state.your.some(Boolean)) {{
    alert('Generate an offer first.');
    return;
  }}
  if (!state.inv.length) {{
    alert('Add items to My Items so an offer can be built.');
    return;
  }}

  const theirKey = theirSideKey();
  let cycle = state.lowerCycle;
  if (!cycle || cycle.theirKey !== theirKey || Math.abs(cycle.baseYour - yourValue) > 0.5) {{
    cycle = rebuildLowerCycle(theirValue, yourValue);
  }}

  if (!cycle.list.length) {{
    alert(state.avoidSetBreaks
      ? 'No lower offers without breaking a set. Turn off “Avoid set breaks” to unlock set pieces.'
      : 'No lower offers available from My Items.');
    state.lowerCycle = null;
    return;
  }}

  const currentKey = currentYourComboKey();
  // Walk every remaining trade in order
  while (cycle.index < cycle.list.length) {{
    const next = cycle.list[cycle.index++];
    if (next.key === currentKey) continue;
    if (next.v >= yourValue - 0.5) continue;
    applyYourOfferCombo(next.combo);
    state.higherCycle = null;
    state.lowerCycle = {{
      theirKey: theirKey,
      baseYour: next.v,
      list: cycle.list.filter((row) => row.v < next.v - 0.5),
      index: 0,
    }};
    return;
  }}

  alert('Cycled through every lower offer.');
  state.lowerCycle = null;
}}

function rebuildHigherCycle(theirValue, yourValue) {{
  const maxPay = theirValue * 1.18;
  const filterFn = (combo, v) => {{
    if (v <= yourValue + 0.5) return false;
    if (v > maxPay) return false;
    return true;
  }};
  let list = collectOfferCombos(filterFn, offerBreakOpts());
  if (!list.length && !state.avoidSetBreaks) {{
    list = collectOfferCombos(filterFn, {{ allowBreakSets: true }});
  }}
  // Cheapest upgrade first, then step up
  list.sort((a, b) => {{
    if (a.v !== b.v) return a.v - b.v;
    return b.want - a.want;
  }});
  state.higherCycle = {{
    theirKey: theirSideKey(),
    baseYour: yourValue,
    list: list,
    index: 0,
  }};
  return state.higherCycle;
}}

function generateHigherOffer() {{
  const theirValue = sideTotal('their');
  const yourValue = sideTotal('your');
  if (theirValue <= 0 || !state.their.some(Boolean)) {{
    alert('Add items to Their Offer first.');
    return;
  }}
  if (!state.your.some(Boolean)) {{
    alert('Generate an offer first.');
    return;
  }}
  if (!state.inv.length) {{
    alert('Add items to My Items so an offer can be built.');
    return;
  }}

  const theirKey = theirSideKey();
  let cycle = state.higherCycle;
  if (!cycle || cycle.theirKey !== theirKey || Math.abs(cycle.baseYour - yourValue) > 0.5) {{
    cycle = rebuildHigherCycle(theirValue, yourValue);
  }}

  if (!cycle.list.length) {{
    alert(state.avoidSetBreaks
      ? 'No higher offers without breaking a set. Turn off “Avoid set breaks” to unlock set pieces.'
      : 'No higher offers available from My Items.');
    state.higherCycle = null;
    return;
  }}

  const currentKey = currentYourComboKey();
  while (cycle.index < cycle.list.length) {{
    const next = cycle.list[cycle.index++];
    if (next.key === currentKey) continue;
    if (next.v <= yourValue + 0.5) continue;
    applyYourOfferCombo(next.combo);
    state.lowerCycle = null;
    state.higherCycle = {{
      theirKey: theirKey,
      baseYour: next.v,
      list: cycle.list.filter((row) => row.v > next.v + 0.5),
      index: 0,
    }};
    return;
  }}

  alert('Cycled through every higher offer.');
  state.higherCycle = null;
}}

function renderSuggestCard(idea, opts) {{
  opts = opts || {{}};
  const gives = idea.gives;
  const gets = idea.gets;
  const card = document.createElement('div');
  card.className = 'suggest-card' + (opts.dump ? ' dump' : '');
  const targetNote = idea.targetHits
    ? ' · includes ' + idea.targetHits + ' target' + (idea.targetHits > 1 ? 's' : '')
    : (idea.hotHits
      ? ' · ' + idea.hotHits + ' hot/rising'
      : '');
  const whyExtra = opts.dump && idea.dumpWhy
    ? 'Dump: ' + idea.dumpWhy + ' · '
    : (!opts.dump && state.autoTargetHot && idea.targetHits
      ? 'Hot/rising aim · '
      : '');
  const why = whyExtra + reasonBits(gives, gets);
  card.innerHTML =
    '<div class="suggest-swap">' +
      '<div class="suggest-side">' +
        '<div class="tag">' + (opts.dump ? 'TRADE OFF · ' : 'GIVE · ') + gives.length + '</div>' +
        artsHtml(gives) +
        '<div class="name" title="' + namesLine(gives) + '">' + namesRichHtml(gives) + '</div>' +
        '<div class="val">' + fmt(idea.gv) + '</div>' +
      '</div>' +
      '<div class="suggest-arrow">→</div>' +
      '<div class="suggest-side">' +
        '<div class="tag">GET · ' + gets.length + targetNote + '</div>' +
        artsHtml(gets) +
        '<div class="name" title="' + namesLine(gets) + '">' + namesRichHtml(gets) + '</div>' +
        '<div class="val">' + fmt(idea.tv) + '</div>' +
      '</div>' +
    '</div>' +
    '<div class="suggest-why"><strong>Why:</strong> ' + why + '</div>' +
    '<button class="suggest-use" type="button">Load into trade</button>';
  card.querySelector('.suggest-use').addEventListener('click', () => applySuggestion(gives, gets));
  return card;
}}

function suggestionKey(idea) {{
  return idea.gives.map((i) => i.id).sort().join('+') + '>' + idea.gets.map((i) => i.id).sort().join('+');
}}

function renderSuggestions(opts) {{
  opts = opts || {{}};
  if (opts.lists !== false) {{
    renderTargets();
    renderDumpList();
  }}
  const ideas = buildSuggestions();
  const dumpIdeas = buildDumpTradeIdeas();
  suggestList.innerHTML = '';

  const ownedElite = state.inv.some((entry) => {{
    const item = entry && byId[entry.id];
    return item && SUGGEST_RARITIES.has(item.rarity);
  }});
  const hasTargets = state.targets.some((entry) => {{
    const item = entry && byId[entry.id];
    return item && SUGGEST_RARITIES.has(item.rarity);
  }}) || (state.autoTargetHot && autoHotRisingTargets().length > 0);
  const hasDumpPicks = state.dumpList.some((entry) => {{
    const item = entry && byId[entry.id];
    return item && SUGGEST_RARITIES.has(item.rarity);
  }});

  if (!state.inv.length) {{
    suggestList.innerHTML = '<div class="suggest-empty">Add items to My Items</div>';
    return;
  }}
  if (!ownedElite) {{
    suggestList.innerHTML = '<div class="suggest-empty">Need Godly / Ancient / Chroma items</div>';
    return;
  }}

  const combined = [];
  const used = new Set();
  for (const idea of dumpIdeas) {{
    const key = suggestionKey(idea);
    if (used.has(key)) continue;
    used.add(key);
    combined.push({{ idea, dump: true }});
  }}
  for (const idea of ideas) {{
    const key = suggestionKey(idea);
    if (used.has(key)) continue;
    used.add(key);
    combined.push({{ idea, dump: !!idea.dump }});
  }}
  combined.sort((a, b) => (b.idea.score || 0) - (a.idea.score || 0));

  if (!combined.length) {{
    if (hasTargets) {{
      suggestList.innerHTML = '<div class="suggest-empty">No fair path to targets</div>';
    }} else if (hasDumpPicks) {{
      suggestList.innerHTML = '<div class="suggest-empty">No fair trade-offs found for these items</div>';
    }} else {{
      suggestList.innerHTML = '<div class="suggest-empty">No suggestions right now</div>';
    }}
    return;
  }}

  const frag = document.createDocumentFragment();
  for (const row of combined) frag.appendChild(renderSuggestCard(row.idea, {{ dump: row.dump }}));
  suggestList.appendChild(frag);
}}

let suggestTimer = 0;
let suggestListsPending = false;
let suggestIdleHandle = 0;
function scheduleSuggestions(opts) {{
  opts = opts || {{}};
  if (opts.lists !== false) suggestListsPending = true;
  updateGenOfferBtn();
  updateTradeHistBadge();
  if (suggestList) suggestList.classList.add('is-pending');
  if (suggestTimer) clearTimeout(suggestTimer);
  if (suggestIdleHandle && window.cancelIdleCallback) {{
    window.cancelIdleCallback(suggestIdleHandle);
    suggestIdleHandle = 0;
  }}
  const run = () => {{
    suggestTimer = 0;
    suggestIdleHandle = 0;
    const lists = suggestListsPending;
    suggestListsPending = false;
    renderSuggestions({{ lists }});
    if (suggestList) suggestList.classList.remove('is-pending');
  }};
  // Wait for input to settle, then run off the critical path
  suggestTimer = window.setTimeout(() => {{
    suggestTimer = 0;
    if (window.requestIdleCallback) {{
      suggestIdleHandle = window.requestIdleCallback(run, {{ timeout: 600 }});
    }} else {{
      suggestTimer = window.setTimeout(run, 0);
    }}
  }}, 220);
}}

let histCommitQueued = false;
function commitHistoryDeferred() {{
  if (histQuiet || histCommitQueued) return;
  histCommitQueued = true;
  requestAnimationFrame(() => {{
    histCommitQueued = false;
    commitHistory();
  }});
}}

function renderTradeOnly() {{
  paintTradeBoards({{ full: true }});
  commitHistoryDeferred();
}}

function render(opts) {{
  opts = opts || {{}};
  if (opts.board !== false) {{
    paintTradeBoards({{ full: true }});
  }}
  if (opts.inv !== false) updateInvPanel();
  // Suggestions depend on inventory / targets / dump — NOT the offer boards.
  // Never rebuild them on trade-slot add/remove (that was freezing the UI).
  const needSuggest = opts.suggestions === true || (opts.suggestions !== false && opts.inv !== false);
  if (needSuggest) {{
    const lists = opts.lists != null ? !!opts.lists : true;
    scheduleSuggestions({{ lists }});
  }} else {{
    updateGenOfferBtn();
    updateTradeHistBadge();
  }}
}}

function openPicker(side) {{
  if (side !== 'inv' && side !== 'targets' && side !== 'dump' && firstEmpty(side) === -1) {{
    alert('That offer is full (4 unique items — stacks share a slot).');
    return;
  }}
  state.pickingFor = side;
  pickerTitle.textContent = side === 'inv'
    ? 'Add to My Items'
    : side === 'targets'
      ? 'Add target item'
      : side === 'dump'
        ? 'Add item to trade off'
        : 'Add item';
  const showMine = side === 'your' || side === 'their';
  pickerMine.hidden = !showMine;
  modalBody.classList.toggle('no-mine', !showMine);
  search.value = '';
  rarityFilter.value = '';
  if (side === 'targets' || side === 'dump') rarityFilter.value = '';
  modal.classList.add('open');
  search.focus();
  renderPicker();
}}

function closePicker() {{
  modal.classList.remove('open');
  state.pickingFor = null;
}}

function filterCatalog(q, rar) {{
  const query = (q || '').trim().toLowerCase();
  return CATALOG.filter((item) => {{
    if (rar === 'Chroma') {{
      if (item.rarity !== 'Chroma' && !isChromaSet(item)) return false;
    }} else if (rar && item.rarity !== rar) {{
      return false;
    }}
    if (!query) return true;
    const aliasHit = (item.aliases || []).some((a) => String(a).toLowerCase().includes(query));
    return item.name.toLowerCase().includes(query) || item.id.toLowerCase().includes(query) || aliasHit;
  }});
}}

function persistQuickSearch() {{
  try {{
    localStorage.setItem(QUICK_SEARCH_KEY, state.quickSearch ? '1' : '0');
  }} catch (_) {{}}
}}

function setQuickSearchEnabled(on) {{
  state.quickSearch = !!on;
  if (quickSearchToggle) quickSearchToggle.checked = state.quickSearch;
  if (quickSearchWrap) quickSearchWrap.hidden = !state.quickSearch;
  if (!state.quickSearch) {{
    if (quickResults) {{
      quickResults.hidden = true;
      quickResults.innerHTML = '';
    }}
    if (quickSearchInput) quickSearchInput.value = '';
  }} else if (quickSearchInput) {{
    quickSearchInput.focus();
    renderQuickResults();
  }}
  persistQuickSearch();
}}

function loadQuickSearch() {{
  try {{
    const raw = localStorage.getItem(QUICK_SEARCH_KEY);
    if (raw === '1') state.quickSearch = true;
    else if (raw === '0') state.quickSearch = false;
  }} catch (_) {{}}
  if (quickSearchToggle) quickSearchToggle.checked = !!state.quickSearch;
  if (quickSearchWrap) quickSearchWrap.hidden = !state.quickSearch;
}}

function quickAdd(item, side) {{
  state.pickingFor = side;
  addItem(item, true);
  if (quickSearchInput) {{
    quickSearchInput.value = '';
    quickSearchInput.focus();
  }}
  if (quickResults) {{
    quickResults.hidden = true;
    quickResults.innerHTML = '';
  }}
}}

function renderQuickResults() {{
  if (!quickResults || !quickSearchInput) return;
  if (!state.quickSearch) {{
    quickResults.hidden = true;
    return;
  }}
  const q = quickSearchInput.value.trim();
  const rar = quickRarity ? quickRarity.value : '';
  if (!q && !rar) {{
    quickResults.hidden = true;
    quickResults.innerHTML = '';
    return;
  }}
  const rows = filterCatalog(q, rar).slice(0, 60);
  quickResults.hidden = false;
  quickResults.innerHTML = '';
  if (!rows.length) {{
    quickResults.innerHTML = '<div class="quick-empty">No items match.</div>';
    return;
  }}
  const frag = document.createDocumentFragment();
  for (const item of rows) {{
    const row = document.createElement('div');
    row.className = 'quick-row';
    const art = item.image
      ? '<img src="' + item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
      : '<div class="noimg">?</div>';
    const demand = item.demand != null ? ' · Demand ' + item.demand : '';
    row.innerHTML =
      art +
      '<div><div class="name-line">' + itemNameHtml(item, {{
        className: 'name',
      }}) + '</div>' +
      '<div class="meta">' + item.id + ' · ' + rarityLabel(item) + demand + '</div>' +
      '<div class="val">' + fmt(item.value) + '</div></div>' +
      '<div class="quick-actions">' +
        '<button type="button" class="offer">Add to offer</button>' +
        '<button type="button" class="request">Add to request</button>' +
      '</div>';
    row.querySelector('.offer').addEventListener('click', (e) => {{
      e.stopPropagation();
      quickAdd(item, 'your');
    }});
    row.querySelector('.request').addEventListener('click', (e) => {{
      e.stopPropagation();
      quickAdd(item, 'their');
    }});
    row.addEventListener('click', (e) => {{
      if (e.target.closest('button')) return;
      openDetail(item);
    }});
    frag.appendChild(row);
  }}
  quickResults.appendChild(frag);
}}

function isTypingTarget(el) {{
  if (!el || el === document.body) return false;
  const tag = (el.tagName || '').toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return true;
  if (el.isContentEditable) return true;
  return false;
}}

function renderPickerMine() {{
  pickerMineList.innerHTML = '';
  if (!state.inv.length) {{
    pickerMineList.innerHTML = '<div class="picker-mine-empty">Nothing in My Items yet. Use Add on the side panel.</div>';
    return;
  }}
  const sorted = state.inv
    .map((entry) => ({{ entry, item: byId[entry.id] }}))
    .filter((row) => row.item)
    .sort((a, b) => (b.item.value * b.entry.qty) - (a.item.value * a.entry.qty));

  const frag = document.createDocumentFragment();
  for (const rowInfo of sorted) {{
    const item = rowInfo.item;
    const entry = rowInfo.entry;
    const row = document.createElement('div');
    row.className = 'mine-row';
    const art = item.image
      ? '<img src="' + item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
      : '<div class="noimg">?</div>';
    row.innerHTML =
      art +
      '<div><div class="name-line">' + itemNameHtml(item, {{
        className: 'name',
      }}) + '</div>' +
      '<div class="meta">×' + entry.qty + ' · ' + fmt(item.value) + '</div></div>';
    row.title = 'Add to offer';
    row.addEventListener('click', () => addFromMine(item));
    frag.appendChild(row);
  }}
  pickerMineList.appendChild(frag);
}}

function addFromMine(item) {{
  const side = state.pickingFor;
  if (!side || side === 'inv') return;
  // Reuse addItem so sets expand the same way as catalog picks
  addItem(item, true);
}}

function renderPicker() {{
  const q = search.value.trim().toLowerCase();
  const rar = rarityFilter.value;
  const rows = filterCatalog(q, rar);

  modalList.innerHTML = '';
  if (!rows.length) {{
    modalList.innerHTML = '<div class="modal-empty">No items match.</div>';
  }} else {{
    const frag = document.createDocumentFragment();
    for (const item of rows) {{
      const row = document.createElement('div');
      row.className = 'item-row';
      const art = item.image
        ? '<img src="' + item.image + '" alt="" loading="lazy" referrerpolicy="no-referrer" />'
        : '<div class="noimg">?</div>';
      const demand = item.demand != null ? ' · Demand ' + item.demand : '';
      const members = (item.members && item.members.length)
        ? ' · adds ' + item.members.length + ' items'
        : (item.rarity === 'Set' ? ' · set (no breakdown)' : '');
      row.innerHTML =
        art +
        '<div><div class="name-line">' + itemNameHtml(item, {{
          className: 'name',
        }}) + '</div>' +
        '<div class="meta">' + item.id + ' · ' + rarityLabel(item) + demand + members + '</div></div>' +
        '<div class="val">' + fmt(item.value) + '</div>';
      row.title = 'Left-click add & close · Right-click add & keep open';
      row.addEventListener('click', () => addItem(item, false));
      row.addEventListener('contextmenu', (e) => {{
        e.preventDefault();
        addItem(item, true);
      }});
      frag.appendChild(row);
    }}
    modalList.appendChild(frag);
  }}

  if (state.pickingFor && state.pickingFor !== 'inv') renderPickerMine();
}}

function placeOne(side, item) {{
  if (side === 'inv') {{
    const existing = state.inv.find((e) => e.id === item.id);
    if (existing) existing.qty = Math.min(999, existing.qty + 1);
    else state.inv.push({{ id: item.id, qty: 1 }});
    return true;
  }}
  if (side === 'targets') {{
    if (!SUGGEST_RARITIES.has(item.rarity)) {{
      alert('Targets are limited to Godly, Ancient, and Chroma.');
      return false;
    }}
    const existing = state.targets.find((e) => e.id === item.id);
    if (existing) existing.qty = Math.min(9, existing.qty + 1);
    else state.targets.push({{ id: item.id, qty: 1 }});
    return true;
  }}
  if (side === 'dump') {{
    if (!SUGGEST_RARITIES.has(item.rarity)) {{
      alert('Trade-off items are limited to Godly, Ancient, and Chroma.');
      return false;
    }}
    const existing = state.dumpList.find((e) => e.id === item.id);
    if (existing) existing.qty = Math.min(9, existing.qty + 1);
    else state.dumpList.push({{ id: item.id, qty: 1 }});
    return true;
  }}
  const existing = state[side].find((e) => e && e.id === item.id);
  if (existing) {{
    existing.qty = Math.min(99, existing.qty + 1);
    existing._bump = true;
    return true;
  }}
  const idx = firstEmpty(side);
  if (idx === -1) return false;
  state[side][idx] = {{
    id: item.id,
    name: item.name,
    value: item.value,
    image: item.image,
    qty: 1,
    _enter: true,
  }};
  return true;
}}

function afterItemChange(side, keepOpen) {{
  if (!keepOpen) closePicker();
  if (side === 'inv' || side === 'targets' || side === 'dump') {{
    render();
    commitHistory();
  }} else {{
    renderTradeOnly();
  }}
}}

function addItem(item, keepOpen) {{
  const side = state.pickingFor;
  if (!side) return;

  // Expand sets into their contained items when we know the full list
  const memberIds = item.members && item.members.length ? item.members : null;
  if (item.rarity === 'Set' && !memberIds) {{
    // Opaque set row — still addable as one trade slot
    if (!placeOne(side, item)) {{
      if (side !== 'inv' && side !== 'targets' && side !== 'dump') {{
        alert('That offer is full (4 unique items — stacks share a slot).');
      }}
      return;
    }}
    afterItemChange(side, keepOpen);
    return;
  }}
  if (memberIds) {{
    const parts = [];
    const missing = [];
    for (const id of memberIds) {{
      const part = byId[id];
      if (!part) missing.push(id);
      else parts.push(part);
    }}
    if (!parts.length) {{
      // Broken mapping — fall back to the set as one entry
      if (!placeOne(side, item)) {{
        if (side !== 'inv' && side !== 'targets' && side !== 'dump') {{
          alert('That offer is full (4 unique items — stacks share a slot).');
        }}
        return;
      }}
      afterItemChange(side, keepOpen);
      return;
    }}
    if (side !== 'inv' && side !== 'targets' && side !== 'dump') {{
      const empty = state[side].filter((x) => !x).length;
      const needNew = parts.filter((p) => !state[side].some((e) => e && e.id === p.id)).length;
      if (needNew > empty) {{
        // Not enough room to expand — add the set as a single valued slot instead
        if (!placeOne(side, item)) {{
          alert(
            'Need ' + needNew + ' empty slots to expand this set (have ' + empty +
            '), and no free slot to add it as one set entry.'
          );
          return;
        }}
        afterItemChange(side, keepOpen);
        return;
      }}
    }}
    for (const part of parts) placeOne(side, part);
    afterItemChange(side, keepOpen);
    return;
  }}

  if (!placeOne(side, item)) {{
    if (side !== 'inv' && side !== 'targets' && side !== 'dump') alert('That offer is full (4 unique items — stacks share a slot).');
    return;
  }}
  afterItemChange(side, keepOpen);
}}

document.getElementById('modalClose').addEventListener('click', closePicker);
modal.addEventListener('click', (e) => {{
  if (e.target === modal) closePicker();
}});
document.getElementById('detailClose').addEventListener('click', closeDetail);
detail.addEventListener('click', (e) => {{
  if (e.target === detail) closeDetail();
}});
document.addEventListener('keydown', (e) => {{
  const mod = e.ctrlKey || e.metaKey;
  if (mod && !e.altKey && (e.key === 'z' || e.key === 'Z')) {{
    if (e.shiftKey) {{
      e.preventDefault();
      redoAction();
    }} else {{
      e.preventDefault();
      undoAction();
    }}
    return;
  }}
  if (mod && !e.altKey && (e.key === 'y' || e.key === 'Y')) {{
    e.preventDefault();
    redoAction();
    return;
  }}
  if (e.key === 'Escape') {{
    if (typeof window.__closeThemePanel === 'function') {{
      const themePanel = document.getElementById('themePanel');
      if (themePanel && !themePanel.hidden) {{
        window.__closeThemePanel();
        return;
      }}
    }}
    if (detail.classList.contains('open')) {{
      closeDetail();
      return;
    }}
    if (modal.classList.contains('open')) {{
      closePicker();
      return;
    }}
    if (prevTradeModal && prevTradeModal.classList.contains('open')) {{
      closePrevTrade();
      return;
    }}
    if (tradeHistModal && tradeHistModal.classList.contains('open')) {{
      closeTradeHistory();
      return;
    }}
    if (graphModal.classList.contains('open')) {{
      closeGraph();
      return;
    }}
    if (state.quickSearch && quickResults && !quickResults.hidden) {{
      quickResults.hidden = true;
      if (quickSearchInput) quickSearchInput.blur();
      return;
    }}
    return;
  }}

  // Quick search: typing anywhere focuses the search box
  if (!state.quickSearch || !quickSearchInput) return;
  if (modal.classList.contains('open') || detail.classList.contains('open') || graphModal.classList.contains('open')) return;
  if (tradeHistModal && tradeHistModal.classList.contains('open')) return;
  if (prevTradeModal && prevTradeModal.classList.contains('open')) return;
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (isTypingTarget(e.target) && e.target !== quickSearchInput) return;
  if (e.target === quickSearchInput) return;
  if (e.key.length !== 1) return;
  e.preventDefault();
  quickSearchInput.focus();
  quickSearchInput.value += e.key;
  renderQuickResults();
}});
search.addEventListener('input', renderPicker);
rarityFilter.addEventListener('change', renderPicker);
if (quickSearchToggle) {{
  quickSearchToggle.addEventListener('change', () => {{
    setQuickSearchEnabled(!!quickSearchToggle.checked);
  }});
}}
if (quickSearchInput) {{
  quickSearchInput.addEventListener('input', renderQuickResults);
  quickSearchInput.addEventListener('focus', renderQuickResults);
}}
if (quickRarity) quickRarity.addEventListener('change', renderQuickResults);
document.addEventListener('click', (e) => {{
  if (!state.quickSearch || !quickResults || quickResults.hidden) return;
  if (quickSearchWrap && quickSearchWrap.contains(e.target)) return;
  quickResults.hidden = true;
}});
document.getElementById('resetBtn').addEventListener('click', () => {{
  state.your = Array(SLOTS).fill(null);
  state.their = Array(SLOTS).fill(null);
  state.lowerCycle = null;
  state.higherCycle = null;
  renderTradeOnly();
}});
document.getElementById('genOfferBtn').addEventListener('click', generateOfferAgainstTheir);
document.getElementById('genReceiveBtn').addEventListener('click', generateReceiveFromYours);
document.getElementById('lowerOfferBtn').addEventListener('click', generateLowerOffer);
document.getElementById('higherOfferBtn').addEventListener('click', generateHigherOffer);
document.getElementById('completeOfferBtn').addEventListener('click', applyCompletedTrade);
document.getElementById('undoBtn').addEventListener('click', undoAction);
document.getElementById('redoBtn').addEventListener('click', redoAction);
if (tradeHistBtn) tradeHistBtn.addEventListener('click', openTradeHistory);
if (tradeHistModal) {{
  document.getElementById('tradeHistClose').addEventListener('click', closeTradeHistory);
  tradeHistModal.addEventListener('click', (e) => {{
    if (e.target === tradeHistModal) closeTradeHistory();
  }});
}}
if (tradeHistFilter) {{
  tradeHistFilter.addEventListener('input', () => {{
    tradeHistFilterText = tradeHistFilter.value || '';
    renderTradeHistory();
  }});
}}
if (prevTradeModal) {{
  document.getElementById('prevTradeClose').addEventListener('click', closePrevTrade);
  prevTradeModal.addEventListener('click', (e) => {{
    if (e.target === prevTradeModal) closePrevTrade();
  }});
}}
document.getElementById('invAddBtn').addEventListener('click', () => openPicker('inv'));
document.getElementById('invSaveBtn').addEventListener('click', saveInvSnapshot);
document.getElementById('invGraphBtn').addEventListener('click', openGraph);
document.getElementById('targetAddBtn').addEventListener('click', () => openPicker('targets'));
document.getElementById('targetClearBtn').addEventListener('click', () => {{
  if (!state.targets.length) return;
  state.targets = [];
  persistTargets();
  render();
  commitHistory();
}});
document.getElementById('dumpAddBtn').addEventListener('click', () => openPicker('dump'));
document.getElementById('dumpClearBtn').addEventListener('click', () => {{
  if (!state.dumpList.length) return;
  state.dumpList = [];
  persistDumpList();
  render();
  commitHistory();
}});
const avoidSetBreaksEl = document.getElementById('avoidSetBreaks');
if (avoidSetBreaksEl) {{
  avoidSetBreaksEl.addEventListener('change', () => {{
    state.avoidSetBreaks = !!avoidSetBreaksEl.checked;
    persistSetProtect();
    state.lowerCycle = null;
    state.higherCycle = null;
    render();
  }});
}}
const autoTargetHotEl = document.getElementById('autoTargetHot');
if (autoTargetHotEl) {{
  autoTargetHotEl.addEventListener('change', () => {{
    state.autoTargetHot = !!autoTargetHotEl.checked;
    persistAutoTargetHot();
    render();
  }});
}}
document.getElementById('graphClose').addEventListener('click', closeGraph);
graphModal.addEventListener('click', (e) => {{
  if (e.target === graphModal) closeGraph();
}});
document.getElementById('invClearBtn').addEventListener('click', () => {{
  if (!state.inv.length && !state.invHistory.length) return;
  if (!confirm('Clear all items and value history?')) return;
  state.inv = [];
  state.invHistory = [];
  persistInv();
  render();
  commitHistory();
}});

loadInv();
loadTargets();
loadDumpList();
loadTradeDismissed();
loadTradeHistory();
syncInferredTradesFromInvHistory();
loadSetProtect();
loadAutoTargetHot();
loadQuickSearch();
render();
renderTrendsPanel();
commitHistory();
</script>
</body>
</html>
"""

    OUT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({len(catalog)} SV items, aliases excluded)")


if __name__ == "__main__":
    main()
