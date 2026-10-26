# AFK coin path — one LocalScript

Walks to coins named `Coin_Server` anywhere in Workspace. Map names are not required. The template in ReplicatedStorage is ignored.

Your server still collects, fades, and destroys coins. This script only moves the character.

## Studio

1. `StarterGui` → **LocalScript** named `AutoCollect` (a normal LocalScript, not under StarterPlayer)
2. Paste `auto-collect/AutoCollect.lua` (same text as the Notepad file `AutoCollect.txt` in the agent files)
3. Do not also run the old Office3 / ResearchFacility test scripts

It skips coins already collected (`Transparency == 1`) and retargets when the server takes the current one.
