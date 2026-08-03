# Lunix's AI Trade Assistant

MM2 values scraper (Supreme Values) plus a browser-based trade calculator — **Lunix's AI Trade Assistant**.

| Artifact | Purpose |
|---|---|
| `scrape_mm2_values.py` | Scrapes values into `mm2_values.json` |
| `build_trade_calculator.py` | Rebuilds `trade_calculator.html` from that JSON |
| `trade_calculator.html` | Standalone calculator (open in any browser) |
| `calculator_overlay.py` | Optional always-on-top Windows overlay |

Values are sourced from [Supreme Values](https://supremevalues.com/mm2/).

---

## Use the calculator (no install)

### Option A — open the file

1. Clone or download this repo.
2. Double-click `trade_calculator.html`, or open it from your browser (File → Open).

### Option B — GitHub Pages (one-click)

If Pages is enabled on this repo (Settings → Pages → Deploy from branch **main** / root `/`):

```
https://<your-github-username>.github.io/mm2-values-scraper/
```

That serves `index.html`, which redirects to the calculator. Direct link:

```
https://<your-github-username>.github.io/mm2-values-scraper/trade_calculator.html
```

See [Publish to GitHub](#publish-to-github) below to turn Pages on.

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
cd path\to\mm2-values-scraper
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

This project is meant to be pushed as a normal public repo so others can clone it or use Pages.

### Create the repo and push (first time)

```powershell
# From the project folder (git must be on PATH)
git init
git add .
git commit -m "Add Lunix's AI Trade Assistant scraper and calculator"

# Create a public GitHub repo and push (GitHub CLI)
gh repo create mm2-values-scraper --public --source=. --remote=origin --push
```

Without `gh`, create an empty repo on github.com, then:

```powershell
git remote add origin https://github.com/<your-username>/mm2-values-scraper.git
git branch -M main
git push -u origin main
```

If push asks for login, complete auth in the browser / credential helper — this environment cannot finish auth for you.

### Enable GitHub Pages

**UI:** Repo → **Settings** → **Pages** → Source: **Deploy from a branch** → Branch: `main` → Folder: `/ (root)` → Save.

**CLI** (after the repo exists):

```powershell
gh api repos/<your-username>/mm2-values-scraper/pages -X POST -f build_type=legacy -f source[branch]=main -f source[path]=/
```

Wait a minute, then open:

`https://<your-username>.github.io/mm2-values-scraper/`

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
