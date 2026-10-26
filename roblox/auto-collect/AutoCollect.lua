-- LocalScript: StarterPlayer.StarterPlayerScripts/AutoCollect
-- Builds a path among existing coins and follows it.
-- Coin pickup, awards, fade, and destroy are already handled by your server.
-- This script only moves the character. It does not grant coins or change coin instances.

local PathfindingService = game:GetService("PathfindingService")
local Players = game:GetService("Players")
local Workspace = game:GetService("Workspace")

local player = Players.LocalPlayer

----------------------------------------------------------------
-- Config (edit here)
----------------------------------------------------------------
local Config = {
	-- Only path toward coins within this many studs.
	SearchRadius = 1000,
	ReplanInterval = 0.35,

	-- Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
	CoinContainerName = "CoinContainer",
	CoinServerName = "Coin_Server",
	CoinVisualName = "CoinVisual",

	-- Your server sets Transparency to 1 when a coin is taken, then destroys later.
	-- Skip those so we never walk to a coin that is already collected.
	CollectedTransparency = 1,

	AgentRadius = 2,
	AgentHeight = 5,
	AgentCanJump = true,
	WaypointSpacing = 4,
	MoveToTimeout = 3,
	MoveToRepulse = 0.35,
	MaxPathCandidates = 12,
	UnreachableCooldown = 4,
}

----------------------------------------------------------------
-- Find coins (read-only)
----------------------------------------------------------------
type Candidate = { server: BasePart, pos: Vector3, straightDist: number }

local busy = false
local unreachableUntil: { [BasePart]: number } = {}

local function getVisual(server: BasePart): BasePart
	local visual = server:FindFirstChild(Config.CoinVisualName)
	if visual and visual:IsA("BasePart") then
		return visual
	end
	return server
end

-- Still on the map and not already collected by the server.
local function isAvailable(server: BasePart): boolean
	if not server.Parent then
		return false
	end
	if server.Transparency >= Config.CollectedTransparency then
		return false
	end
	return true
end

local function rootAndHumanoid(character: Model): (BasePart?, Humanoid?)
	local root = character:FindFirstChild("HumanoidRootPart")
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if root and root:IsA("BasePart") and humanoid then
		return root, humanoid
	end
	return nil, nil
end

local function listAvailableCoins(origin: Vector3): { Candidate }
	local list: { Candidate } = {}
	local radiusSq = Config.SearchRadius * Config.SearchRadius

	for _, map in Workspace:GetChildren() do
		local container = map:FindFirstChild(Config.CoinContainerName)
		if not container then
			continue
		end
		for _, child in container:GetChildren() do
			local server: BasePart? = nil
			if child.Name == Config.CoinServerName and child:IsA("BasePart") then
				server = child
			elseif child:IsA("Model") then
				local nested = child:FindFirstChild(Config.CoinServerName)
				if nested and nested:IsA("BasePart") then
					server = nested
				end
			end
			if server and isAvailable(server) then
				local pos = getVisual(server).Position
				local offset = pos - origin
				if offset:Dot(offset) <= radiusSq then
					table.insert(list, {
						server = server,
						pos = pos,
						straightDist = offset.Magnitude,
					})
				end
			end
		end
	end

	return list
end

local function isOnCooldown(server: BasePart): boolean
	local untilTime = unreachableUntil[server]
	return untilTime ~= nil and os.clock() < untilTime
end

local function markUnreachable(server: BasePart)
	unreachableUntil[server] = os.clock() + Config.UnreachableCooldown
end

local function createPath()
	return PathfindingService:CreatePath({
		AgentRadius = Config.AgentRadius,
		AgentHeight = Config.AgentHeight,
		AgentCanJump = Config.AgentCanJump,
		WaypointSpacing = Config.WaypointSpacing,
	})
end

local function computePath(from: Vector3, to: Vector3): (number?, { PathWaypoint }?)
	local path = createPath()
	local ok = pcall(function()
		path:ComputeAsync(from, to)
	end)
	if not ok or path.Status ~= Enum.PathStatus.Success then
		return nil, nil
	end
	local waypoints = path:GetWaypoints()
	if #waypoints == 0 then
		return nil, nil
	end
	local length = 0
	for i = 2, #waypoints do
		length += (waypoints[i].Position - waypoints[i - 1].Position).Magnitude
	end
	return length, waypoints
end

-- Shortest walkable coin among the nearest candidates.
local function pickBestTarget(origin: Vector3): (BasePart?, { PathWaypoint }?)
	local coins = listAvailableCoins(origin)
	if #coins == 0 then
		return nil, nil
	end

	table.sort(coins, function(a, b)
		return a.straightDist < b.straightDist
	end)

	local bestServer: BasePart? = nil
	local bestWaypoints: { PathWaypoint }? = nil
	local bestLength = math.huge
	local limit = math.min(Config.MaxPathCandidates, #coins)

	for i = 1, limit do
		local c = coins[i]
		if not isOnCooldown(c.server) and isAvailable(c.server) then
			local length, waypoints = computePath(origin, c.pos)
			if length and waypoints and length < bestLength then
				bestLength = length
				bestServer = c.server
				bestWaypoints = waypoints
			elseif not length then
				markUnreachable(c.server)
			end
		end
	end

	return bestServer, bestWaypoints
end

local function prepareHumanoid(humanoid: Humanoid)
	if humanoid.Sit then
		humanoid.Sit = false
	end
	if humanoid.PlatformStand then
		humanoid.PlatformStand = false
	end
	humanoid.AutoRotate = true
end

local function followWaypoints(humanoid: Humanoid, root: BasePart, target: BasePart, waypoints: { PathWaypoint })
	prepareHumanoid(humanoid)

	for i, waypoint in waypoints do
		if i == 1 then
			continue
		end
		-- Server collected it (faded or gone) — stop and let the loop pick the next coin.
		if not isAvailable(target) then
			return
		end
		local character = player.Character
		if not character or humanoid.Parent ~= character then
			return
		end

		if waypoint.Action == Enum.PathWaypointAction.Jump then
			humanoid.Jump = true
		end

		humanoid:MoveTo(waypoint.Position)
		local finished = false
		local conn: RBXScriptConnection?
		conn = humanoid.MoveToFinished:Connect(function()
			finished = true
		end)

		local deadline = os.clock() + Config.MoveToTimeout
		local nextPulse = os.clock()
		while not finished and os.clock() < deadline do
			if not isAvailable(target) then
				if conn then
					conn:Disconnect()
				end
				return
			end
			character = player.Character
			if not character or humanoid.Parent ~= character then
				if conn then
					conn:Disconnect()
				end
				return
			end

			if os.clock() >= nextPulse then
				humanoid:MoveTo(waypoint.Position)
				nextPulse = os.clock() + Config.MoveToRepulse
			end
			task.wait(0.1)
		end
		if conn then
			conn:Disconnect()
		end
		if not finished then
			markUnreachable(target)
			return
		end
	end
end

local function runOnce()
	if busy then
		return
	end
	local character = player.Character
	if not character then
		return
	end
	local root, humanoid = rootAndHumanoid(character)
	if not root or not humanoid or humanoid.Health <= 0 then
		return
	end

	busy = true
	local ok, err = pcall(function()
		local target, waypoints = pickBestTarget(root.Position)
		if not target or not waypoints then
			return
		end
		followWaypoints(humanoid, root, target, waypoints)
	end)
	busy = false
	if not ok then
		warn("[AutoCollect] error", err)
	end
end

task.spawn(function()
	while true do
		runOnce()
		task.wait(Config.ReplanInterval)
	end
end)
