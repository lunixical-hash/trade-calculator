"""Deeper probe: _svPopup + history modal data."""

from __future__ import annotations

import json
import re

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(
            "https://supremevalues.com/mm2/ancients",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        page.wait_for_timeout(2500)

        popup = page.evaluate(
            """() => {
              if (typeof _svPopup === 'undefined') return null;
              const keys = Object.keys(_svPopup);
              const sample = _svPopup[keys[0]];
              return { count: keys.length, sampleKey: keys[0], sample, keys: keys.slice(0, 15) };
            }"""
        )
        print("POPUP", json.dumps(popup, indent=2)[:2500])

        # Search page HTML for history-related embedded data
        html = page.content()
        for pat in [
            r"valueHistory",
            r"ValueHistory",
            r"itemHistory",
            r"_svHistory",
            r"historyData",
            r"chartData",
            r"/history",
            r"similarItems",
        ]:
            m = re.search(pat, html, re.I)
            print("PAT", pat, "->", bool(m), (m.group(0) if m else ""))

        # Find script tags with large JSON
        scripts = page.evaluate(
            """() => {
              const out = [];
              for (const s of document.querySelectorAll('script')) {
                const t = s.textContent || '';
                if (t.length < 80) continue;
                if (/history|svPopup|chart|similar/i.test(t)) {
                  out.push({ len: t.length, head: t.slice(0, 200), hasHist: /hist/i.test(t) });
                }
              }
              return out.slice(0, 20);
            }"""
        )
        print("SCRIPTS", json.dumps(scripts, indent=2)[:3000])

        # Open image context menu path carefully
        page.evaluate(
            """() => {
              const img = [...document.querySelectorAll('img[src*="/media/mm2"]')]
                .find(i => /Celestial|Gingerscope|Batwing/i.test(i.src) || /Celestial|Gingerscope|Batwing/i.test(i.alt||''));
              (img || document.querySelector('img[src*="/media/mm2"]')).click();
            }"""
        )
        page.wait_for_timeout(500)

        # Capture DOM after opening history
        page.evaluate(
            """() => {
              for (const el of document.querySelectorAll('*')) {
                const t = (el.innerText || '').trim();
                if (t === 'View Value History and Similar Items') {
                  el.click();
                  return true;
                }
              }
              return false;
            }"""
        )
        page.wait_for_timeout(2500)

        modal = page.evaluate(
            """() => {
              const candidates = [...document.querySelectorAll('div,section,dialog')]
                .filter(el => {
                  const t = el.innerText || '';
                  return /Value History|Similar Items/i.test(t) && t.length > 40 && t.length < 20000;
                })
                .map(el => ({
                  cls: el.className,
                  id: el.id,
                  len: (el.innerText||'').length,
                  text: (el.innerText||'').slice(0, 2500),
                  html: el.innerHTML.slice(0, 2500),
                }));
              return candidates.slice(0, 3);
            }"""
        )
        print("MODAL", json.dumps(modal, indent=2)[:5000])

        # Check window for chart datasets after open
        charts = page.evaluate(
            """() => {
              const out = {};
              for (const k of ['Chart', 'ChartData', '_svHistory', 'valueHistory', 'itemData', 'historyData']) {
                try { if (window[k] != null) out[k] = typeof window[k]; } catch(e) {}
              }
              // Chart.js instances
              if (window.Chart && Chart.instances) {
                out.chartInstances = Object.keys(Chart.instances).length;
              }
              const canvases = [...document.querySelectorAll('canvas')].map(c => ({
                w: c.width, h: c.height, id: c.id, cls: c.className
              }));
              out.canvases = canvases;
              return out;
            }"""
        )
        print("CHARTS", json.dumps(charts, indent=2)[:2000])

        browser.close()


if __name__ == "__main__":
    main()
