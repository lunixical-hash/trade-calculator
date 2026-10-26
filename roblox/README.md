# Free AFK coin path — one LocalScript

Walks the character along a path between coins. **Your existing server already collects, awards, fades, and destroys coins.** This script does not touch coin instances or grant currency.

## Studio

1. `StarterPlayer` → `StarterPlayerScripts` → new **LocalScript** named `AutoCollect`
2. Paste `auto-collect/AutoCollect.lua`
3. Edit `Config` at the top if needed (`SearchRadius` default **1000** studs)

## Coins it paths toward

```
Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
```

It skips coins your server has already collected (`Coin_Server.Transparency == 1`, waiting to despawn) so it does not walk to a taken coin. When the server collects the current target, the script picks the next reachable coin.
