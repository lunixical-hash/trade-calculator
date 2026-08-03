"""Build a review list: Supreme Values names <-> closest game inventory IDs."""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VALUES = ROOT / "mm2_values.json"
GAME = Path.home() / "AppData/Local/Volt/workspace/mm2_game_item_names.json"
OUT_JSON = ROOT / "name_match_review.json"
OUT_TXT = ROOT / "name_match_review.txt"
VOLT_TXT = Path.home() / "AppData/Local/Volt/workspace/name_match_review.txt"
VOLT_JSON = Path.home() / "AppData/Local/Volt/workspace/name_match_review.json"


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def peel(s: str) -> str:
    n = norm(s)
    for suf in ("gun", "knife", "axe", "edge", "blade", "luger", "set"):
        if n.endswith(suf) and len(n) > len(suf) + 1:
            return n[: -len(suf)]
    return n


JUNK_EXACT = {
    "data", "owned", "equipped", "amount", "active", "weapons", "pets",
    "effects", "emotes", "radios", "perks", "materials", "coins", "gems",
    "xp", "progress", "claimed", "current", "default", "list", "gui", "fx",
    "local", "loop", "reset", "sort", "price", "season", "character",
    "innocent", "murderer", "classic", "chroma", "elite", "regular", "combat",
    "myinventory", "itemid", "animationid", "layoutorder", "offset", "rotation",
    "messages", "quests", "bans", "credits", "prestige", "slots", "toys",
    "uniques", "footsteps", "dual", "userid", "torsoId", "chinaid",
}


def is_junk(name: str) -> bool:
    if not name or len(name) > 48:
        return True
    if name.isdigit():
        return True
    n = norm(name)
    if n in JUNK_EXACT:
        return True
    low = name.lower()
    for bad in (
        "claimed", "progress", "reward", "tutorial", "backup", "converted",
        "purchase", "history", "pending", "leaderboard", "pass20", "phonk",
        "sound effect", "module", "content deleted",
    ):
        if bad in low:
            return True
    # long spaced radio/song titles
    if " " in name and "'" not in name and "_" not in name and not re.match(r"^[A-Za-z0-9 ]+$", name):
        return True
    if " " in name and len(name) > 30:
        return True
    return False


def score(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    best = SequenceMatcher(None, na, nb).ratio()
    # bonus if peeled bases match
    pa, pb = peel(a), peel(b)
    if pa and pb and pa == pb:
        best = max(best, 0.92)
    # containment
    if na in nb or nb in na:
        best = max(best, 0.85)
    return best


def main() -> None:
    values = json.loads(VALUES.read_text(encoding="utf-8"))
    game_dump = json.loads(GAME.read_text(encoding="utf-8"))

    sv_items = []
    for game_id, display in (values.get("displayNames") or {}).items():
        sv_items.append(
            {
                "svId": game_id,
                "svDisplay": display,
                "value": values.get("items", {}).get(game_id),
            }
        )
    sv_items.sort(key=lambda x: (x["svDisplay"] or x["svId"]).lower())

    raw_game = game_dump.get("gameNames") or []
    sources = game_dump.get("sources") or {}

    # Prefer Owned keys when available; else filtered list
    owned = [n for n in raw_game if "Owned" in (sources.get(n) or [])]
    game_names = []
    seen = set()
    for pool in (owned, raw_game):
        for n in pool:
            if n in seen or is_junk(n):
                continue
            seen.add(n)
            game_names.append(n)

    # If Owned pool was tiny, still keep filtered full list (already merged)
    game_names.sort(key=str.lower)

    rows = []
    for item in sv_items:
        sv_id = item["svId"]
        sv_disp = item["svDisplay"]
        candidates = []
        for g in game_names:
            s = max(score(sv_id, g), score(sv_disp, g))
            if s >= 0.72:
                candidates.append((s, g))
        candidates.sort(key=lambda x: (-x[0], x[1].lower()))
        top = candidates[:5]
        best = top[0] if top else None
        rows.append(
            {
                "svId": sv_id,
                "svDisplay": sv_disp,
                "value": item["value"],
                "bestGameId": best[1] if best else None,
                "bestScore": round(best[0], 3) if best else None,
                "alternates": [{"gameId": g, "score": round(s, 3)} for s, g in top[1:]],
                "needsReview": True,
                "confirmedGameId": "",  # fill this manually
            }
        )

    # Also list game IDs with no SV match (possible missing mappings)
    matched_game = {r["bestGameId"] for r in rows if r["bestGameId"]}
    unmatched_game = [g for g in game_names if g not in matched_game]

    payload = {
        "note": (
            "For each row: svDisplay/svId are Supreme Values. "
            "bestGameId is the closest game inventory ID guess. "
            "Set confirmedGameId to the real game ID (or leave blank if wrong). "
            "Known tip from you: SunsetGun->Sunrise, SunsetKnife->Sunset."
        ),
        "knownCorrections": {
            "SunsetGun": "Sunrise",
            "SunsetKnife": "Sunset",
        },
        "svCount": len(rows),
        "gameIdCount": len(game_names),
        "ownedOnlyCount": len(owned),
        "matches": rows,
        "unmatchedGameIdsSample": unmatched_game[:200],
    }

    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    VOLT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = []
    lines.append("SV name  |  value  |  closest game ID  |  score  |  alternates")
    lines.append("=" * 100)
    for r in rows:
        alts = ", ".join(f"{a['gameId']}({a['score']})" for a in r["alternates"][:3]) or "-"
        lines.append(
            f"{r['svDisplay']} [{r['svId']}]  |  {r['value']}  |  "
            f"{r['bestGameId'] or '???'}  |  {r['bestScore'] or '-'}  |  {alts}"
        )
    lines.append("")
    lines.append("Known corrections to apply:")
    lines.append("  SunsetGun  -> Sunrise value (svId Sunrise)")
    lines.append("  SunsetKnife -> Sunset value (svId Sunset)")
    lines.append("")
    lines.append(f"Game IDs considered: {len(game_names)} (Owned keys: {len(owned)})")
    text = "\n".join(lines)
    OUT_TXT.write_text(text, encoding="utf-8")
    VOLT_TXT.write_text(text, encoding="utf-8")

    print(f"Wrote {OUT_TXT}")
    print(f"Wrote {VOLT_TXT}")
    print(f"SV rows: {len(rows)} | game IDs used: {len(game_names)} | Owned: {len(owned)}")
    # print a few relevant
    for r in rows:
        if "sun" in (r["svId"] + r["svDisplay"]).lower() or "travel" in (r["svId"] + r["svDisplay"]).lower():
            print(r["svDisplay"], "=>", r["bestGameId"], r["bestScore"], r["alternates"][:3])


if __name__ == "__main__":
    main()
