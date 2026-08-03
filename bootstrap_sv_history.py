"""
Pull Supreme Values chart history into mm2_values.json without a full scrape.

Visits each Godly / Ancient / Chroma / Set item page (?item=slug) and reads
_svPopup[name].history, then merges into meta[id].history.

Usage:
  python bootstrap_sv_history.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from catalog_fixes import apply_to_values_payload
from scrape_mm2_values import (
    HISTORY_CATEGORIES,
    HISTORY_MIN_SET_VALUE,
    PAGES,
    EXTRACT_SV_POPUP_JS,
    load_name_map,
    merge_item_history,
    scrape_sv_item_histories,
    to_game_name,
)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "mm2_values.json"
VOLT = Path.home() / "AppData" / "Local" / "Volt" / "workspace" / "mm2_values.json"


def main() -> None:
    data = json.loads(OUT.read_text(encoding="utf-8"))
    items = data.get("items") or {}
    meta = data.setdefault("meta", {})
    displays = data.get("displayNames") or {}
    rarities = data.get("rarities") or {}
    name_map = load_name_map()
    updated_at = int(time.time())

    # display name -> catalog id
    by_display: dict[str, str] = {}
    for item_id, dname in displays.items():
        if isinstance(dname, str) and dname.strip():
            by_display.setdefault(dname.strip(), item_id)

    enriched_prev: dict[str, dict] = {}
    for k, m in meta.items():
        row = dict(m) if isinstance(m, dict) else {}
        if k in items and isinstance(items[k], (int, float)):
            row["_prevValue"] = float(items[k])
        enriched_prev[k] = row

    total_hits = 0
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

        for url, category in PAGES:
            if category not in HISTORY_CATEGORIES:
                continue
            print(f"History for {category}: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            try:
                page.wait_for_selector('img[src*="/media/mm2"]', timeout=45_000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            raw = page.evaluate(EXTRACT_SV_POPUP_JS)
            if not isinstance(raw, list) or not raw:
                print("  no popup rows")
                continue
            if category == "Set":
                raw = [
                    r
                    for r in raw
                    if isinstance(r.get("value"), (int, float))
                    and float(r["value"]) >= HISTORY_MIN_SET_VALUE
                ]

            hits = scrape_sv_item_histories(page, url, raw, category)
            print(f"  got history for {len(hits)} / {len(raw)} items")

            for row in raw:
                name = row.get("name")
                if not isinstance(name, str):
                    continue
                gid = by_display.get(name.strip()) or to_game_name(name, name_map)
                if not gid or gid not in items:
                    continue
                sv_hist = hits.get(name)
                value = float(items[gid])
                history = merge_item_history(
                    enriched_prev,
                    gid,
                    value,
                    updated_at,
                    sv_hist if isinstance(sv_hist, list) else None,
                )
                m = meta.get(gid)
                if not isinstance(m, dict):
                    m = {}
                    meta[gid] = m
                m["history"] = history
                if sv_hist:
                    total_hits += 1
                    enriched_prev[gid] = {**m, "_prevValue": value}

        browser.close()

    data["updatedAt"] = updated_at
    data = apply_to_values_payload(data)
    text = json.dumps(data, indent=2, ensure_ascii=False)
    OUT.write_text(text, encoding="utf-8")
    try:
        VOLT.parent.mkdir(parents=True, exist_ok=True)
        VOLT.write_text(text, encoding="utf-8")
        print(f"Also wrote {VOLT}")
    except Exception as e:
        print(f"Volt copy skipped: {e}")

    # Stats
    lens = []
    for m in meta.values():
        if isinstance(m, dict) and isinstance(m.get("history"), list):
            lens.append(len(m["history"]))
    lens.sort()
    print(
        f"Done. SV hits={total_hits}. History lens: "
        f"min={lens[0] if lens else 0} median={lens[len(lens)//2] if lens else 0} "
        f"max={lens[-1] if lens else 0} items={len(lens)}"
    )


if __name__ == "__main__":
    main()
