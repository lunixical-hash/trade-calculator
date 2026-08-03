"""Build a simple Supreme Values catalog sorted by value."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VALUES = ROOT / "mm2_values.json"
OUT = ROOT / "sv_items_by_value.html"
VOLT = Path.home() / "AppData/Local/Volt/workspace/sv_items_by_value.html"


def fmt(v) -> str:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return "—"
    if n >= 1000:
        return f"{n:,.0f}"
    if n == int(n):
        return str(int(n))
    return f"{n:g}"


def main() -> None:
    d = json.loads(VALUES.read_text(encoding="utf-8"))
    items = d.get("items") or {}
    displays = d.get("displayNames") or {}
    images = d.get("images") or {}
    rarities = d.get("rarities") or {}
    meta = d.get("meta") or {}
    aliases = set((d.get("aliases") or {}).keys())

    rows = []
    for sv_id, value in items.items():
        if sv_id in aliases:
            continue  # skip alias duplicate keys
        rarity = rarities.get(sv_id, "—")
        if rarity in {"Set", "Pet"}:
            continue
        rows.append(
            {
                "id": sv_id,
                "name": displays.get(sv_id, sv_id),
                "value": value,
                "image": images.get(sv_id),
                "rarity": rarity,
                "demand": (meta.get(sv_id) or {}).get("demand"),
                "rarityScore": (meta.get(sv_id) or {}).get("rarityScore"),
            }
        )

    rarity_order = [
        "Ancient", "Godly", "Vintage", "Chroma", "Unique", "Evo",
        "Legendary", "Rare", "Uncommon", "Common",
    ]

    def rar_rank(r: str) -> int:
        try:
            return rarity_order.index(r)
        except ValueError:
            return len(rarity_order)

    rows.sort(key=lambda r: (rar_rank(r["rarity"]), -float(r["value"]), r["name"].lower()))

    cards = []
    for i, r in enumerate(rows, 1):
        img = (
            f'<img src="{r["image"]}" alt="" loading="lazy" referrerpolicy="no-referrer" />'
            if r["image"]
            else '<div class="noimg">No image yet</div>'
        )
        demand = f'Demand {r["demand"]}' if r["demand"] is not None else ""
        score = f'SV # {r["rarityScore"]}' if r["rarityScore"] is not None else ""
        bits = " · ".join(x for x in (demand, score) if x)
        cards.append(
            f"""
            <article class="card" data-rarity="{(r['rarity'] or '').lower()}" data-name="{r['name'].lower()}" data-id="{r['id'].lower()}">
              <div class="rank">#{i}</div>
              <div class="art">{img}</div>
              <div class="body">
                <div class="name">{r['name']}</div>
                <div class="id">{r['id']}</div>
                <div class="meta"><span class="rarity">{r['rarity']}</span>{(' · ' + bits) if bits else ''}</div>
              </div>
              <div class="value">{fmt(r['value'])}</div>
            </article>
            """
        )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>SV Items by Value</title>
<style>
  :root {{
    --bg:#0f1115; --panel:#171a21; --text:#e8eaef; --muted:#9aa3b2; --line:#2a3140; --accent:#3db8a0;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; font-family:"Segoe UI", system-ui, sans-serif; color:var(--text);
    background: radial-gradient(1000px 500px at 0% 0%, #1a3030 0%, var(--bg) 50%);
  }}
  header {{
    position:sticky; top:0; z-index:5; backdrop-filter:blur(10px);
    background:rgba(15,17,21,.92); border-bottom:1px solid var(--line);
    padding:16px 20px; display:flex; flex-wrap:wrap; gap:10px; align-items:center;
  }}
  h1 {{ margin:0; font-size:20px; margin-right:auto; }}
  input, select {{
    background:var(--panel); color:var(--text); border:1px solid var(--line);
    border-radius:10px; padding:9px 12px; font-size:13px;
  }}
  input {{ min-width:240px; flex:1; max-width:420px; }}
  .stats {{ color:var(--muted); font-size:12px; width:100%; }}
  main {{ padding:16px 20px 40px; display:grid; gap:10px; }}
  .card {{
    display:grid; grid-template-columns:56px 64px 1fr auto; gap:12px; align-items:center;
    background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:10px 12px;
  }}
  .card.hidden {{ display:none; }}
  .rank {{ color:var(--muted); font-weight:700; font-variant-numeric:tabular-nums; }}
  .art img, .noimg {{
    width:56px; height:56px; border-radius:10px; object-fit:contain;
    background:#10141b; border:1px solid var(--line);
  }}
  .noimg {{ display:grid; place-items:center; font-size:10px; color:var(--muted); text-align:center; }}
  .name {{ font-weight:700; }}
  .id {{ color:var(--muted); font-size:12px; font-family:ui-monospace, Consolas, monospace; }}
  .meta {{ color:var(--muted); font-size:12px; margin-top:4px; }}
  .rarity {{
    display:inline-block; padding:2px 8px; border-radius:999px; background:#2a2438; color:#d2c4ff; font-weight:700;
  }}
  .value {{ font-size:18px; font-weight:800; font-variant-numeric:tabular-nums; color:#b7f5e4; }}
  @media (max-width:720px) {{
    .card {{ grid-template-columns:40px 52px 1fr; }}
    .value {{ grid-column: 2 / -1; }}
  }}
</style>
</head>
<body>
<header>
  <h1>Supreme Values · by rarity, then value</h1>
  <input id="q" type="search" placeholder="Search name or id..." />
  <select id="rarity">
    <option value="">All rarities</option>
    <option>Godly</option><option>Ancient</option><option>Vintage</option>
    <option>Chroma</option><option>Unique</option><option>Evo</option>
    <option>Legendary</option><option>Rare</option><option>Uncommon</option>
    <option>Common</option>
  </select>
  <div class="stats" id="stats">{len(rows)} items · sets excluded · rarity then value</div>
</header>
<main>
{''.join(cards)}
</main>
<script>
const q = document.getElementById('q');
const rarity = document.getElementById('rarity');
const stats = document.getElementById('stats');
function apply() {{
  const query = q.value.trim().toLowerCase();
  const rar = rarity.value.toLowerCase();
  let shown = 0;
  document.querySelectorAll('.card').forEach(card => {{
    const okName = !query || card.dataset.name.includes(query) || card.dataset.id.includes(query);
    const okRar = !rar || card.dataset.rarity === rar;
    const ok = okName && okRar;
    card.classList.toggle('hidden', !ok);
    if (ok) shown += 1;
  }});
  stats.textContent = shown + ' showing · rarity then value · sets excluded';
}}
q.addEventListener('input', apply);
rarity.addEventListener('change', apply);
</script>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    VOLT.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT} ({len(rows)} items)")
    print(f"Wrote {VOLT}")


if __name__ == "__main__":
    main()
