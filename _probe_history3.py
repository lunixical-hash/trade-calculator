"""Find how SV opens value history."""

from __future__ import annotations

import json
import re

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Capture XHR/fetch
        reqs = []

        def on_req(r):
            if r.resource_type in ("xhr", "fetch") or "json" in (r.headers.get("accept") or ""):
                reqs.append(r.url)

        page.on("request", on_req)
        page.goto(
            "https://supremevalues.com/mm2/godlies",
            wait_until="networkidle",
            timeout=90_000,
        )
        page.wait_for_timeout(2000)

        # Get loaded v6 JS source from browser cache/dom
        js_src = page.evaluate(
            """async () => {
              const scripts = [...document.querySelectorAll('script[src]')].map(s => s.src);
              const target = scripts.find(s => /v6/i.test(s)) || scripts.find(s => /javascript/i.test(s));
              if (!target) return { scripts, src: null };
              try {
                const res = await fetch(target);
                const text = await res.text();
                return { scripts, src: target, len: text.length, head: text.slice(0, 500), hist: (text.match(/hist\\w*/gi)||[]).slice(0,40), snippets: [...text.matchAll(/.{0,80}(hist|similar|chart).{0,120}/gi)].slice(0,15).map(m=>m[0]) };
              } catch (e) {
                return { scripts, err: String(e) };
              }
            }"""
        )
        print("JS", json.dumps(js_src, indent=2)[:5000])

        # Try right-click on image
        box = page.evaluate(
            """() => {
              const img = document.querySelector('img[src*="/media/mm2"]');
              if (!img) return null;
              const r = img.getBoundingClientRect();
              return { x: r.x + r.width/2, y: r.y + r.height/2, src: img.src };
            }"""
        )
        print("BOX", box)
        if box:
            page.mouse.click(box["x"], box["y"], button="right")
            page.wait_for_timeout(800)
            menu = page.evaluate(
                """() => {
                  const nodes = [...document.querySelectorAll('*')].filter(el => {
                    const t = (el.innerText||'').trim();
                    return /View Value History|Favorite|Wiki/i.test(t) && t.length < 200;
                  }).slice(0,10).map(el => ({t:(el.innerText||'').slice(0,120), tag:el.tagName, cls:el.className}));
                  return nodes;
                }"""
            )
            print("MENU", json.dumps(menu, indent=2)[:2000])

            page.evaluate(
                """() => {
                  for (const el of document.querySelectorAll('*')) {
                    const t = (el.innerText||'').trim();
                    if (/View Value History/i.test(t) && t.length < 80) { el.click(); return t; }
                  }
                  return null;
                }"""
            )
            page.wait_for_timeout(3000)
            print("AFTER CLICK REQS", reqs[-20:])
            after = page.evaluate(
                """() => {
                  const body = document.body.innerText || '';
                  const idx = body.search(/Value History|Similar Items|Date|Value over/i);
                  return {
                    canvases: document.querySelectorAll('canvas').length,
                    slice: idx>=0 ? body.slice(Math.max(0,idx-100), idx+2000) : body.slice(-1500),
                    dialogs: [...document.querySelectorAll('[class*=modal],[class*=popup],[class*=dialog],[id*=hist]')].map(el=>({id:el.id,cls:el.className,text:(el.innerText||'').slice(0,400)}))
                  };
                }"""
            )
            print("AFTER", json.dumps(after, indent=2)[:4000])

        browser.close()


if __name__ == "__main__":
    main()
