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

## Office3 test

`auto-collect/Office3PathTest.lua` is a LocalScript that only walks coins under `Workspace.Office3`. Paste it into `StarterPlayerScripts` as `Office3PathTest`. Watch the Output window for `[Office3PathTest]`. Do not run it together with `AutoCollect`. It does not award or destroy coins — your server still does that.

## Important: client-trusting awards

Coin awards and transparency/destroy run **on the client**. That is simpler and smooth on all devices, but **exploiters can grant themselves coins**. If you need secure economy later, add a thin server validator (RemoteEvent + server `TryCollect`) — not included here by choice.
