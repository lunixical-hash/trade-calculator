# Free AFK auto-collect

One server script. Works for **PC, mobile, tablet, and console** — no client scripts, no touch/gamepad UI. Every player auto-collects coins in range; pathfinding walks around walls when needed.

## Studio

1. Create a **Script** under `ServerScriptService` named `AutoCollect`.
2. Paste `auto-collect/AutoCollect.lua`.
3. Edit `Config` at the top if needed (`CollectRadius` is in studs, default **1000**).
4. If your economy is not `leaderstats.Coins`, change the `award` function in that same script.

## Coin hierarchy

```
Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
```

Map name is discovered automatically. Coins already collected (`Coin_Server.Transparency == 1`, waiting to despawn) are skipped.

## Cross-device notes

- Server owns `HumanoidRootPart` while walking so mobile/console input cannot cancel `MoveTo`.
- Ownership is returned to the player when a walk finishes.
- R6 and R15 both use `HumanoidRootPart` + `Humanoid`.
- No LocalScripts required.

## Behavior

- Free for all players.
- Vacuum / collect anything within `CollectRadius` (1000 studs by default).
- Pathfinds when a walk is still useful; picks shortest walkable target among nearby candidates.
- Fade-then-destroy collect path matches intentional coin despawn timing.
