# Free AFK auto-collect

One server script. Every player pathfinds around walls to the nearest reachable coin — no gamepass.

## Studio

1. Create a **Script** under `ServerScriptService` named `AutoCollect`.
2. Paste the contents of `auto-collect/AutoCollect.lua`.
3. Edit the `Config` table at the top if needed (radius, agent size, etc.).
4. If your economy is not `leaderstats.Coins`, change the `award` function in that same script.

## Coin hierarchy

```
Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
```

Map name is discovered automatically. Coins that are already collected (`Coin_Server.Transparency == 1`, waiting to despawn) are skipped.

## Behavior

- Free for all players (no MarketplaceService / gamepass check).
- Pathfinds; picks shortest walkable target among nearby candidates.
- Walks with `Humanoid:MoveTo`; vacuums anything that enters `CollectRadius` while moving.
- Fade-then-destroy collect path matches intentional coin despawn timing.
