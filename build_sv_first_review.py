"""SV-first name match review: SV item -> guessed game ID.

Sorts by rarity, then value. Skips Sets.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VALUES = ROOT / "mm2_values.json"
GAME = Path.home() / "AppData/Local/Volt/workspace/mm2_game_item_names.json"
OUT_HTML = ROOT / "name_match_review.html"
VOLT_HTML = Path.home() / "AppData/Local/Volt/workspace/name_match_review.html"
OUT_JSON = ROOT / "sv_to_game_review.json"
VOLT_JSON = Path.home() / "AppData/Local/Volt/workspace/sv_to_game_review.json"

RARITY_ORDER = [
    "Ancient",
    "Godly",
    "Vintage",
    "Chroma",
    "Unique",
    "Evo",
    "Legendary",
    "Rare",
    "Uncommon",
    "Common",
]

KNOWN_GAME_FOR_SV = {
    # svId -> preferred game inventory id
    "Sunrise": "SunsetGun",
    "Sunset": "SunsetKnife",
    "TravelersGun": "TravelerGun",
    "TravelersAxe": "TravelerAxe",
}


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
    if nb.startswith("chroma") and not na.startswith("chroma"):
        best *= 0.85
    if na.startswith("chroma") and not nb.startswith("chroma"):
        best *= 0.9
    if peel(a) == peel(b) and peel(a):
        best = max(best, 0.9)
    if na in nb or nb in na:
        best = max(best, 0.84)
    return best


def fmt_value(v) -> str:
    if v is None:
        return "—"
    try:
        n = float(v)
    except (TypeError, ValueError):
        return str(v)
    if n >= 1000:
        return f"{n:,.0f}"
    if n == int(n):
        return str(int(n))
    return f"{n:g}"


def confidence(s: float | None) -> tuple[str, str]:
    if s is None:
        return "none", "No match"
    if s >= 0.97:
        return "high", "Likely"
    if s >= 0.85:
        return "mid", "Maybe"
    return "low", "Uncertain"


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SV → Game Name Review</title>
<style>
  :root {
    --bg:#0f1115; --panel:#171a21; --row:#1c2029; --row2:#1a1e26; --text:#e8eaef;
    --muted:#9aa3b2; --line:#2a3140; --accent:#3db8a0; --high:#3ecf8e; --mid:#e6b84d;
    --low:#e07a5f; --none:#6b7280; --chip:#24303a;
  }
  * { box-sizing:border-box; }
  body {
    margin:0; font-family:"Segoe UI", system-ui, sans-serif; color:var(--text);
    background: radial-gradient(1200px 600px at 10% -10%, #1a3030 0%, var(--bg) 45%);
  }
  header {
    position:sticky; top:0; z-index:10; backdrop-filter:blur(10px);
    background:rgba(15,17,21,.92); border-bottom:1px solid var(--line);
    padding:16px 20px 14px;
  }
  h1 { margin:0 0 6px; font-size:20px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:12px; max-width:920px; line-height:1.4; }
  .controls { display:flex; flex-wrap:wrap; gap:10px; align-items:center; }
  input[type="search"], select, button {
    background:var(--panel); color:var(--text); border:1px solid var(--line);
    border-radius:10px; padding:9px 12px; font-size:13px;
  }
  input[type="search"] { flex:1; min-width:220px; max-width:420px; }
  button { cursor:pointer; }
  button.primary { background:var(--accent); color:#081512; border-color:transparent; font-weight:700; }
  .stats { color:var(--muted); font-size:12px; }
  main { padding:16px 20px 40px; }
  .hint {
    background:var(--panel); border:1px solid var(--line); border-radius:12px;
    padding:12px 14px; margin-bottom:14px; color:var(--muted); font-size:13px; line-height:1.45;
  }
  .hint code { color:var(--accent); }
  .section {
    margin:18px 0 8px; font-size:13px; text-transform:uppercase; letter-spacing:.06em;
    color:var(--muted); font-weight:700;
  }
  table { width:100%; border-collapse:collapse; }
  th {
    text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.04em;
    color:var(--muted); padding:10px 12px; border-bottom:1px solid var(--line);
    position:sticky; top:132px; background:#12151b;
  }
  td { padding:12px; border-bottom:1px solid var(--line); vertical-align:top; font-size:14px; }
  tr.item:nth-child(even) td { background:var(--row2); }
  tr.item:nth-child(odd) td { background:var(--row); }
  tr.item:hover td { background:#222833; }
  tr.item.hidden { display:none; }
  tr.item[data-status="ok"] td { box-shadow: inset 3px 0 0 var(--high); }
  tr.item[data-status="bad"] td { box-shadow: inset 3px 0 0 var(--low); }
  tr.item[data-status="skip"] td { box-shadow: inset 3px 0 0 var(--none); }
  .sv-cell { display:flex; gap:12px; align-items:flex-start; }
  .thumb {
    width:56px; height:56px; border-radius:10px; object-fit:contain;
    background:#10141b; border:1px solid var(--line); flex:0 0 auto;
  }
  .thumb.missing { display:grid; place-items:center; color:var(--muted); font-size:11px; }
  .sv-name { font-weight:700; }
  .sv-id { color:var(--muted); font-size:12px; font-family:ui-monospace, Consolas, monospace; margin-top:3px; }
  .rarity {
    display:inline-block; margin-top:6px; padding:2px 8px; border-radius:999px;
    font-size:11px; font-weight:700; background:#2a2438; color:#d2c4ff;
  }
  .meta { color:var(--muted); font-size:12px; margin-top:4px; }
  .game {
    font-family:ui-monospace, Consolas, monospace; font-weight:700; color:#fff;
  }
  .badge {
    display:inline-block; margin-left:8px; padding:2px 8px; border-radius:999px;
    font-size:11px; font-weight:700; background:var(--chip); color:var(--muted);
  }
  .badge.owned { color:#b7f5e4; background:#1b3a34; }
  .alts { color:var(--muted); font-size:12px; line-height:1.45; margin-top:8px; }
  .alts strong { color:#c9d1de; font-weight:600; }
  .value { font-variant-numeric:tabular-nums; font-weight:800; color:#b7f5e4; }
  .pill { display:inline-block; padding:3px 9px; border-radius:999px; font-size:11px; font-weight:700; }
  .pill.high { background:rgba(62,207,142,.15); color:var(--high); }
  .pill.mid { background:rgba(230,184,77,.15); color:var(--mid); }
  .pill.low { background:rgba(224,122,95,.15); color:var(--low); }
  .pill.none { background:rgba(107,114,128,.18); color:var(--none); }
  .mark { display:flex; gap:6px; flex-wrap:wrap; }
  .mark button { padding:6px 10px; border-radius:8px; font-size:12px; font-weight:700; cursor:pointer; }
  .custom {
    margin-top:8px; width:100%; background:#12161d; color:var(--text);
    border:1px solid var(--line); border-radius:8px; padding:7px 9px; font-size:12px;
  }
  footer { color:var(--muted); font-size:12px; padding:8px 20px 24px; }
</style>
</head>
<body>
<header>
  <h1>Supreme Values → Game IDs</h1>
  <div class="sub">
    Left = item on Supreme Values. Right = closest game inventory ID guess.
    Sorted by <b>rarity</b>, then <b>value</b>. Sets and pets are excluded.
  </div>
  <div class="controls">
    <input id="q" type="search" placeholder="Search SV name, id, or game id..." />
    <select id="filter">
      <option value="all">All items</option>
      <option value="todo">Unchecked only</option>
      <option value="high">Likely matches</option>
      <option value="mid">Maybe / uncertain</option>
      <option value="none">No game match</option>
      <option value="owned-guess">Guess is an Owned id</option>
    </select>
    <select id="rarityFilter">
      <option value="">All rarities</option>
      __RARITY_OPTIONS__
    </select>
    <button id="exportBtn" class="primary">Copy my corrections</button>
    <span class="stats" id="stats"></span>
  </div>
</header>
<main>
  <div class="hint">
    Mark Correct if the game ID is right. If wrong, type the real game inventory ID
    (example: <code>TravelerGun</code>). Known: <code>Sunrise ↔ SunsetGun</code>, <code>Sunset ↔ SunsetKnife</code>.
  </div>
  <table>
    <thead>
      <tr>
        <th style="width:34%">On Supreme Values</th>
        <th style="width:12%">Value</th>
        <th style="width:28%">Guessed game ID</th>
        <th style="width:10%">Confidence</th>
        <th style="width:16%">Your call</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</main>
<footer>Choices save in this browser. Export before closing if you want to keep them.</footer>
<script>
const ROWS = __ROWS__;
const key = "mm2-sv-first-review-v1";
const saved = JSON.parse(localStorage.getItem(key) || "{}");

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function render() {
  const tb = document.getElementById("tbody");
  let html = "";
  let lastRarity = null;
  ROWS.forEach((r, i) => {
    if (r.rarity !== lastRarity) {
      lastRarity = r.rarity;
      html += `<tr class="section-row"><td colspan="5"><div class="section">${esc(r.rarity || "Unknown")} · sorted by value</div></td></tr>`;
    }
    const st = saved[r.svId]?.status || "";
    const custom = saved[r.svId]?.custom || r.knownGameId || "";
    const img = r.image
      ? `<img class="thumb" src="${esc(r.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" />`
      : `<div class="thumb missing">No img</div>`;
    const alts = (r.alternates || []).map(a =>
      `<strong>${esc(a.gameId)}</strong>${a.fromOwned ? " (owned)" : ""}`
    ).join(" · ") || "None";
    const metaBits = [];
    if (r.demand != null) metaBits.push("Demand " + r.demand);
    if (r.rarityScore != null) metaBits.push("SV # " + r.rarityScore);
    html += `<tr class="item" data-i="${i}" data-status="${esc(st)}" data-conf="${esc(r.confidenceClass)}" data-rarity="${esc((r.rarity || "").toLowerCase())}" data-owned-guess="${r.guessFromOwned ? 1 : 0}">
      <td>
        <div class="sv-cell">
          ${img}
          <div>
            <div class="sv-name">${esc(r.svDisplay)}</div>
            <div class="sv-id">${esc(r.svId)}</div>
            <div class="rarity">${esc(r.rarity || "—")}</div>
            ${metaBits.length ? `<div class="meta">${esc(metaBits.join(" · "))}</div>` : ""}
          </div>
        </div>
      </td>
      <td class="value">${esc(r.valueLabel)}</td>
      <td>
        <div class="game">${esc(r.bestGameId || "???")}</div>
        ${r.guessFromOwned ? '<span class="badge owned">Owned</span>' : '<span class="badge">Guess</span>'}
        <div class="alts"><strong>Alternates:</strong> ${alts}</div>
      </td>
      <td><span class="pill ${esc(r.confidenceClass)}">${esc(r.confidenceLabel)}</span></td>
      <td>
        <div class="mark">
          <button data-act="ok">Correct</button>
          <button data-act="bad">Wrong</button>
          <button data-act="skip">Skip</button>
        </div>
        <input class="custom" placeholder="If wrong: real game ID" value="${esc(custom)}" />
      </td>
    </tr>`;
  });
  tb.innerHTML = html;
  bind();
  applyFilters();
}

function bind() {
  document.querySelectorAll("tr.item").forEach(tr => {
    const row = ROWS[+tr.dataset.i];
    tr.querySelectorAll("button[data-act]").forEach(btn => {
      btn.addEventListener("click", () => {
        saved[row.svId] = saved[row.svId] || {};
        saved[row.svId].status = btn.dataset.act;
        if (btn.dataset.act === "ok" && row.bestGameId) {
          saved[row.svId].custom = row.bestGameId;
          tr.querySelector("input.custom").value = row.bestGameId;
        }
        tr.dataset.status = btn.dataset.act;
        localStorage.setItem(key, JSON.stringify(saved));
        applyFilters();
      });
    });
    const input = tr.querySelector("input.custom");
    input.addEventListener("input", () => {
      saved[row.svId] = saved[row.svId] || {};
      saved[row.svId].custom = input.value.trim();
      localStorage.setItem(key, JSON.stringify(saved));
    });
  });
}

function applyFilters() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const f = document.getElementById("filter").value;
  const rar = document.getElementById("rarityFilter").value.toLowerCase();
  let shown = 0, done = 0;
  document.querySelectorAll("tr.item").forEach(tr => {
    const r = ROWS[+tr.dataset.i];
    const hay = `${r.svDisplay} ${r.svId} ${r.bestGameId || ""} ${r.rarity || ""}`.toLowerCase();
    let ok = true;
    if (q && !hay.includes(q)) ok = false;
    if (rar && (r.rarity || "").toLowerCase() !== rar) ok = false;
    if (f === "todo" && tr.dataset.status) ok = false;
    if (f === "high" && tr.dataset.conf !== "high") ok = false;
    if (f === "mid" && !(tr.dataset.conf === "mid" || tr.dataset.conf === "low")) ok = false;
    if (f === "none" && tr.dataset.conf !== "none") ok = false;
    if (f === "owned-guess" && tr.dataset.ownedGuess !== "1") ok = false;
    tr.classList.toggle("hidden", !ok);
    if (ok) shown += 1;
    if (tr.dataset.status) done += 1;
  });
  // hide empty section headers
  document.querySelectorAll("tr.section-row").forEach(sec => {
    let next = sec.nextElementSibling;
    let any = false;
    while (next && !next.classList.contains("section-row")) {
      if (next.classList.contains("item") && !next.classList.contains("hidden")) any = true;
      next = next.nextElementSibling;
    }
    sec.style.display = any ? "" : "none";
  });
  document.getElementById("stats").textContent = `${shown} showing · ${done} marked · sets excluded`;
}

document.getElementById("q").addEventListener("input", applyFilters);
document.getElementById("filter").addEventListener("change", applyFilters);
document.getElementById("rarityFilter").addEventListener("change", applyFilters);
document.getElementById("exportBtn").addEventListener("click", async () => {
  const lines = ["# SV => gameId corrections", ""];
  for (const r of ROWS) {
    const s = saved[r.svId];
    if (!s || !s.status || s.status === "skip") continue;
    const gameId = s.custom || (s.status === "ok" ? r.bestGameId : "FIXME");
    lines.push(`${r.svId} => ${gameId}`);
  }
  const text = lines.join("\\n");
  try {
    await navigator.clipboard.writeText(text);
    alert("Corrections copied.");
  } catch {
    prompt("Copy these:", text);
  }
});

render();
</script>
</body>
</html>
"""


