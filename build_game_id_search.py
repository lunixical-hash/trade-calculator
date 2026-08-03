"""Build a searchable game-ID lookup page from the latest dump."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GAME = Path.home() / "AppData/Local/Volt/workspace/mm2_game_item_names.json"
VALUES = ROOT / "mm2_values.json"
OUT = ROOT / "game_id_search.html"
VOLT = Path.home() / "AppData/Local/Volt/workspace/game_id_search.html"

HARD_JUNK = {
    "data", "owned", "equipped", "amount", "active", "weapons", "pets", "effects",
    "emotes", "radios", "perks", "coins", "gems", "xp", "progress", "claimed",
    "current", "default", "list", "gui", "fx", "local", "loop", "reset", "sort",
    "price", "season", "character", "innocent", "murderer", "classic", "chroma",
    "elite", "regular", "combat", "myinventory", "messages", "quests", "credits",
    "userid", "parent", "classname", "animationid", "itemid", "layoutorder",
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def soft_junk(name: str) -> bool:
    if not name or name.isdigit():
        return True
    if norm(name) in HARD_JUNK:
        return True
    low = name.lower()
    for bad in (
        "claimed", "progress", "rewarded", "tutorial", "backup", "phonk",
        "module", "content deleted", "sound effect", "converted", "purchasehistory",
        "leaderboard", "pending",
    ):
        if bad in low:
            return True
    return False


def is_weapon(name: str, category: str | None, sources: list[str]) -> bool:
    cat = (category or "").lower()
    if cat in {"pets", "effects", "emotes", "radios", "perks", "materials"}:
        return False
    if cat == "weapons":
        return True
    # If category missing, keep unless it clearly looks like a pet/effect currency
    low = name.lower()
    if any(x in low for x in ("plush", "egg", "pet", "radio", "effect", "emote")):
        # still allow weapon-like event ids ending in _K_/_G_
        if re.search(r"_[kg]_\d", low):
            return True
        return False
    return True


def main() -> None:
    dump = json.loads(GAME.read_text(encoding="utf-8"))
    values = json.loads(VALUES.read_text(encoding="utf-8")) if VALUES.exists() else {}
    sources = dump.get("sources") or {}
    game_displays = dump.get("gameDisplayNames") or {}
    categories = dump.get("categories") or {}
    displays = values.get("displayNames") or {}
    rarities = values.get("rarities") or {}

    by_norm = {}
    for sv_id, display in displays.items():
        by_norm[norm(sv_id)] = (sv_id, display, rarities.get(sv_id))
        by_norm[norm(display)] = (sv_id, display, rarities.get(sv_id))

    rows = []
    for name in dump.get("gameNames") or []:
        srcs = sources.get(name) or []
        cat = categories.get(name)
        if not is_weapon(name, cat, srcs):
            continue
        if soft_junk(name):
            continue
        owned = any(("Owned" in s) or s.endswith(":Owned") for s in srcs)
        from_db = any(
            ("InventoryModule" in s) or s.startswith("Module:") or "Database" in s or "ItemData" in s
            for s in srcs
        )
        hint = by_norm.get(norm(name))
        gdisp = game_displays.get(name)
        rows.append(
            {
                "id": name,
                "owned": owned,
                "fromDb": from_db,
                "junk": False,
                "weapon": True,
                "category": cat or "Weapons",
                "gameDisplay": gdisp,
                "hintSvId": hint[0] if hint else None,
                "hintDisplay": hint[1] if hint else None,
                "hintRarity": hint[2] if hint else None,
                "search": " ".join(
                    x for x in [name, gdisp or "", hint[1] if hint else "", hint[0] if hint else ""] if x
                ).lower(),
            }
        )

    rows.sort(key=lambda r: (0 if r["owned"] else 1, 0 if r["fromDb"] else 1, r["id"].lower()))

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Game ID Search</title>
<style>
  :root {{
    --bg:#0f1115; --panel:#171a21; --text:#e8eaef; --muted:#9aa3b2;
    --line:#2a3140; --accent:#3db8a0; --chip:#24303a; --warn:#e6b84d;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; font-family:"Segoe UI", system-ui, sans-serif; color:var(--text);
    background: radial-gradient(1000px 500px at 0% 0%, #1a3030 0%, var(--bg) 45%);
  }}
  header {{
    position:sticky; top:0; z-index:5; backdrop-filter:blur(10px);
    background:rgba(15,17,21,.92); border-bottom:1px solid var(--line);
    padding:16px 20px;
  }}
  h1 {{ margin:0 0 6px; font-size:20px; }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:10px; line-height:1.4; max-width:900px; }}
  .warn {{
    background:#2a2416; border:1px solid #5a4a20; color:#f0d58a; border-radius:10px;
    padding:10px 12px; font-size:13px; margin-bottom:12px; line-height:1.4;
  }}
  .controls {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; }}
  input, select, button {{
    background:var(--panel); color:var(--text); border:1px solid var(--line);
    border-radius:10px; padding:10px 12px; font-size:14px;
  }}
  input {{ flex:1; min-width:260px; max-width:520px; }}
  button {{ cursor:pointer; font-weight:700; }}
  .stats {{ color:var(--muted); font-size:12px; width:100%; }}
  main {{ padding:14px 20px 40px; display:grid; gap:8px; }}
  .row {{
    display:grid; grid-template-columns:1fr auto auto; gap:12px; align-items:center;
    background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:10px 12px;
  }}
  .id {{ font-family:ui-monospace, Consolas, monospace; font-weight:800; font-size:15px; }}
  .hint {{ color:var(--muted); font-size:12px; margin-top:4px; }}
  .badge {{
    display:inline-block; padding:3px 8px; border-radius:999px; font-size:11px; font-weight:700;
    background:var(--chip); color:var(--muted); margin-left:6px;
  }}
  .badge.owned {{ color:#b7f5e4; background:#1b3a34; }}
  .badge.db {{ color:#cbb7ff; background:#2a2438; }}
  .badge.junk {{ color:#f0d58a; background:#2a2416; }}
  .copy {{
    background:#12161d; border:1px solid var(--line); border-radius:8px;
    padding:7px 10px; font-size:12px; font-weight:700; cursor:pointer;
  }}
  .copy.copied {{ border-color:var(--accent); color:var(--accent); }}
  mark {{ background:rgba(61,184,160,.25); color:#fff; border-radius:3px; padding:0 2px; }}
</style>
</head>
<body>
<header>
  <h1>Game ID Search · Weapons</h1>
  <div class="sub">
    Weapons only (pets/effects/etc. hidden). Click <b>Copy</b> to paste into the SV review page.
  </div>
  <div class="warn" id="coverageWarn"></div>
  <div class="controls">
    <input id="q" type="search" placeholder="Type part of a name... e.g. sun, travel, vamp, chroma" autofocus />
    <select id="filter">
      <option value="weapons">Weapons only</option>
      <option value="owned">Owned weapons</option>
      <option value="db">From modules/DB</option>
    </select>
    <button id="clearBtn">Clear</button>
    <div class="stats" id="stats"></div>
  </div>
</header>
<main id="list"></main>
<script>
const ROWS = {json.dumps(rows)};
const DUMP_COUNT = {len(rows)};

function esc(s) {{
  return String(s ?? "").replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
}}
function highlight(text, query) {{
  const t = String(text ?? "");
  if (!query) return esc(t);
  const parts = query.trim().toLowerCase().split(/\\s+/).filter(Boolean);
  let out = esc(t);
  for (const p of parts) {{
    const re = new RegExp("(" + p.replace(/[.*+?^${{}}()|[\\]\\\\]/g, "\\\\$&") + ")", "ig");
    out = out.replace(re, "<mark>$1</mark>");
  }}
  return out;
}}
function tokens(q) {{ return q.trim().toLowerCase().split(/\\s+/).filter(Boolean); }}
function matches(row, parts) {{
  if (!parts.length) return true;
  const hay = row.search;
  return parts.every(p => hay.includes(p) || row.id.toLowerCase().includes(p));
}}
function scoreRow(row, parts) {{
  if (!parts.length) return (row.owned ? 5 : 0) + (row.fromDb ? 2 : 0);
  const id = row.id.toLowerCase();
  let s = 0;
  for (const p of parts) {{
    if (id === p) s += 100;
    else if (id.startsWith(p)) s += 45;
    else if (id.includes(p)) s += 25;
    else if (row.search.includes(p)) s += 10;
  }}
  if (row.owned) s += 4;
  if (row.fromDb) s += 2;
  if (row.junk) s -= 8;
  return s;
}}

document.getElementById("coverageWarn").textContent =
  "Showing weapons only from dump (" + DUMP_COUNT + "). Pets/effects/etc. are hidden.";

function render() {{
  const q = document.getElementById("q").value;
  const parts = tokens(q);
  const filter = document.getElementById("filter").value;
  let list = ROWS.slice();
  if (filter === "owned") list = list.filter(r => r.owned);
  if (filter === "db") list = list.filter(r => r.fromDb);
  list = list.filter(r => matches(r, parts));
  list.sort((a,b) => scoreRow(b, parts) - scoreRow(a, parts) || a.id.localeCompare(b.id));

  const root = document.getElementById("list");
  root.innerHTML = list.slice(0, 500).map(r => {{
    const bits = [];
    if (r.gameDisplay) bits.push("Game label: " + esc(r.gameDisplay));
    if (r.hintDisplay) bits.push("Maybe SV: " + esc(r.hintDisplay) + " (" + esc(r.hintSvId) + ")");
    if (r.category) bits.push(esc(r.category));
    const hint = bits.length ? `<div class="hint">${{bits.join(" · ")}}</div>` : "";
    return `<div class="row" data-id="${{esc(r.id)}}">
      <div>
        <div class="id">${{highlight(r.id, q)}}
          ${{r.owned ? '<span class="badge owned">Owned</span>' : ''}}
          ${{r.fromDb ? '<span class="badge db">DB</span>' : ''}}
          ${{r.junk ? '<span class="badge junk">Junk?</span>' : ''}}
        </div>
        ${{hint}}
      </div>
      <span class="badge">${{r.owned ? "Owned" : (r.fromDb ? "DB" : "ID")}}</span>
      <button class="copy" type="button">Copy</button>
    </div>`;
  }}).join("");

  document.getElementById("stats").textContent =
    list.length + " match" + (list.length === 1 ? "" : "es") +
    (list.length > 500 ? " (showing first 500)" : "") +
    " · dump size " + DUMP_COUNT;

  root.querySelectorAll(".copy").forEach(btn => {{
    btn.addEventListener("click", async () => {{
      const id = btn.closest(".row").dataset.id;
      try {{ await navigator.clipboard.writeText(id); }}
      catch {{ prompt("Copy ID:", id); }}
      btn.textContent = "Copied";
      btn.classList.add("copied");
      setTimeout(() => {{ btn.textContent = "Copy"; btn.classList.remove("copied"); }}, 900);
    }});
  }});
}}

document.getElementById("q").addEventListener("input", render);
document.getElementById("filter").addEventListener("change", render);
document.getElementById("clearBtn").addEventListener("click", () => {{
  document.getElementById("q").value = "";
  render();
  document.getElementById("q").focus();
}});
render();
</script>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    VOLT.write_text(html, encoding="utf-8")
    useful = sum(1 for r in rows if not r["junk"])
    owned = sum(1 for r in rows if r["owned"])
    print(f"Wrote {OUT}")
    print(f"dump={len(rows)} useful={useful} owned={owned}")


if __name__ == "__main__":
    main()
