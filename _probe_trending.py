"""Probe homepage trending + changelog + image paths."""

from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://supremevalues.com/mm2/", wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(3000)
        info = page.evaluate(
            """() => {
              const body = document.body.innerText || '';
              const idxT = body.search(/Trending/i);
              const idxC = body.search(/SUPREME VALUES UPDATE|Changelog|UPDATE/i);
              const imgs = [...document.querySelectorAll('img')].slice(0,5).map(i => i.src);
              const media = [...document.querySelectorAll('img')].map(i => i.src).filter(s => /media\\/mm2/i.test(s)).slice(0,5);
              return {
                title: document.title,
                imgSample: imgs,
                mediaSample: media,
                trending: idxT>=0 ? body.slice(idxT, idxT+1200) : null,
                changelog: idxC>=0 ? body.slice(idxC, idxC+2500) : null,
                hasSvPopup: typeof _svPopup !== 'undefined',
                svCount: typeof _svPopup !== 'undefined' ? Object.keys(_svPopup).length : 0,
              };
            }"""
        )
        print(json.dumps(info, indent=2)[:6000])

        page.goto("https://supremevalues.com/mm2/godlies", wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(3500)
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
        g = page.evaluate(
            """() => {
              const media = [...document.querySelectorAll('img')].map(i => i.currentSrc||i.src).filter(s => /media/i.test(s)).slice(0,20);
              return {
                media,
                svCount: typeof _svPopup !== 'undefined' ? Object.keys(_svPopup).length : 0,
                sample: typeof _svPopup !== 'undefined' ? _svPopup[Object.keys(_svPopup)[0]] : null,
              };
            }"""
        )
        print("GODLIES", json.dumps(g, indent=2)[:3000])
        browser.close()


if __name__ == "__main__":
    main()