def main() -> None:
    values = json.loads(VALUES.read_text(encoding="utf-8"))
    game_dump = json.loads(GAME.read_text(encoding="utf-8"))
    sources = game_dump.get("sources") or {}

    images = values.get("images") or {}
    rarities = values.get("rarities") or {}
    meta_map = values.get("meta") or {}
    displays = values.get("displayNames") or {}
    items = values.get("items") or {}
    alias_keys = set((values.get("aliases") or {}).keys())

    raw_game = game_dump.get("gameNames") or []
    game_ids = []
    seen = set()
    for n in raw_game:
        if n in seen or is_junk(n):
            continue
        seen.add(n)
        game_ids.append(n)

    rows = []
    for sv_id, value in items.items():
        if sv_id in alias_keys:
            continue
        rarity = rarities.get(sv_id) or "Unknown"
        if rarity in {"Set", "Pet"}:
            continue

        display = displays.get(sv_id, sv_id)
        cands = []
        for gid in game_ids:
            s = max(score(sv_id, gid), score(display, gid))
            if s >= 0.72:
                cands.append((s, gid, "Owned" in (sources.get(gid) or [])))
        # Prefer owned IDs slightly when scores are close
        cands.sort(key=lambda x: (-x[0], 0 if x[2] else 1, x[1].lower()))
        top = cands[:4]
        best = top[0] if top else None

        if sv_id in KNOWN_GAME_FOR_SV:
            known = KNOWN_GAME_FOR_SV[sv_id]
            best = (1.0, known, "Owned" in (sources.get(known) or []))
            conf_class, conf_label = "high", "Confirmed"
        else:
            conf_class, conf_label = confidence(best[0] if best else None)

        m = meta_map.get(sv_id) or {}
        rows.append(
            {
                "svId": sv_id,
                "svDisplay": display,
                "value": value,
                "valueLabel": fmt_value(value),
                "rarity": rarity,
                "image": images.get(sv_id),
                "demand": m.get("demand"),
                "rarityScore": m.get("rarityScore"),
                "bestGameId": best[1] if best else None,
                "guessFromOwned": bool(best[2]) if best else False,
                "bestScore": round(best[0], 3) if best else None,
                "confidenceClass": conf_class,
                "confidenceLabel": conf_label,
                "knownGameId": KNOWN_GAME_FOR_SV.get(sv_id, ""),
                "alternates": [
                    {"gameId": g, "score": round(s, 3), "fromOwned": owned}
                    for s, g, owned in top[1:]
                ],
            }
        )

    def rarity_rank(r: str) -> int:
        try:
            return RARITY_ORDER.index(r)
        except ValueError:
            return len(RARITY_ORDER)

    rows.sort(key=lambda r: (rarity_rank(r["rarity"]), -float(r["value"] or 0), r["svDisplay"].lower()))

    rarity_opts = "".join(f'<option value="{r.lower()}">{r}</option>' for r in RARITY_ORDER)
    html = (
        HTML.replace("__ROWS__", json.dumps(rows))
        .replace("__RARITY_OPTIONS__", rarity_opts)
    )
    OUT_HTML.write_text(html, encoding="utf-8")
    VOLT_HTML.write_text(html, encoding="utf-8")
    payload = {"count": len(rows), "rows": rows}
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    VOLT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_HTML} ({len(rows)} SV items, sets excluded)")
    print(f"Wrote {VOLT_HTML}")


if __name__ == "__main__":
    main()
