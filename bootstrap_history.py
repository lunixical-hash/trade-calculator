"""Bootstrap changePct/trending into existing mm2_values.json without a full scrape.

Does NOT invent history dates from % change. Use bootstrap_sv_history.py to pull
authoritative Supreme Values chart points.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from scrape_mm2_values import (
    load_name_map,
    parse_change_pct,
    scrape_trending_and_changelog,
    to_game_name,
)
from catalog_fixes import apply_to_values_payload, sanitize_item_history

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "mm2_values.json"


def main() -> None:
    data = json.loads(OUT.read_text(encoding="utf-8"))
    items = data.get("items") or {}
    meta = data.setdefault("meta", {})
    name_map = load_name_map()
    now = int(time.time())

    cleaned_n = 0
    for item_id, value in items.items():
        if not isinstance(value, (int, float)):
            continue
        m = meta.get(item_id)
        if not isinstance(m, dict):
            m = {}
            meta[item_id] = m
        change = m.get("change")
        pct = parse_change_pct(change if isinstance(change, str) else None)
        m["changePct"] = pct

        hist = m.get("history") if isinstance(m.get("history"), list) else []
        before = len(hist)
        clean = sanitize_item_history(hist, float(value), change_pct=pct)
        # Ensure a current tip exists without inventing a fake prior date.
        if not clean:
            clean = [
                {
                    "t": now,
                    "v": float(value),
                    "label": time.strftime("%Y-%m-%d", time.localtime(now)),
                }
            ]
        elif abs(clean[-1]["v"] - float(value)) >= 0.5:
            clean.append(
                {
                    "t": now,
                    "v": float(value),
                    "label": time.strftime("%Y-%m-%d", time.localtime(now)),
                }
            )
        if len(clean) != before:
            cleaned_n += 1
        m["history"] = clean[-120:]

    trending_out = []
    changelog = None
    print("Fetching trending from homepage...")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            trending_raw, changelog = scrape_trending_and_changelog(page)
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
        print(f"  trending {len(trending_out)}")
    except Exception as e:
        print(f"  trending failed: {e}")

    data["trending"] = trending_out
    if changelog:
        data["changelog"] = changelog
    data["updatedAt"] = data.get("updatedAt") or now
    data = apply_to_values_payload(data)
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Sanitized history on {cleaned_n} items · wrote {OUT}")


if __name__ == "__main__":
    main()
