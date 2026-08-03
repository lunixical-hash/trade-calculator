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
          const rows = [];
          const imgs = [...document.querySelectorAll('img')];
          for (const img of imgs) {
            const src = img.currentSrc || img.src || '';
            if (!src || src.includes('/media/icons/')) continue;
            const block = img.closest('a,div,article,section,li') || img.parentElement;
            const text = (block?.innerText || '').replace(/\\s+/g, ' ').trim();
            if (!/Value\\s*-/i.test(text)) continue;
            const name = (text.split('Value')[0] || '').trim().split('\\n').pop();
            rows.push({ src: src.slice(0, 200), alt: img.alt || '', text: text.slice(0, 120), nameHint: name.slice(0, 60) });
            if (rows.length >= 8) break;
          }
          const prefixes = {};
          for (const img of imgs) {
            const src = img.currentSrc || img.src || '';
            const m = src.match(/\\/media\\/[^/]+\\//);
            if (m) prefixes[m[0]] = (prefixes[m[0]] || 0) + 1;
          }
          return { rows, prefixes, total: imgs.length };
        }"""
    )
    print("total", data["total"])
    print("prefixes", data["prefixes"])
    for r in data["rows"]:
        print(r)
    browser.close()
