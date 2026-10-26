# Free AFK auto-collect — one LocalScript

Single LocalScript: config + pathfinding + `MoveTo` + collect/award.

## Studio

1. `StarterPlayer` → `StarterPlayerScripts` → new **LocalScript** named `AutoCollect`
2. Paste `auto-collect/AutoCollect.lua`
3. Edit the `Config` table at the top (`CollectRadius` default **1000** studs)

## Coins

```
Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
```

Already-collected coins (`Coin_Server.Transparency == 1`, waiting to despawn) are skipped.

## Map path tests

Paste one of these into `StarterPlayerScripts` as a LocalScript. Only run one at a time (both call `MoveTo`). They do not award or destroy coins.

| File | Map |
|------|-----|
| `auto-collect/Office3PathTest.lua` | `Workspace.Office3` |
| `auto-collect/ResearchFacilityPathTest.lua` | `Workspace.ResearchFacility` |

Output is prefixed `[Office3PathTest]` or `[ResearchFacilityPathTest]`.

## Important: client-trusting awards

Coin awards and transparency/destroy run **on the client**. That is simpler and smooth on all devices, but **exploiters can grant themselves coins**. If you need secure economy later, add a thin server validator (RemoteEvent + server `TryCollect`) — not included here by choice.
