-- ModuleScript: ServerScriptService/AutoCollect/Config
-- Paste the numeric GamePass ID here after you create the gamepass.

local Config = {
	GamePassId = 0, -- TODO: replace 0 with your GamePass ID

	-- Pickup range once the character is next to a coin (CoinVisual position).
	CollectRadius = 8,

	-- How often each owner re-plans (pick best reachable coin / retarget).
	ReplanInterval = 0.35,

	OwnershipRecheckSeconds = 60,

	-- Hierarchy: Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
	CoinContainerName = "CoinContainer",
	CoinServerName = "Coin_Server",
	CoinVisualName = "CoinVisual",

	-- Collected coins stay briefly with Transparency = 1, then destroy.
	CollectedTransparency = 1,
	DestroyAfterSeconds = 2,

	CoinValueAttribute = "Value",
	DefaultCoinValue = 1,

	-- Pathfinding (walls / mazes). Agent sizes should roughly match your character.
	AgentRadius = 2,
	AgentHeight = 5,
	AgentCanJump = true,
	WaypointSpacing = 4,
	MoveToTimeout = 2, -- seconds per waypoint before giving up that path

	-- Only pathfind among the N nearest candidates by straight-line distance
	-- (keeps planning cheap on maps with hundreds of coins).
	MaxPathCandidates = 12,

	-- Skip a coin for this many seconds after a failed path (dead ends / blocked).
	UnreachableCooldown = 4,
}

return Config
