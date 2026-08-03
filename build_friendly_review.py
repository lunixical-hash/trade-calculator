"""Generate a readable HTML name-match review for manual checking."""

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
    # Prefer non-chroma when comparing plain game IDs
    if nb.startswith("chroma") and not na.startswith("chroma"):
        best *= 0.85
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


KNOWN = {
    "SunsetGun": "Sunrise",
    "SunsetKnife": "Sunset",
}


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>MM2 Name Match Review</title>
<style>
  :root {
    --bg: #0f1115;
    --panel: #171a21;
    --row: #1c2029;
    --row2: #1a1e26;
    --text: #e8eaef;
    --muted: #9aa3b2;
    --line: #2a3140;
    --accent: #3db8a0;
    --high: #3ecf8e;
    --mid: #e6b84d;
    --low: #e07a5f;
    --none: #6b7280;
    --chip: #24303a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    font-family: "Segoe UI", system-ui, sans-serif;
    background: radial-gradient(1200px 600px at 10% -10%, #1a3030 0%, var(--bg) 45%);
    color: var(--text);
  }
  header {
    position: sticky; top: 0; z-index: 10;
    backdrop-filter: blur(10px);
    background: rgba(15,17,21,.9);
    border-bottom: 1px solid var(--line);
    padding: 16px 20px 14px;
  }
  h1 { margin: 0 0 6px; font-size: 20px; font-weight: 700; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 12px; max-width: 900px; line-height: 1.4; }
  .controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  input[type="search"] {
    flex: 1; min-width: 220px; max-width: 420px;
    background: var(--panel); color: var(--text);
    border: 1px solid var(--line); border-radius: 10px;
    padding: 10px 12px; font-size: 14px;
  }
  select, button {
    background: var(--panel); color: var(--text);
    border: 1px solid var(--line); border-radius: 10px;
    padding: 9px 12px; font-size: 13px; cursor: pointer;
  }
  button.primary { background: var(--accent); color: #081512; border-color: transparent; font-weight: 700; }
  .stats { color: var(--muted); font-size: 12px; }
  main { padding: 16px 20px 40px; }
  .hint {
    background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
    padding: 12px 14px; margin-bottom: 14px; color: var(--muted); font-size: 13px; line-height: 1.45;
  }
  .hint code { color: var(--accent); }
  table { width: 100%; border-collapse: collapse; }
  th {
    text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: .04em;
    color: var(--muted); padding: 10px 12px; border-bottom: 1px solid var(--line);
    position: sticky; top: 118px; background: #12151b;
  }
  td { padding: 12px; border-bottom: 1px solid var(--line); vertical-align: top; font-size: 14px; }
  tr.item:nth-child(even) td { background: var(--row2); }
  tr.item:nth-child(odd) td { background: var(--row); }
  tr.item:hover td { background: #222833; }
  .game {
    font-family: ui-monospace, Consolas, monospace;
    font-weight: 700; color: #fff;
  }
  .badge {
    display: inline-block; margin-left: 8px; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 700; background: var(--chip); color: var(--muted);
  }
  .badge.owned { color: #b7f5e4; background: #1b3a34; }
  .sv-name { font-weight: 650; }
  .sv-id { color: var(--muted); font-size: 12px; font-family: ui-monospace, Consolas, monospace; margin-top: 3px; }
  .value { font-variant-numeric: tabular-nums; font-weight: 700; }
  .pill {
    display: inline-block; padding: 3px 9px; border-radius: 999px;
    font-size: 11px; font-weight: 700;
  }
  .pill.high { background: rgba(62,207,142,.15); color: var(--high); }
  .pill.mid { background: rgba(230,184,77,.15); color: var(--mid); }
  .pill.low { background: rgba(224,122,95,.15); color: var(--low); }
  .pill.none { background: rgba(107,114,128,.18); color: var(--none); }
  .alts { color: var(--muted); font-size: 12px; line-height: 1.45; }
  .alts strong { color: #c9d1de; font-weight: 600; }
  .mark { display: flex; gap: 6px; flex-wrap: wrap; }
  .mark button {
    padding: 6px 10px; border-radius: 8px; font-size: 12px; font-weight: 700;
  }
  .mark button.ok { border-color: #2f6b52; }
  .mark button.bad { border-color: #7a3d3d; }
  .mark button.skip { border-color: #3d4658; }
  tr.item[data-status="ok"] td { box-shadow: inset 3px 0 0 var(--high); }
  tr.item[data-status="bad"] td { box-shadow: inset 3px 0 0 var(--low); }
  tr.item[data-status="skip"] td { box-shadow: inset 3px 0 0 var(--none); }
  tr.item.hidden { display: none; }
  .custom {
    margin-top: 8px; width: 100%;
    background: #12161d; color: var(--text); border: 1px solid var(--line);
    border-radius: 8px; padding: 7px 9px; font-size: 12px;
  }
  .sv-cell { display: flex; gap: 12px; align-items: flex-start; }
  .thumb {
    width: 56px; height: 56px; border-radius: 10px; object-fit: contain;
    background: #10141b; border: 1px solid var(--line); flex: 0 0 auto;
  }
  .thumb.missing {
    display:grid; place-items:center; color: var(--muted); font-size: 11px;
  }
  .rarity {
    display: inline-block; margin-top: 6px; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 700; background: #2a2438; color: #d2c4ff;
  }
  .meta { color: var(--muted); font-size: 12px; margin-top: 4px; }
  footer { color: var(--muted); font-size: 12px; padding: 8px 20px 24px; }
</style>
</head>
<body>
<header>
  <h1>MM2 Name Match Review</h1>
  <div class="sub">
    Left side = <b>game inventory ID</b> (what Lunix/trades use).
    Right side = closest Supreme Values name guess. Mark Correct / Wrong / Skip, and type the right SV id if needed.
  </div>
  <div class="controls">
    <input id="q" type="search" placeholder="Search game id or SV name..." />
    <select id="filter">
      <option value="owned">Owned items only</option>
      <option value="all">All matched / unmatched</option>
      <option value="todo">Unchecked only</option>
      <option value="high">Likely matches</option>
      <option value="mid">Maybe matches</option>
      <option value="none">No match</option>
      <option value="rarity:godly">Rarity: Godly</option>
      <option value="rarity:ancient">Rarity: Ancient</option>
      <option value="rarity:vintage">Rarity: Vintage</option>
      <option value="rarity:chroma">Rarity: Chroma</option>
      <option value="rarity:legendary">Rarity: Legendary</option>
      <option value="rarity:rare">Rarity: Rare</option>
      <option value="rarity:uncommon">Rarity: Uncommon</option>
      <option value="rarity:common">Rarity: Common</option>
      <option value="rarity:pet">Rarity: Pet</option>
      <option value="rarity:set">Rarity: Set</option>
    </select>
    <select id="sort">
      <option value="owned-first">Sort: Owned first</option>
      <option value="value-desc">Sort: Value high → low</option>
      <option value="value-asc">Sort: Value low → high</option>
      <option value="name">Sort: Name A → Z</option>
    </select>
    <button id="exportBtn" class="primary">Copy my corrections</button>
    <span class="stats" id="stats"></span>
  </div>
</header>
<main>
  <div class="hint">
    Known corrections already applied in aliases:
    <code>SunsetGun → Sunrise</code>,
    <code>SunsetKnife → Sunset</code>.
    When done, click <b>Copy my corrections</b> and paste that back in chat.
  </div>
  <table>
    <thead>
      <tr>
        <th style="width:20%">Game ID</th>
        <th style="width:34%">Best SV match</th>
        <th style="width:10%">Value</th>
        <th style="width:10%">Confidence</th>
        <th style="width:26%">Your call</th>
      </tr>
    </thead>
    <tbody id="tbody"></tbody>
  </table>
</main>
<footer>Saved choices stay in this browser until you clear site data. Export before closing if you want to keep them.</footer>
<script>
const ROWS = __ROWS__;
const KNOWN = __KNOWN__;
const key = "mm2-name-review-v1";
const saved = JSON.parse(localStorage.getItem(key) || "{}");

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

function render() {
  const tb = document.getElementById("tbody");
  tb.innerHTML = ROWS.map((r, i) => {
    const conf = r.confidenceClass;
    const known = KNOWN[r.gameId];
    const st = saved[r.gameId]?.status || "";
    const custom = saved[r.gameId]?.custom || known || "";
    const alts = (r.alternates || []).map(a =>
      `<strong>${esc(a.svDisplay)}</strong> <span>(${esc(a.svId)}, ${esc(a.value)}${a.rarity ? ", " + esc(a.rarity) : ""})</span>`
    ).join(" · ") || "None";
    const img = r.image
      ? `<img class="thumb" src="${esc(r.image)}" alt="" loading="lazy" referrerpolicy="no-referrer" />`
      : `<div class="thumb missing">No img</div>`;
    const rarity = r.rarity ? `<div class="rarity">${esc(r.rarity)}</div>` : "";
    const metaBits = [];
    if (r.demand != null) metaBits.push("Demand " + r.demand);
    if (r.rarityScore != null) metaBits.push("SV rarity # " + r.rarityScore);
    const meta = metaBits.length ? `<div class="meta">${esc(metaBits.join(" · "))}</div>` : "";
    return `<tr class="item" data-i="${i}" data-status="${esc(st)}" data-owned="${r.fromOwned ? 1 : 0}" data-conf="${esc(conf)}" data-rarity="${esc((r.rarity || '').toLowerCase())}">
      <td>
        <div class="game">${esc(r.gameId)}</div>
        ${r.fromOwned ? '<span class="badge owned">Owned</span>' : '<span class="badge">Other</span>'}
        <div class="alts" style="margin-top:8px"><strong>Alternates:</strong> ${alts}</div>
      </td>
      <td>
        <div class="sv-cell">
          ${img}
          <div>
            <div class="sv-name">${esc(r.bestSvDisplay || "No close match")}</div>
            <div class="sv-id">${esc(r.bestSvId || "")}</div>
            ${rarity}
            ${meta}
          </div>
        </div>
      </td>
      <td class="value">${esc(r.bestValueLabel)}</td>
      <td><span class="pill ${conf}">${esc(r.confidenceLabel)}</span></td>
      <td>
        <div class="mark">
          <button class="ok" data-act="ok">Correct</button>
          <button class="bad" data-act="bad">Wrong</button>
          <button class="skip" data-act="skip">Skip</button>
        </div>
        <input class="custom" data-custom="1" placeholder="If wrong: type correct SV id (e.g. TravelersGun)" value="${esc(custom)}" />
      </td>
    </tr>`;
  }).join("");
  bind();
  applyFilters();
}

function bind() {
  document.querySelectorAll("tr.item").forEach(tr => {
    const i = +tr.dataset.i;
    const row = ROWS[i];
    tr.querySelectorAll("button[data-act]").forEach(btn => {
      btn.addEventListener("click", () => {
        saved[row.gameId] = saved[row.gameId] || {};
        saved[row.gameId].status = btn.dataset.act;
        if (btn.dataset.act === "ok" && row.bestSvId) {
          saved[row.gameId].custom = row.bestSvId;
          tr.querySelector("input.custom").value = row.bestSvId;
        }
        tr.dataset.status = btn.dataset.act;
        localStorage.setItem(key, JSON.stringify(saved));
        applyFilters();
      });
    });
    const input = tr.querySelector("input.custom");
    input.addEventListener("input", () => {
      saved[row.gameId] = saved[row.gameId] || {};
      saved[row.gameId].custom = input.value.trim();
      localStorage.setItem(key, JSON.stringify(saved));
    });
  });
}

function applyFilters() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const f = document.getElementById("filter").value;
  const sort = document.getElementById("sort").value;
  const tb = document.getElementById("tbody");
  const trs = [...document.querySelectorAll("tr.item")];

  trs.sort((a, b) => {
    const ra = ROWS[+a.dataset.i];
    const rb = ROWS[+b.dataset.i];
    const va = Number(ra.bestValue);
    const vb = Number(rb.bestValue);
    const aHas = Number.isFinite(va);
    const bHas = Number.isFinite(vb);
    if (sort === "value-desc") {
      if (aHas && bHas) return vb - va;
      if (aHas) return -1;
      if (bHas) return 1;
      return ra.gameId.localeCompare(rb.gameId);
    }
    if (sort === "value-asc") {
      if (aHas && bHas) return va - vb;
      if (aHas) return -1;
      if (bHas) return 1;
      return ra.gameId.localeCompare(rb.gameId);
    }
    if (sort === "name") {
      return ra.gameId.localeCompare(rb.gameId);
    }
    // owned-first
    if (ra.fromOwned !== rb.fromOwned) return ra.fromOwned ? -1 : 1;
    return ra.gameId.localeCompare(rb.gameId);
  });
  trs.forEach(tr => tb.appendChild(tr));

  let shown = 0, owned = 0, done = 0;
  trs.forEach(tr => {
    const i = +tr.dataset.i;
    const r = ROWS[i];
    const hay = `${r.gameId} ${r.bestSvDisplay || ""} ${r.bestSvId || ""} ${r.rarity || ""}`.toLowerCase();
    let ok = true;
    if (q && !hay.includes(q)) ok = false;
    if (f === "owned" && !r.fromOwned) ok = false;
    if (f === "todo" && tr.dataset.status) ok = false;
    if (f === "high" && tr.dataset.conf !== "high") ok = false;
    if (f === "mid" && tr.dataset.conf !== "mid") ok = false;
    if (f === "none" && tr.dataset.conf !== "none") ok = false;
    if (f.startsWith("rarity:") && tr.dataset.rarity !== f.slice(7)) ok = false;
    tr.classList.toggle("hidden", !ok);
    if (ok) shown += 1;
    if (r.fromOwned) owned += 1;
    if (tr.dataset.status) done += 1;
  });
  document.getElementById("stats").textContent =
    `${shown} showing · ${owned} owned · ${done} marked`;
}

document.getElementById("q").addEventListener("input", applyFilters);
document.getElementById("filter").addEventListener("change", applyFilters);
document.getElementById("sort").addEventListener("change", applyFilters);
document.getElementById("exportBtn").addEventListener("click", async () => {
  const lines = ["# MM2 name corrections", "# gameId => svId", ""];
  for (const r of ROWS) {
    const s = saved[r.gameId];
    if (!s || !s.status) continue;
    if (s.status === "skip") continue;
    if (s.status === "ok") {
      const id = s.custom || r.bestSvId;
      if (id) lines.push(`${r.gameId} => ${id}`);
    } else if (s.status === "bad") {
      lines.push(`${r.gameId} => ${s.custom || "FIXME"}`);
    }
  }
  const text = lines.join("\\n");
  try {
    await navigator.clipboard.writeText(text);
    alert("Corrections copied to clipboard.");
  } catch {
    prompt("Copy these corrections:", text);
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

    sv = []
    for sv_id, display in (values.get("displayNames") or {}).items():
        sv.append((sv_id, display, values.get("items", {}).get(sv_id)))

    raw = game_dump.get("gameNames") or []
    owned = [n for n in raw if "Owned" in (sources.get(n) or [])]
    game_ids = []
    seen = set()
    for pool in (owned, raw):
        for n in pool:
            if n in seen or is_junk(n):
                continue
            seen.add(n)
            game_ids.append(n)
    game_ids.sort(key=str.lower)

    # Owned first in HTML
    game_ids.sort(key=lambda g: (0 if "Owned" in (sources.get(g) or []) else 1, g.lower()))

    def enrich(sv_id: str | None) -> dict:
        if not sv_id:
            return {}
        m = meta_map.get(sv_id) or {}
        return {
            "image": images.get(sv_id),
            "rarity": rarities.get(sv_id),
            "demand": m.get("demand"),
            "rarityScore": m.get("rarityScore"),
        }

    rows = []
    for gid in game_ids:
        cands = []
        for sv_id, display, val in sv:
            s = max(score(gid, sv_id), score(gid, display))
            if s >= 0.72:
                cands.append((s, sv_id, display, val))
        cands.sort(key=lambda x: (-x[0], x[2].lower()))
        top = cands[:4]
        best = top[0] if top else None
        conf_class, conf_label = confidence(best[0] if best else None)

        # Prefer known corrections for display
        if gid in KNOWN:
            known_sv = KNOWN[gid]
            known_display = (values.get("displayNames") or {}).get(known_sv, known_sv)
            known_val = (values.get("items") or {}).get(known_sv)
            best = (1.0, known_sv, known_display, known_val)
            conf_class, conf_label = "high", "Confirmed"

        best_id = best[1] if best else None
        extra = enrich(best_id)

        rows.append(
            {
                "gameId": gid,
                "fromOwned": "Owned" in (sources.get(gid) or []),
                "bestSvId": best_id,
                "bestSvDisplay": best[2] if best else None,
                "bestValue": best[3] if best else None,
                "bestValueLabel": fmt_value(best[3] if best else None),
                "bestScore": round(best[0], 3) if best else None,
                "confidenceClass": conf_class,
                "confidenceLabel": conf_label,
                "image": extra.get("image"),
                "rarity": extra.get("rarity"),
                "demand": extra.get("demand"),
                "rarityScore": extra.get("rarityScore"),
                "alternates": [
                    {
                        "svId": i,
                        "svDisplay": d,
                        "value": fmt_value(v),
                        "score": round(s, 3),
                        "rarity": rarities.get(i),
                    }
                    for s, i, d, v in top[1:]
                ],
            }
        )

    html = (
        HTML.replace("__ROWS__", json.dumps(rows))
        .replace("__KNOWN__", json.dumps(KNOWN))
    )
    OUT_HTML.write_text(html, encoding="utf-8")
    VOLT_HTML.write_text(html, encoding="utf-8")

    payload = {"knownCorrections": KNOWN, "rows": rows}
    OUT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    VOLT_JSON.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Wrote {OUT_HTML}")
    print(f"Wrote {VOLT_HTML}")
    print(f"Rows: {len(rows)} | Owned: {sum(1 for r in rows if r['fromOwned'])}")


if __name__ == "__main__":
    main()
