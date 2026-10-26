# Auto-collect coins gamepass

Drop-in Luau for Studio. Checks gamepass ownership on the server and auto-collects nearby coins for AFK players.

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

Coins live under the active map, which changes often:

```
Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
```

Auto-collect finds any `CoinContainer` under Workspace children — you do not hardcode the map name.

## Collected-but-not-destroyed yet

When a coin is collected, `Coin_Server.Transparency` is set to `1`, then destroyed a short time later. That is intentional.

`CoinCollect.IsAvailable` skips any coin with transparency already at `1`, so the auto-collect loop never latches onto an already-taken coin while it waits to despawn.

If your existing pickup script already does that fade+destroy, call `CoinCollect.TryCollect` from it (or mirror the same transparency gate) so both paths stay in sync. Prefer wiring your real award function inside `CoinCollect.award` rather than duplicating grants.

## What you still set

1. Paste your GamePass ID into `Config.GamePassId` (replace `0`).
2. Grant ownership yourself (purchase UI / dashboard not included).
3. Point `award` in `CoinCollect` at your real economy if it is not `leaderstats.Coins`.
