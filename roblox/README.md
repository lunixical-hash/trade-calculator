# Auto-collect coins gamepass

Drop-in Luau for Studio. Server checks gamepass ownership, then AFK-pathfinds around walls to the nearest reachable coin for maximum collections.

## Studio placement

Copy everything under `auto-collect/` into:

```
ServerScriptService/
  AutoCollect/
    Config                 ← ModuleScript (paste GamePassId here)
    CoinCollect            ← ModuleScript
    GamePassCache          ← ModuleScript
    AutoCollectService     ← Script (not ModuleScript)
```

Rename each file in Studio to drop the `.lua` extension (or paste contents into matching ModuleScripts/Script).

## Coin hierarchy (map-aware)

```
Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
```

`MapName` changes per map; scripts find any `CoinContainer` under Workspace.

## Pathfinding (walls)

Maps with lots of walls are handled with `PathfindingService`:

1. Rank coins by straight-line distance, take the closest `MaxPathCandidates` (default 12).
2. Compute a walkable path for each; pick the **shortest successful path** (not just closest through a wall).
3. Walk waypoints with `Humanoid:MoveTo` (jumps when the path says so).
4. Re-plan often (`ReplanInterval`); vacuum any coin that enters `CollectRadius` while moving.
5. Skip coins already at transparency `1` (collected, waiting to despawn).
6. Briefly cool down coins that fail pathfinding so the bot does not thrash on blocked spots.

Tune `AgentRadius` / `AgentHeight` / `AgentCanJump` in `Config` if the character gets stuck in tight corridors.

## Collected-but-not-destroyed yet

On collect, `Coin_Server.Transparency` goes to `1`, then the instance is destroyed after a short delay. `IsAvailable` ignores those so auto-collect never waits on a taken coin.

Prefer routing your real manual pickup through `CoinCollect.TryCollect` so both paths stay in sync. Wire your economy inside `award` in `CoinCollect`.

## What you still set

1. Paste GamePass ID into `Config.GamePassId` (replace `0`).
2. Grant ownership yourself (no purchase UI in this pack).
3. Point `award` at your real economy if not `leaderstats.Coins`.
4. If pathfinding struggles in narrow halls, lower `AgentRadius` slightly.
