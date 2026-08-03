"""
Scrapes MM2 item values from supremevalues.com and writes mm2_values.json.

Captures: value, display name, image URL, category rarity, demand, rarity score,
origin/change/aliases, rise chance, per-item value history (accumulated across scrapes),
and homepage trending items.

Usage:
  python scrape_mm2_values.py
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from catalog_fixes import apply_to_values_payload, sanitize_item_history

ROOT = Path(__file__).resolve().parent
OUT_FILE = ROOT / "mm2_values.json"
NAME_MAP_FILE = ROOT / "name_map.json"
ALIASES_FILE = ROOT / "aliases.json"
HISTORY_MAX_POINTS = 120

# Categories where SV embeds per-item chart history on ?item= pages
HISTORY_CATEGORIES = {"Godly", "Ancient", "Chroma", "Set"}
HISTORY_MIN_SET_VALUE = 50.0

VOLT_WORKSPACE_COPY = (
    Path.home() / "AppData" / "Local" / "Volt" / "workspace" / "mm2_values.json"
)

PAGES = [
    ("https://supremevalues.com/mm2/godlies", "Godly"),
    ("https://supremevalues.com/mm2/ancients", "Ancient"),
    ("https://supremevalues.com/mm2/vintages", "Vintage"),
    ("https://supremevalues.com/mm2/chromas", "Chroma"),
    ("https://supremevalues.com/mm2/uniques", "Unique"),
    ("https://supremevalues.com/mm2/evos", "Evo"),
    ("https://supremevalues.com/mm2/legendaries", "Legendary"),
    ("https://supremevalues.com/mm2/rares", "Rare"),
    ("https://supremevalues.com/mm2/uncommons", "Uncommon"),
    ("https://supremevalues.com/mm2/commons", "Common"),
    ("https://supremevalues.com/mm2/pets", "Pet"),
    ("https://supremevalues.com/mm2/sets", "Set"),
]

HOME_URL = "https://supremevalues.com/mm2/"


def load_name_map() -> dict[str, str]:
    if not NAME_MAP_FILE.exists():
        return {}
    return json.loads(NAME_MAP_FILE.read_text(encoding="utf-8"))


def load_aliases() -> dict[str, str]:
    if not ALIASES_FILE.exists():
        return {}
    return json.loads(ALIASES_FILE.read_text(encoding="utf-8"))


def load_previous_payload() -> dict:
    if not OUT_FILE.exists():
        return {}
    try:
        data = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def to_game_name(display_name: str, name_map: dict[str, str]) -> str | None:
    display_name = display_name.strip()
    if display_name.lower().startswith("contains"):
        return None
    if display_name in name_map:
        return name_map[display_name]

    paren = re.match(r"^(.+?)\s*\((Gun|Knife)\)$", display_name, re.I)
    if paren:
        base = re.sub(r"[^A-Za-z0-9]+", "", paren.group(1))
        return f"Chroma{base}{paren.group(2).title()}"

    poss = re.match(r"^(.+)'s\s+(Gun|Knife|Axe|Edge)$", display_name, re.I)
    if poss:
        base = re.sub(r"[^A-Za-z0-9]+", "", poss.group(1))
        return f"{base}{poss.group(2).title()}"

    poss2 = re.match(r"^(.+?)s\s+(Gun|Knife|Axe|Edge)$", display_name, re.I)
    if poss2 and not re.search(r"\s", poss2.group(1).strip()):
        base = re.sub(r"[^A-Za-z0-9]+", "", poss2.group(1))
        return f"{base}s{poss2.group(2).title()}"

    return re.sub(r"[^A-Za-z0-9]+", "", display_name)


def parse_change_pct(change: str | None) -> float:
    if not change or not isinstance(change, str):
        return 0.0
    m = re.search(r"([+\-−])\s*([0-9]+(?:\.[0-9]+)?)\s*%", change)
    if not m:
        return 0.0
    sign = -1.0 if m.group(1) in {"-", "−"} else 1.0
    return sign * float(m.group(2))


PARSE_ITEM_JS = """
(text) => {
  text = (text || '').replace(/\\s+/g, ' ').trim();
  if (!/Value\\s*-/i.test(text)) return null;

  let name = '';
  const before = text.split(/Value\\s*-/i)[0].trim();
  const parts = before.split(/\\s{2,}|\\n/).map(s => s.trim()).filter(Boolean);
  name = parts[parts.length - 1] || before;
  if (!name || name.length > 80) return null;

  const valueMatch = text.match(/Value\\s*-\\s*([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*([kKmMbB]?)/i);
  if (!valueMatch) return null;
  let value = parseFloat(valueMatch[1].replace(/,/g, ''));
  const suf = (valueMatch[2] || '').toLowerCase();
  if (suf === 'k') value *= 1000;
  if (suf === 'm') value *= 1000000;
  if (suf === 'b') value *= 1000000000;

  const demandMatch = text.match(/Demand\\s*-\\s*([0-9]+)/i);
  const rarityMatch = text.match(/Rarity\\s*-\\s*([0-9]+)/i);
  const stabilityMatch = text.match(/Stability\\s*-\\s*([A-Za-z ]+?)(?:\\s*Demand|\\s*Rarity|$)/i);
  const originMatch = text.match(/Origin\\s*-\\s*(.+?)(?:\\s+Change in Value|\\s+Inv\\.|\\s+Aliases|$)/i);
  const changeMatch = text.match(/Change in Value\\s*-\\s*(\\([^)]+\\)\\s*[+\\-]?[0-9.]+%)/i);
  const aliasesMatch = text.match(/Aliases\\s*-\\s*(.+?)(?:\\s+Flippability|\\s+Chance of Rising|\\s+View Item|$)/i);
  const riseMatch = text.match(/Chance of Rising\\s*-\\s*([0-9]+)/i);
  const flipMatch = text.match(/Flippability\\s*-\\s*([A-Za-z ]+?)(?:\\s+Chance|\\s+View|$)/i);

  return {
    name,
    value,
    demand: demandMatch ? Number(demandMatch[1]) : null,
    rarityScore: rarityMatch ? Number(rarityMatch[1]) : null,
    stability: stabilityMatch ? stabilityMatch[1].trim() : null,
    origin: originMatch ? originMatch[1].trim() : null,
    change: changeMatch ? changeMatch[1].trim() : null,
    aliases: aliasesMatch ? aliasesMatch[1].trim() : null,
    riseChance: riseMatch ? Number(riseMatch[1]) : null,
    flippability: flipMatch ? flipMatch[1].trim() : null,
  };
}
"""


EXTRACT_SV_POPUP_JS = """
() => {
  if (typeof _svPopup === 'undefined' || !_svPopup) return [];
  const rows = [];
  for (const [name, d] of Object.entries(_svPopup)) {
    if (!d || typeof d !== 'object') continue;
    let value = d.rawValue;
    if (typeof value !== 'number') {
      const raw = String(d.value || '').replace(/,/g, '');
      value = parseFloat(raw);
    }
    if (!Number.isFinite(value)) continue;
    const imageKey = d.imageKey || '';
    const image = imageKey
      ? ('https://supremevalues.com/media/' + imageKey + '.webp')
      : null;
    const itemSlug = imageKey ? String(imageKey).split('/').pop() : null;
    const diff = d.diff != null && String(d.diff).trim() !== '' ? String(d.diff).trim() : null;
    const pct = d.pctChange != null ? String(d.pctChange).trim() : null;
    let change = null;
    if (diff != null && pct) {
      const signed = /^[+\\-]/.test(diff) ? diff : ((Number(diff) > 0 ? '+' : '') + diff);
      change = '(' + signed + ') ' + pct;
    } else if (pct) {
      change = pct;
    }
    let riseChance = d.riseChance != null ? Number(d.riseChance) : null;
    if (!Number.isFinite(riseChance)) riseChance = null;
    rows.push({
      name,
      value,
      image,
      imageKey,
      itemSlug,
      demand: d.demand != null ? Number(d.demand) : null,
      rarityScore: d.rarity != null ? Number(d.rarity) : null,
      stability: d.stability || null,
      origin: d.origin || null,
      change,
      aliases: d.aliases || null,
      riseChance,
      flippability: d.flippability || null,
      range: d.range || null,
    });
  }
  return rows;
}
"""


def scrape_trending_and_changelog(page) -> tuple[list[dict], str | None]:
    """Pull Trending Items + latest update blurb from the MM2 home page."""
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=90_000)
    page.wait_for_timeout(2_000)
    data = page.evaluate(
        """() => {
          const body = (document.body.innerText || '').replace(/\\r/g, '');
          let trending = [];
          const tIdx = body.search(/Trending Items/i);
          if (tIdx >= 0) {
            const chunk = body.slice(tIdx, tIdx + 1800);
            const stop = chunk.search(/\\nSupreme Value Team|\\nSUPREME VALUES UPDATE|\\nView Update/i);
            const block = stop > 0 ? chunk.slice(0, stop) : chunk;
            const re = /([A-Za-z0-9][A-Za-z0-9'\\.\\- ]+?)\\s+Value\\s*-\\s*([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*(?:\\[[^\\]]*\\])?\\s*Stability\\s*-\\s*([A-Za-z ]+?)\\s+Change in Value\\s*-\\s*(\\([^)]+\\))/g;
            let m;
            while ((m = re.exec(block)) !== null) {
              trending.push({
                name: m[1].trim(),
                value: parseFloat(m[2].replace(/,/g, '')),
                stability: m[3].trim(),
                change: m[4].trim(),
              });
            }
          }
          let changelog = null;
          const cIdx = body.search(/SUPREME VALUES UPDATE\\s+\\d{1,2}\\/\\d{1,2}\\/\\d{4}/i);
          if (cIdx >= 0) {
            changelog = body.slice(cIdx, cIdx + 2200).trim();
          }
          return { trending, changelog };
        }"""
    )
    trending = data.get("trending") if isinstance(data, dict) else []
    changelog = data.get("changelog") if isinstance(data, dict) else None
    if not isinstance(trending, list):
        trending = []
    if changelog is not None:
        changelog = str(changelog)[:2500]
    return trending, changelog


def scrape_page(page, url: str, category: str) -> list[dict]:
    page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    try:
        page.wait_for_selector('img[src*="/media/mm2"]', timeout=45_000)
    except Exception:
        pass
    page.wait_for_timeout(2_500)
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(1_200)
    page.evaluate("() => window.scrollTo(0, 0)")
    page.wait_for_timeout(400)

    raw = page.evaluate(EXTRACT_SV_POPUP_JS)
    if not isinstance(raw, list) or not raw:
        raw = page.evaluate(
            """() => {
          const rows = [];
          const seen = new Set();
          for (const img of document.querySelectorAll('img')) {
            const src = img.currentSrc || img.src || '';
            if (!src) continue;
            if (!src.includes('/media/mm2')) continue;
            if (src.includes('/media/icons/')) continue;
            if (src.includes('/media/stability/')) continue;
            if (src.includes('/media/headers/')) continue;
            if (src.endsWith('/media/N_A.png')) continue;

            const block = img.closest('a,div,article,section,li') || img.parentElement;
            let text = (block?.innerText || '').replace(/\\s+/g, ' ').trim();
            let el = block;
            for (let i = 0; i < 6 && el; i++) {
              const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
              if (/Origin\\s*-/i.test(t) && t.length < 2500) { text = t; break; }
              el = el.parentElement;
            }
            if (!/Value\\s*-/i.test(text)) continue;

            let name = '';
            const before = text.split(/Value\\s*-/i)[0].trim();
            const parts = before.split(/\\s{2,}|\\n/).map(s => s.trim()).filter(Boolean);
            name = parts[parts.length - 1] || before;
            if (!name || name.length > 60) name = (img.alt || '').trim();
            if (!name) continue;

            const valueMatch = text.match(/Value\\s*-\\s*([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*([kKmMbB]?)/i);
            if (!valueMatch) continue;
            let value = parseFloat(valueMatch[1].replace(/,/g, ''));
            const suf = (valueMatch[2] || '').toLowerCase();
            if (suf === 'k') value *= 1000;
            if (suf === 'm') value *= 1000000;
            if (suf === 'b') value *= 1000000000;

            const demandMatch = text.match(/Demand\\s*-\\s*([0-9]+)/i);
            const rarityMatch = text.match(/Rarity\\s*-\\s*([0-9]+)/i);
            const stabilityMatch = text.match(/Stability\\s*-\\s*([A-Za-z ]+?)(?:\\s*Demand|\\s*Rarity|$)/i);
            const originMatch = text.match(/Origin\\s*-\\s*(.+?)(?:\\s+Change in Value|\\s+Inv\\.|\\s+Aliases|$)/i);
            const changeMatch = text.match(/Change in Value\\s*-\\s*(\\([^)]+\\)\\s*[+\\-]?[0-9.]+%)/i);
            const aliasesMatch = text.match(/Aliases\\s*-\\s*(.+?)(?:\\s+Flippability|\\s+Chance of Rising|\\s+View Item|$)/i);
            const riseMatch = text.match(/Chance of Rising\\s*-\\s*([0-9]+)/i);

            const key = name + '|' + value + '|' + src;
            if (seen.has(key)) continue;
            seen.add(key);

            rows.push({
              name,
              value,
              image: src,
              demand: demandMatch ? Number(demandMatch[1]) : null,
              rarityScore: rarityMatch ? Number(rarityMatch[1]) : null,
              stability: stabilityMatch ? stabilityMatch[1].trim() : null,
              origin: originMatch ? originMatch[1].trim() : null,
              change: changeMatch ? changeMatch[1].trim() : null,
              aliases: aliasesMatch ? aliasesMatch[1].trim() : null,
              riseChance: riseMatch ? Number(riseMatch[1]) : null,
              flippability: null,
            });
          }
          return rows;
        }"""
        )

    need_detail = [
        r
        for r in raw
        if not r.get("origin") or not r.get("aliases") or r.get("riseChance") is None
    ]
    for row in need_detail[:60]:
        src = row.get("image") or ""
        if not src:
            continue
        opened = page.evaluate(
            """(src) => {
              for (const img of document.querySelectorAll('img')) {
                const s = img.currentSrc || img.src || '';
                if (s === src || s.replace(/\\.webp$/i, '.png') === src.replace(/\\.webp$/i, '.png')) {
                  img.click();
                  return true;
                }
              }
              return false;
            }""",
            src,
        )
        if not opened:
            continue
        page.wait_for_timeout(250)
        detail = page.evaluate(
            """() => {
              const body = (document.body.innerText || '').replace(/\\s+/g, ' ');
              const idx = body.search(/Extra Features:\\s*/i);
              if (idx >= 0) return body.slice(idx, idx + 900);
              return body;
            }"""
        )
        parsed = page.evaluate(PARSE_ITEM_JS, detail)
        if isinstance(parsed, dict):
            for key in (
                "demand",
                "rarityScore",
                "stability",
                "origin",
                "change",
                "aliases",
                "riseChance",
                "flippability",
            ):
                if parsed.get(key) is not None:
                    row[key] = parsed[key]
            if parsed.get("name") and not row.get("name"):
                row["name"] = parsed["name"]
            if parsed.get("value") is not None:
                row["value"] = parsed["value"]
        page.keyboard.press("Escape")
        page.wait_for_timeout(80)

    # Pull full SV chart history from each item's ?item= page (embedded in _svPopup)
    if category in HISTORY_CATEGORIES and raw:
        history_hits = scrape_sv_item_histories(page, url, raw, category)
        for name, points in history_hits.items():
            for row in raw:
                if row.get("name") == name:
                    row["svHistory"] = points
                    break

    results: list[dict] = []
    seen_names: set[str] = set()
    for row in raw:
        name = str(row.get("name") or "").strip()
        if not name or name.lower().startswith("class"):
            continue
        value = row.get("value")
        if not isinstance(value, (int, float)):
            continue
        image = row.get("image") or ""
        if image.startswith("//"):
            image = "https:" + image

        img_name = _display_from_image(image)
        if img_name and (
            "special tier" in name.lower()
            or name.lower().startswith("nik")
            or _looks_like_short_code_name(name)
        ):
            name = img_name

        if name in seen_names:
            continue
        seen_names.add(name)
        results.append(
            {
                "displayName": name,
                "value": float(value),
                "image": image,
                "category": category,
                "demand": row.get("demand"),
                "rarityScore": row.get("rarityScore"),
                "stability": row.get("stability"),
                "origin": row.get("origin"),
                "change": row.get("change"),
                "aliases": row.get("aliases"),
                "riseChance": row.get("riseChance"),
                "flippability": row.get("flippability"),
                "svHistory": row.get("svHistory"),
                "itemSlug": row.get("itemSlug"),
            }
        )
    return results


def _parse_sv_time(value) -> int | None:
    """Parse SV history timestamps like '2026-06-12 21:18:43' to unix seconds.

    SV emits naive wall-clock strings with no timezone. We treat them as local
    time so the calendar day in labels matches the site (and prior scrapes).
    Prefer the date portion of the original string for display labels.
    """
    if isinstance(value, (int, float)) and value > 1_000_000:
        # Seconds vs ms
        iv = int(value)
        if iv > 10_000_000_000:  # ms
            return iv // 1000
        return iv
    if not isinstance(value, str):
        return None
    s = value.strip()
    for fmt, width in (
        ("%Y-%m-%d %H:%M:%S", 19),
        ("%Y-%m-%d", 10),
        ("%m/%d/%Y", 10),
        ("%m/%d/%y", 8),
    ):
        try:
            return int(time.mktime(time.strptime(s[:width], fmt)))
        except ValueError:
            continue
    return None


def _sv_label_from_raw(t_raw, ts: int | None) -> str | None:
    """Prefer the calendar date from SV's own timestamp string."""
    if isinstance(t_raw, str):
        s = t_raw.strip()
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return s[:10]
        for fmt, width in (("%m/%d/%Y", 10), ("%m/%d/%y", 8)):
            try:
                st = time.strptime(s[:width], fmt)
                return time.strftime("%Y-%m-%d", st)
            except ValueError:
                continue
    if ts is not None:
        return time.strftime("%Y-%m-%d", time.localtime(ts))
    return None


def scrape_sv_item_histories(
    page,
    category_url: str,
    raw: list[dict],
    category: str,
) -> dict[str, list[dict]]:
    """
    Visit each item's ?item=<slug> page and read _svPopup[name].history.

    SV only embeds the chart series for the focused item on that URL.
    """
    out: dict[str, list[dict]] = {}
    base = category_url.split("?")[0].rstrip("/")
    targets: list[tuple[str, str]] = []
    for row in raw:
        name = row.get("name")
        value = row.get("value")
        if not isinstance(name, str) or not name.strip():
            continue
        name = name.strip()
        # Sets use a name-derived slug on SV (?item=Chroma_Ever_Set), not imageKey.
        if category == "Set":
            slug = re.sub(r"[^A-Za-z0-9\s]", "", name).strip().replace(" ", "_")
            if not isinstance(value, (int, float)) or float(value) < HISTORY_MIN_SET_VALUE:
                continue
        else:
            slug = row.get("itemSlug")
            if not isinstance(slug, str) or not slug.strip():
                image = str(row.get("image") or "")
                if image:
                    slug = Path(urlparse(image).path).name.rsplit(".", 1)[0]
            if not isinstance(slug, str) or not slug.strip():
                continue
            slug = slug.strip()
        targets.append((name, slug))

    # Highest value first (more useful if interrupted)
    targets.sort(
        key=lambda pair: next(
            (
                float(r["value"])
                for r in raw
                if r.get("name") == pair[0] and isinstance(r.get("value"), (int, float))
            ),
            0.0,
        ),
        reverse=True,
    )

    print(f"    history pages: {len(targets)}")
    for i, (name, slug) in enumerate(targets, start=1):
        item_url = f"{base}?item={slug}"
        try:
            page.goto(item_url, wait_until="domcontentloaded", timeout=60_000)
            # Wait briefly for _svPopup history injection
            page.wait_for_timeout(700)
            points = page.evaluate(
                """(wantName) => {
                  if (typeof _svPopup === 'undefined' || !_svPopup) return [];
                  let d = _svPopup[wantName];
                  if (!d || !Array.isArray(d.history) || !d.history.length) {
                    // focused item is usually the only one with history
                    for (const [n, row] of Object.entries(_svPopup)) {
                      if (row && Array.isArray(row.history) && row.history.length) {
                        d = row;
                        wantName = n;
                        break;
                      }
                    }
                  }
                  if (!d || !Array.isArray(d.history)) return [];
                  return d.history.map((p) => ({
                    v: Number(p && p.v),
                    t: (p && p.t != null) ? p.t : null,
                    label: (p && p.label != null) ? String(p.label) : null,
                  })).filter((p) => Number.isFinite(p.v));
                }""",
                name,
            )
        except Exception as e:
            print(f"      history fail {name}: {e}")
            continue

        if not isinstance(points, list) or len(points) < 2:
            if i <= 5 or i % 25 == 0:
                print(f"      [{i}/{len(targets)}] {name}: no history")
            continue

        cleaned: list[dict] = []
        for p in points:
            if not isinstance(p, dict):
                continue
            v = p.get("v")
            if not isinstance(v, (int, float)):
                continue
            entry: dict = {"v": float(v)}
            t_raw = p.get("t")
            ts = _parse_sv_time(t_raw)
            if ts is not None:
                entry["t"] = ts
            label = _sv_label_from_raw(t_raw, ts)
            if label is None and isinstance(p.get("label"), str) and p["label"].strip():
                label = p["label"].strip()
            if label:
                entry["label"] = label
            cleaned.append(entry)

        if len(cleaned) >= 2:
            out[name] = cleaned[-HISTORY_MAX_POINTS:]
            if i <= 8 or i % 25 == 0:
                print(f"      [{i}/{len(targets)}] {name}: {len(cleaned)} points")

    # Return to category listing for cleanliness
    try:
        page.goto(base, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(400)
    except Exception:
        pass
    return out


def merge_item_history(
    prev_meta: dict,
    game_name: str,
    value: float,
    updated_at: int,
    sv_history: list[dict] | None,
) -> list[dict]:
    """Combine prior scrape history with SV chart points + current value.

    Prefer authoritative SV timestamps. Do not invent prior dates from % change.
    Same-second SV updates with different values are kept (key includes value).
    Unchanged tips keep their original SV timestamp (scrape time is not a move).
    """
    by_key: dict[str, dict] = {}
    seq_counter = 0

    def add_point(entry: dict, *, prefer_new: bool = False, seq: int | None = None) -> None:
        nonlocal seq_counter
        v = entry.get("v")
        if not isinstance(v, (int, float)):
            return
        point: dict = {"v": float(v)}
        if isinstance(entry.get("t"), (int, float)):
            point["t"] = int(entry["t"])
        if isinstance(entry.get("label"), str) and entry["label"].strip():
            point["label"] = entry["label"].strip()
        if seq is not None:
            point["_seq"] = int(seq)
        else:
            point["_seq"] = seq_counter
            seq_counter += 1
        # Include value in the key so same-second SV ticks (45 then 43) survive.
        if "t" in point:
            key = f"t:{point['t']}:v:{point['v']}"
        elif "label" in point:
            key = f"l:{point['label']}:v:{point['v']}"
        else:
            key = f"v:{point['v']}:{point['_seq']}"
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = point
            return
        # Prefer the copy that already has a calendar label / keep existing.
        if prefer_new or ("label" in point and "label" not in prev):
            # Keep earlier sequence when replacing so order stays stable
            if "_seq" in prev and "_seq" not in point:
                point["_seq"] = prev["_seq"]
            by_key[key] = point

    prev = prev_meta.get(game_name) if isinstance(prev_meta.get(game_name), dict) else {}
    old = prev.get("history") if isinstance(prev, dict) else None
    if isinstance(old, list):
        for p in old:
            if isinstance(p, dict):
                add_point(p)

    if isinstance(sv_history, list):
        for i, p in enumerate(sv_history):
            if not isinstance(p, dict):
                continue
            entry: dict = {"v": p.get("v")}
            t_raw = p.get("t")
            if isinstance(t_raw, (int, float)):
                entry["t"] = int(t_raw) if t_raw < 10_000_000_000 else int(t_raw) // 1000
            else:
                ts = _parse_sv_time(t_raw)
                if ts is not None:
                    entry["t"] = ts
            label = None
            if isinstance(p.get("label"), str) and p["label"].strip():
                label = p["label"].strip()
            else:
                label = _sv_label_from_raw(t_raw, entry.get("t"))
            if label:
                entry["label"] = label
            # SV array order is authoritative for same-second updates
            add_point(entry, prefer_new=True, seq=10_000 + i)

    hist = list(by_key.values())
    hist.sort(
        key=lambda p: (
            p.get("t") is None,
            p.get("t") or 0,
            p.get("_seq") or 0,
        )
    )
    for p in hist:
        p.pop("_seq", None)
    # Drop wrong-scale / synthetic points before deciding on the tip
    hist = sanitize_item_history(hist, value)

    # If value moved since last known point, record the scrape tip — but never
    # invent a fake "yesterday" prior from % change or previous catalog value.
    if not hist:
        hist = [
            {
                "t": updated_at,
                "v": float(value),
                "label": time.strftime("%Y-%m-%d", time.localtime(updated_at)),
            }
        ]
    elif abs(hist[-1]["v"] - value) >= 0.5:
        hist.append(
            {
                "t": updated_at,
                "v": float(value),
                "label": time.strftime("%Y-%m-%d", time.localtime(updated_at)),
            }
        )
    # else: tip value already matches — keep the authoritative SV/scrape stamp

    return sanitize_item_history(hist, value)[-HISTORY_MAX_POINTS:]


def _looks_like_short_code_name(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9]{2,8}", name.strip()))


def _display_from_image(image: str) -> str | None:
    if not image:
        return None
    stem = Path(urlparse(image).path).name.rsplit(".", 1)[0]
    if not stem or stem in {"N_A", "na", "unknown"}:
        return None
    if re.fullmatch(r"[A-Z0-9]{2,8}", stem):
        return None
    if "_" in stem:
        return stem.replace("_", " ").strip()
    if re.search(r"[a-z]", stem) and len(stem) >= 5:
        return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem).strip()
    return None


def main() -> None:
    name_map = load_name_map()
    aliases = load_aliases()
    previous = load_previous_payload()
    prev_items = previous.get("items") if isinstance(previous.get("items"), dict) else {}
    prev_meta = previous.get("meta") if isinstance(previous.get("meta"), dict) else {}
    enriched_prev_meta: dict[str, dict] = {}
    for k, m in prev_meta.items():
        row = dict(m) if isinstance(m, dict) else {}
        if k in prev_items and isinstance(prev_items[k], (int, float)):
            row["_prevValue"] = float(prev_items[k])
        enriched_prev_meta[k] = row

    items: dict[str, float] = {}
    display_names: dict[str, str] = {}
    images: dict[str, str] = {}
    rarities: dict[str, str] = {}
    meta: dict[str, dict] = {}
    trending_out: list[dict] = []
    changelog: str | None = None
    updated_at = int(time.time())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()

        print(f"Scraping home trends: {HOME_URL} ...")
        try:
            trending_raw, changelog = scrape_trending_and_changelog(page)
            print(f"  trending {len(trending_raw)} items")
        except Exception as e:
            trending_raw = []
            print(f"  FAILED trends: {e}")

        for url, category in PAGES:
            print(f"Scraping {category}: {url} ...")
            try:
                found = scrape_page(page, url, category)
                print(f"  found {len(found)} items")
                for row in found:
                    game_name = to_game_name(row["displayName"], name_map)
                    if not game_name:
                        continue
                    if game_name in items:
                        continue
                    items[game_name] = row["value"]
                    display_names[game_name] = row["displayName"]
                    if row.get("image"):
                        images[game_name] = row["image"]
                    rarities[game_name] = category
                    history = merge_item_history(
                        enriched_prev_meta,
                        game_name,
                        float(row["value"]),
                        updated_at,
                        row.get("svHistory")
                        if isinstance(row.get("svHistory"), list)
                        else None,
                    )
                    meta[game_name] = {
                        "demand": row.get("demand"),
                        "rarityScore": row.get("rarityScore"),
                        "stability": row.get("stability"),
                        "origin": row.get("origin"),
                        "change": row.get("change"),
                        "aliases": row.get("aliases"),
                        "riseChance": row.get("riseChance"),
                        "flippability": row.get("flippability"),
                        "history": history,
                        "changePct": parse_change_pct(row.get("change")),
                    }
            except Exception as e:
                print(f"  FAILED: {e}")

        browser.close()

    for t in trending_raw:
        name = t.get("name")
        if not isinstance(name, str):
            continue
        gid = to_game_name(name, name_map)
        trending_out.append(
            {
                "name": name,
                "id": gid if gid in items else None,
                "value": t.get("value"),
                "stability": t.get("stability"),
                "change": t.get("change"),
            }
        )

    clean_aliases = {
        src: dst for src, dst in aliases.items() if isinstance(src, str) and dst in items
    }

    for src, dst in clean_aliases.items():
        if dst in items and src not in items:
            items[src] = items[dst]
        if dst in display_names and src not in display_names:
            display_names[src] = display_names[dst]
        if dst in images and src not in images:
            images[src] = images[dst]
        if dst in rarities and src not in rarities:
            rarities[src] = rarities[dst]
        if dst in meta and src not in meta:
            meta[src] = meta[dst]

    payload = apply_to_values_payload(
        {
            "updatedAt": updated_at,
            "source": "supremevalues.com",
            "count": len(items),
            "items": items,
            "displayNames": display_names,
            "images": images,
            "rarities": rarities,
            "meta": meta,
            "aliases": clean_aliases,
            "trending": trending_out,
            "changelog": changelog,
        }
    )
    text = json.dumps(payload, indent=2)
    OUT_FILE.write_text(text, encoding="utf-8")
    hist_n = sum(1 for m in meta.values() if isinstance(m, dict) and m.get("history"))
    print(
        f"Wrote {OUT_FILE} ({len(items)} items, {len(images)} images, "
        f"{len(rarities)} rarities, {len(clean_aliases)} aliases, "
        f"{hist_n} with history, {len(trending_out)} trending)"
    )

    try:
        VOLT_WORKSPACE_COPY.parent.mkdir(parents=True, exist_ok=True)
        VOLT_WORKSPACE_COPY.write_text(text, encoding="utf-8")
        print(f"Copied to {VOLT_WORKSPACE_COPY}")
    except OSError as e:
        print(f"Could not copy to Volt workspace: {e}")


if __name__ == "__main__":
    main()
