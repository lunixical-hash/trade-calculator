"""Game-ID-first review: each game inventory ID -> closest Supreme Values names."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VALUES = ROOT / "mm2_values.json"
GAME = Path.home() / "AppData/Local/Volt/workspace/mm2_game_item_names.json"
OUT_TXT = ROOT / "game_to_sv_review.txt"
VOLT_TXT = Path.home() / "AppData/Local/Volt/workspace/game_to_sv_review.txt"
OUT_JSON = ROOT / "game_to_sv_review.json"
VOLT_JSON = Path.home() / "AppData/Local/Volt/workspace/game_to_sv_review.json"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def peel(s: str) -> str:
    n = norm(s)
    for suf in ("gun", "knife", "axe", "edge", "blade", "luger", "set"):
        if n.endswith(suf) and len(n) > len(suf) + 1:
            return n[: -len(suf)]
    return n


JUNK = {
    "data", "owned", "equipped", "amount", "active", "weapons", "pets", "effects",
    "emotes", "radios", "perks", "coins", "gems", "xp", "progress", "claimed",
    "current", "default", "list", "gui", "fx", "local", "loop", "reset", "sort",
    "price", "season", "character", "innocent", "murderer", "classic", "chroma",
    "elite", "regular", "combat", "myinventory", "messages", "quests", "credits",
}


def is_junk(name: str) -> bool:
    if not name or name.isdigit() or len(name) > 48:
        return True
    if norm(name) in JUNK:
        return True
    low = name.lower()
    for bad in ("claimed", "progress", "reward", "tutorial", "backup", "phonk", "module", "content deleted"):
        if bad in low:
            return True
    if " " in name and len(name) > 28 and "'" not in name:
        return True
    return False


def score(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    best = SequenceMatcher(None, na, nb).ratio()
    if peel(a) == peel(b) and peel(a):
        best = max(best, 0.9)
    if na in nb or nb in na:
        best = max(best, 0.84)
    return best


def main() -> None:
    values = json.loads(VALUES.read_text(encoding="utf-8"))
    game_dump = json.loads(GAME.read_text(encoding="utf-8"))
    sources = game_dump.get("sources") or {}

    sv = []
    for sv_id, display in (values.get("displayNames") or {}).items():
        sv.append((sv_id, display, values.get("items", {}).get(sv_id)))

    raw = game_dump.get("gameNames") or []
    owned = [n for n in raw if "Owned" in (sources.get(n) or [])]
    # Prefer owned, then other non-junk
    game_ids = []
    seen = set()
    for pool in (owned, raw):
        for n in pool:
            if n in seen or is_junk(n):
                continue
            seen.add(n)
            game_ids.append(n)
    game_ids.sort(key=str.lower)

    known = {
        "SunsetGun": ("Sunrise", "Sunrise"),
        "SunsetKnife": ("Sunset", "Sunset"),
    }

    rows = []
    for gid in game_ids:
        cands = []
        for sv_id, display, val in sv:
            s = max(score(gid, sv_id), score(gid, display))
            if s >= 0.72:
                cands.append((s, sv_id, display, val))
        cands.sort(key=lambda x: (-x[0], x[2].lower()))
        top = cands[:5]
        best = top[0] if top else None
        rows.append(
            {
                "gameId": gid,
                "fromOwned": "Owned" in (sources.get(gid) or []),
                "bestSvId": best[1] if best else None,
                "bestSvDisplay": best[2] if best else None,
                "bestValue": best[3] if best else None,
                "bestScore": round(best[0], 3) if best else None,
                "alternates": [
                    {"svId": i, "svDisplay": d, "value": v, "score": round(s, 3)}
                    for s, i, d, v in top[1:]
                ],
                "confirmedSvId": known.get(gid, ("",))[0] if gid in known else "",
            }
        )

    payload = {
        "note": "gameId is what MM2 inventory/trade uses. Pick the correct Supreme Values row (confirmedSvId).",
        "knownCorrections": {
            "SunsetGun": "Sunrise",
            "SunsetKnife": "Sunset",
        },
        "rows": rows,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    VOLT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "GAME ID  =>  closest SV name [svId] (value) score | alternates",
        "Fill in what is correct. Known: SunsetGun=>Sunrise, SunsetKnife=>Sunset",
        "=" * 110,
        "",
        "--- OWNED (items seen in real inventories on your dump) ---",
        "",
    ]
    for r in rows:
        if not r["fromOwned"]:
            continue
        alts = ", ".join(
            f"{a['svDisplay']}[{a['svId']}]={a['value']}({a['score']})" for a in r["alternates"][:3]
        ) or "-"
        lines.append(
            f"{r['gameId']}  =>  {r['bestSvDisplay'] or '???'} [{r['bestSvId'] or '?'}] "
            f"= {r['bestValue']} ({r['bestScore']})  |  {alts}"
        )

    lines += ["", "--- OTHER GAME-LIKE IDS (filtered) ---", ""]
    for r in rows:
        if r["fromOwned"]:
            continue
        if not r["bestSvId"]:
            continue
        if (r["bestScore"] or 0) < 0.84:
            continue
        lines.append(
            f"{r['gameId']}  =>  {r['bestSvDisplay']} [{r['bestSvId']}] = {r['bestValue']} ({r['bestScore']})"
        )

    text = "\n".join(lines)
    OUT_TXT.write_text(text, encoding="utf-8")
    VOLT_TXT.write_text(text, encoding="utf-8")
    print(f"Wrote {OUT_TXT}")
    owned_rows = [r for r in rows if r["fromOwned"]]
    print(f"Owned rows: {len(owned_rows)}")
    for r in owned_rows:
        if "sun" in r["gameId"].lower() or "travel" in r["gameId"].lower():
            print(r["gameId"], "=>", r["bestSvDisplay"], r["bestSvId"], r["bestScore"], r["alternates"][:3])


if __name__ == "__main__":
    main()
