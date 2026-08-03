# Lunix's AI Trade Assistant

Trade calculator for Murder Mystery 2 values (scraped from Supreme Values) — **Lunix's AI Trade Assistant**.

| Artifact | Purpose |
|---|---|
| `scrape_mm2_values.py` | Scrapes values into `mm2_values.json` |
| `build_trade_calculator.py` | Rebuilds `trade_calculator.html` from that JSON |
| `trade_calculator.html` | Standalone calculator (open in any browser) |
| `calculator_overlay.py` | Optional always-on-top Windows overlay |

**Repo:** https://github.com/lunixical-hash/trade-calculator  
**Live site:** https://lunixical-hash.github.io/trade-calculator/

Values are sourced from [Supreme Values](https://supremevalues.com/mm2/).

---

## Use the calculator (no install)

### Option A — open the file

1. Clone or download this repo.
2. Double-click `trade_calculator.html`, or open it from your browser (File → Open).

### Option B — GitHub Pages (one-click)

```
https://lunixical-hash.github.io/trade-calculator/
```

That serves `index.html`, which redirects to the calculator. Direct link:

```
https://lunixical-hash.github.io/trade-calculator/trade_calculator.html
```

### Option C — Windows overlay

```powershell
python -m pip install -r requirements.txt
python calculator_overlay.py
# or double-click: Start Calculator Overlay.bat
```

---

## Scrape values / rebuild the calculator

### Setup (once)

```powershell
cd path\to\trade-calculator
python -m pip install -r requirements.txt
python -m playwright install chromium
```

### Scrape

```powershell
python scrape_mm2_values.py
```

Writes `mm2_values.json` here, and (on Windows) copies to  
`%LOCALAPPDATA%\Volt\workspace\mm2_values.json` when that folder exists.

### Rebuild the calculator HTML

After a scrape (or after changing catalog fixes):

```powershell
python build_trade_calculator.py
```

Opens as `trade_calculator.html` (and is what Pages serves).

### Optional hourly scrape (Windows Task Scheduler)

1. Task Scheduler → Create Basic Task → e.g. `MM2 Values Scraper`
2. Trigger: Daily → then edit to **Repeat every 1 hour**
3. Action: Start a program  
   - Program: `python`  
   - Arguments: `scrape_mm2_values.py`  
   - Start in: your clone path  
4. Run the task once to verify

---

## Name mismatches

If a site name doesn't match the in-game inventory name, edit `name_map.json`:

```json
{
  "Traveler's Gun": "TravelersGun"
}
```

Left = website name, right = exact MM2 inventory name.

---

## Publish to GitHub

### Create the repo and push (first time)

```powershell
git init
git add .
git commit -m "Add Lunix's AI Trade Assistant scraper and calculator"
gh repo create trade-calculator --public --source=. --remote=origin --push
```

Without `gh`, create an empty repo on github.com, then:

```powershell
git remote add origin https://github.com/lunixical-hash/trade-calculator.git
git branch -M main
git push -u origin main
```

### Enable GitHub Pages

**UI:** Repo → **Settings** → **Pages** → Source: **Deploy from a branch** → Branch: `main` → Folder: `/ (root)` → Save.

**CLI:**

```powershell
gh api repos/lunixical-hash/trade-calculator/pages -X POST -f build_type=legacy -f source[branch]=main -f source[path]=/
```

Live URL: `https://lunixical-hash.github.io/trade-calculator/`

---

## Lunix / local JSON (optional)

```lua
local HttpService = game:GetService("HttpService")

local function loadValues()
	if not isfile or not isfile("mm2_values.json") then
		return nil
	end
	local ok, data = pcall(function()
		return HttpService:JSONDecode(readfile("mm2_values.json"))
	end)
	if ok then
		return data
	end
	return nil
end

local values = loadValues()
if values then
	print("VampireGun value:", values.items.VampireGun)
end
```

---

## Requirements

- Python 3.10+ recommended  
- Dependencies: see `requirements.txt` (`playwright`, `pywebview`)
