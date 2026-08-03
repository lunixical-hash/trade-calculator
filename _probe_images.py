"""Probe supremevalues godlies page for item image URL patterns."""

from playwright.sync_api import sync_playwright

URL = "https://supremevalues.com/mm2/godlies"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    )
    page.goto(URL, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(5000)

    data = page.evaluate(
        """() => {
          const imgs = [...document.querySelectorAll('img')]
            .slice(0, 40)
            .map(img => ({
              src: img.currentSrc || img.src || '',
              alt: img.alt || '',
              title: img.title || '',
              w: img.naturalWidth || img.width,
              h: img.naturalHeight || img.height,
              parentText: (img.closest('a,div,article,section')?.innerText || '').slice(0, 120)
            }));
          return {
            title: document.title,
            imgCount: document.querySelectorAll('img').length,
            imgs
          };
        }"""
    )
    print("title", data["title"])
    print("imgCount", data["imgCount"])
    for im in data["imgs"][:25]:
        print("---")
        print("alt:", im["alt"])
        print("src:", im["src"][:180])
        print("parent:", repr(im["parentText"][:100]))
    browser.close()
