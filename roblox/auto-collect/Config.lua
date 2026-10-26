-- ModuleScript: ServerScriptService/AutoCollect/Config
-- Paste the numeric GamePass ID here after you create the gamepass.

local Config = {
	GamePassId = 0, -- TODO: replace 0 with your GamePass ID

	CollectRadius = 20, -- studs around the character (uses CoinVisual position)
	LoopInterval = 0.5, -- seconds between auto-collect sweeps
	OwnershipRecheckSeconds = 60, -- periodic cache refresh (0 = only on join)

	-- Hierarchy: Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
	-- MapName changes per map; we find any CoinContainer under Workspace.
	CoinContainerName = "CoinContainer",
	CoinServerName = "Coin_Server",
	CoinVisualName = "CoinVisual",

	-- Collected coins stay in the world briefly with Transparency = 1, then destroy.
	-- Auto-collect must skip those so it never waits on an already-taken coin.
	CollectedTransparency = 1,
	DestroyAfterSeconds = 2,

	CoinValueAttribute = "Value",
	DefaultCoinValue = 1,
}

return Config
