# Free AFK auto-collect (client move + server awards)

Smooth movement on **PC / mobile / tablet / console** via a **LocalScript**. Coin grants stay **server-authoritative**.

## Studio placement

| File | Put in Studio as |
|------|------------------|
| `Config.lua` | `ReplicatedStorage/AutoCollect/Config` (**ModuleScript**) |
| `AutoCollectServer.lua` | `ServerScriptService/AutoCollectServer` (**Script**) |
| `AutoCollectClient.lua` | `StarterPlayer.StarterPlayerScripts/AutoCollectClient` (**LocalScript**) |

Create the `ReplicatedStorage/AutoCollect` folder first, then add `Config`. The server script creates `RequestCollect` (RemoteEvent) under that folder if missing.

Drop the `.lua` suffix when naming instances in Studio (or paste contents into matching scripts).

## Split of responsibility

- **Client:** pathfinding + `Humanoid:MoveTo` (smooth, uses normal client physics on all devices). When a coin is in range, fires `RequestCollect`.
- **Server:** validates coin instance, `CoinContainer` ancestry, availability (`Transparency < 1`), and distance (`CollectRadius` + slack). Then fade → award → delayed destroy. Never trusts the client for the grant amount beyond the request.

## Coins

```
Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
```

Already-collected coins (`Transparency == 1`, waiting to despawn) are skipped on both sides.

## Config

Edit `CollectRadius` (default **1000** studs) and other knobs in `ReplicatedStorage/AutoCollect/Config`. Wire `award` in `AutoCollectServer` if you do not use `leaderstats.Coins`.
