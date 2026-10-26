-- ModuleScript: ReplicatedStorage/AutoCollect/Config
-- Shared by client (movement) and server (award validation). Keep one source of truth.

local Config = {
	-- Studs. Client vacuums / server accepts collect within this distance (+ slack on server).
	CollectRadius = 1000,
	-- Extra studs allowed on server to cover latency / replication lag.
	ServerDistanceSlack = 50,

	ReplanInterval = 0.35,

	CoinContainerName = "CoinContainer",
	CoinServerName = "Coin_Server",
	CoinVisualName = "CoinVisual",

	CollectedTransparency = 1,
	DestroyAfterSeconds = 2,

	CoinValueAttribute = "Value",
	DefaultCoinValue = 1,

	AgentRadius = 2,
	AgentHeight = 5,
	AgentCanJump = true,
	WaypointSpacing = 4,
	MoveToTimeout = 3,
	MoveToRepulse = 0.35,
	MaxPathCandidates = 12,
	UnreachableCooldown = 4,

	-- Client: min seconds between RequestCollect fires for the same coin.
	ClientRequestCooldown = 0.2,
}

return Config
