"""Probe Supreme Values item history UI / network."""

from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        hits: list[dict] = []

        def on_response(r):
            u = r.url
            if "supremevalues" not in u:
                return
            ct = (r.headers.get("content-type") or "").lower()
            interesting = (
                "json" in ct
                or "hist" in u.lower()
                or "/api" in u.lower()
                or "chart" in u.lower()
                or "value" in u.lower()
            )
            if not interesting:
                return
            try:
                body = r.text()
            except Exception:
                body = ""
            hits.append(
                {
                    "url": u,
                    "status": r.status,
                    "ct": ct,
                    "body": body[:800],
                }
            )

        page.on("response", on_response)
        page.goto(
            "https://supremevalues.com/mm2/ancients",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        page.wait_for_timeout(3000)

        page.evaluate(
            """() => {
              const img = document.querySelector('img[src*="/media/mm2"]');
              if (img) img.click();
            }"""
        )
        page.wait_for_timeout(800)

        clicked = page.evaluate(
            """() => {
              for (const el of document.querySelectorAll('button,a,div,span,li,p')) {
                const t = (el.innerText || el.textContent || '').trim();
                if (/value history|similar items/i.test(t) && t.length < 100) {
                  el.click();
                  return { ok: true, t: t.slice(0, 100) };
                }
              }
              // also try menu items by attribute / title
              for (const el of document.querySelectorAll('[onclick], [role="menuitem"], .menu *')) {
                const t = (el.innerText || el.textContent || el.title || '').trim();
                if (/history/i.test(t) && t.length < 100) {
                  el.click();
                  return { ok: true, t: t.slice(0, 100), via: 'attr' };
                }
              }
              return { ok: false };
            }"""
        )
        print("CLICK", clicked)
        page.wait_for_timeout(3000)

        info = page.evaluate(
            """() => {
              const body = document.body.innerText || '';
              const idx = body.search(/Value History|Historical|Similar Items|Changelog/i);
              const tables = [...document.querySelectorAll('table')].map(t =>
                (t.innerText || '').slice(0, 400)
              );
              const charts = {
                canvas: document.querySelectorAll('canvas').length,
                svg: document.querySelectorAll('svg').length,
              };
              // Look for chart.js / plotly / highcharts data
              const globals = [];
              for (const k of Object.keys(window)) {
                if (/chart|hist|value|plotly|highcharts/i.test(k)) globals.push(k);
              }
              return {
                idx,
                slice: idx >= 0 ? body.slice(idx, idx + 2000) : body.slice(0, 1000),
                tables: tables.slice(0, 5),
                charts,
                globals: globals.slice(0, 40),
              };
            }"""
        )
        print("INFO", json.dumps(info, indent=2)[:4000])
        print("NET COUNT", len(hits))
        for h in hits[:30]:
            print("---", h["url"], h["status"], h["ct"])
            print(h["body"][:400])

        browser.close()


if __name__ == "__main__":
    main()
