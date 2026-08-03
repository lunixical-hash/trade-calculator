"""Apply SV => gameId corrections into aliases + values JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VALUES = ROOT / "mm2_values.json"
ALIASES = ROOT / "aliases.json"
VOLT = Path.home() / "AppData/Local/Volt/workspace/mm2_values.json"
CORRECTIONS_OUT = ROOT / "sv_game_corrections.json"

RAW = r"""
Gingerscope => Gingerscope
TravelersAxe => TravelerAxe
Celestial => Celestial
VampiresAxe => VampireAxe
Harvester => Harvester
Icepiercer => Icepiercer
Icebreaker => Icebreaker
ElderwoodScythe => ElderwoodScythe
SwirlyAxe => SwirlyAxe
Hallowscythe => Hallowscythe
Logchopper => Hallowscythe
Icewing => Icewing
TravelersGun => TravelerGun
Constellation => Constellation
VampireGun => VampireGun
Darkshot => Darkshot
Darksword => Darksword
Sunrise => SunsetGun
Snowcannon => Snowcannon
Bauble => Bauble
Alienbeam => UFOKnife
Raygun => Raygun
Sunset => FIXME
RainbowGun => Rainbow_G
Flora => Flora
Rainbow => Rainbow_K
Bloom => Bloom
HeartWand => HeartWand
Ocean => Ocean_G
Waves => FIXME
Xenoknife => XenoKnife
Xenoshot => XenoGun
FlowerwoodGun => FlowerwoodGun
Blizzard => Blizzard
Flowerwood => FlowerwoodKnife
Snowstorm => Snowstorm
SnowDagger => SnowDagger
Watergun => Watergun
Treat => Treat
Sweet => Sweet
Bat => ZombieBat
Pearlshine => Pearl_G
Pearl => Pearl_K
Candy => candy
Heartblade => Heartblade
Luger => Luger
RedLuger => RedLuger
Phantom => Phantom2022
Spectre => Spectre2022
Candleflame => Candleflame
Darkbringer => Darkbringer
ElderwoodBlade => ElderwoodKnife
ElderwoodRevolver => ElderwoodGun
Iceblaster => Iceblaster
Lightbringer => Lightbringer
Makeshift => Makeshift
Sugar => Sugar
Ornament => BaubleKnife
GreenLuger => GreenLuger
Amerilaser => Amerilaser
Laser => Laser
Hallowgun => Hallowgun
Nightblade => Nightblade
Shark => Shark
Icebeam => Icebeam
Plasmabeam => Plasmabeam
SwirlyGun => SwirlyGun
BattleaxeII => BattleAxe2
Blaster => Blaster
GingerLuger => GingerLuger
Pixel => Pixel
Gemstone => Gemstone
Iceflake => Iceflake
OldGlory => AmericaSword
Plasmablade => Plasmablade
Slasher => Slasher
VampiresEdge => VampiresEdge
Cookiecane => Cookieblade
Deathshard => Deathshard
Eternalcane => EternalCane
Gingerblade => Gingerblade
Jinglegun => Jinglegun
Lugercane => Lugercane
Minty => Lugercane
Nebula => Nebula
Virtual => Virtual
Battleaxe => BattleAxe
Gingermint => Gingermint_G
SwirlyBlade => SwirlyBlade
Chill => Chill
Clockwork => Clockwork
Fang => Fang
Frostsaber => Frostsaber
Heat => Heat
Spider => Spider
Tides => Tides
Bioblade => Bioblade
EternalIII => Eternal3
EternalIV => Eternal4
HallowsBlade => HallowsBlade
HallowEdge => HallowsBlade
Handsaw => Handsaw
Boneblade => Boneblade
Eternal => Eternal
EternalII => Eternal2
Frostbite => Frostbite
Ghostblade => Ghostblade
IceDragon => IceDragon
IceShard => IceShard
Prismatic => Prismatic
Pumpking => Pumpking
Saw => Saw
Xmas => Xmas
Eggblade => Eggblade
Flames => Flames
Snowflake => Snowflake
WinterEdge => WintersEdge
Peppermint => Peppermint
BlueSeer => BlueSeer
Cookieblade => Cookieblade
PurpleSeer => PurpleSeer
RedSeer => RedSeer
Seer => TheSeer
OrangeSeer => OrangeSeer
YellowSeer => YellowSeer
"""


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> None:
    pairs: list[tuple[str, str]] = []
    for line in RAW.strip().splitlines():
        line = line.strip()
        if not line or "=>" not in line:
            continue
        left, right = [p.strip() for p in line.split("=>", 1)]
        if not left or not right or right.upper() == "FIXME":
            continue
        pairs.append((left, right))

    # Build gameId -> svId. Prefer identity / closest when conflicts.
    candidates: dict[str, list[str]] = {}
    for sv_id, game_id in pairs:
        candidates.setdefault(game_id, []).append(sv_id)

    game_to_sv: dict[str, str] = {}
    conflicts = []
    for game_id, sv_list in candidates.items():
        unique = list(dict.fromkeys(sv_list))
        if len(unique) == 1:
            game_to_sv[game_id] = unique[0]
            continue
        # Prefer exact / normalized match
        best = None
        for sv in unique:
            if sv == game_id or norm(sv) == norm(game_id):
                best = sv
                break
        if not best:
            # Prefer highest similarity ratio-ish by shared prefix length
            best = max(unique, key=lambda sv: sum(a == b for a, b in zip(norm(sv), norm(game_id))))
        game_to_sv[game_id] = best
        conflicts.append({"gameId": game_id, "options": unique, "chose": best})

    # Identity aliases not needed in file, but keep non-identity
    aliases = {g: s for g, s in game_to_sv.items() if g != s}

    values = json.loads(VALUES.read_text(encoding="utf-8"))
    items = values.setdefault("items", {})
    displays = values.setdefault("displayNames", {})
    images = values.setdefault("images", {})
    rarities = values.setdefault("rarities", {})
    meta = values.setdefault("meta", {})

    applied = 0
    missing_sv = []
    for game_id, sv_id in sorted(aliases.items()):
        if sv_id not in items:
            missing_sv.append({"gameId": game_id, "svId": sv_id})
            continue
        items[game_id] = items[sv_id]
        if sv_id in displays:
            displays[game_id] = displays[sv_id]
        if sv_id in images:
            images[game_id] = images[sv_id]
        if sv_id in rarities:
            rarities[game_id] = rarities[sv_id]
        if sv_id in meta:
            meta[game_id] = meta[sv_id]
        applied += 1

    # Also store full mapping including identities for the review UI
    values["aliases"] = aliases
    values["svToGame"] = {sv: game for game, sv in game_to_sv.items()}
    # Keep explicit user map
    user_map = {sv: game for sv, game in pairs if game.upper() != "FIXME"}
    values["manualSvToGame"] = user_map

    text = json.dumps(values, indent=2)
    VALUES.write_text(text, encoding="utf-8")
    VOLT.write_text(text, encoding="utf-8")
    ALIASES.write_text(json.dumps(aliases, indent=2), encoding="utf-8")

    report = {
        "aliasCount": len(aliases),
        "applied": applied,
        "conflicts": conflicts,
        "missingSv": missing_sv,
        "aliases": aliases,
        "skippedFixme": ["Sunset", "Waves"],
    }
    CORRECTIONS_OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Aliases written: {len(aliases)}")
    print(f"Applied onto values: {applied}")
    if conflicts:
        print("Conflicts resolved:")
        for c in conflicts:
            print(f"  {c['gameId']}: {c['options']} -> {c['chose']}")
    if missing_sv:
        print("Missing SV ids (not in scrape):")
        for m in missing_sv:
            print(f"  {m}")
    print(f"Updated {VALUES}")
    print(f"Updated {VOLT}")


if __name__ == "__main__":
    main()
