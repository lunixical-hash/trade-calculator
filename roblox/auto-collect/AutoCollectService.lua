-- Script: ServerScriptService/AutoCollect/AutoCollectService
-- AFK owners pathfind around walls to the nearest reachable coin, re-plan often,
-- and only award via CoinCollect (skips already-collected / transparent coins).

local PathfindingService = game:GetService("PathfindingService")
local Players = game:GetService("Players")
local Workspace = game:GetService("Workspace")

local Config = require(script.Parent.Config)
local CoinCollect = require(script.Parent.CoinCollect)
local GamePassCache = require(script.Parent.GamePassCache)

type Candidate = {
	server: BasePart,
	pos: Vector3,
	straightDist: number,
}

local busy: { [Player]: boolean } = {}
local unreachableUntil: { [Player]: { [BasePart]: number } } = {}

local function rootAndHumanoid(character: Model): (BasePart?, Humanoid?)
	local root = character:FindFirstChild("HumanoidRootPart")
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if root and root:IsA("BasePart") and humanoid then
		return root, humanoid
	end
	return nil, nil
end

local function listAvailableCoins(): { Candidate }
	local list: { Candidate } = {}
	for _, map in Workspace:GetChildren() do
		local container = map:FindFirstChild(Config.CoinContainerName)
		if container then
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
				if server and CoinCollect.IsAvailable(server) then
					local pos = CoinCollect.GetVisualPosition(server)
					if pos then
						table.insert(list, {
							server = server,
							pos = pos,
							straightDist = 0,
						})
					end
				end
			end
		end
	end
	return list
end

local function isOnCooldown(player: Player, server: BasePart): boolean
	local map = unreachableUntil[player]
	if not map then
		return false
	end
	local untilTime = map[server]
	return untilTime ~= nil and os.clock() < untilTime
end

local function markUnreachable(player: Player, server: BasePart)
	local map = unreachableUntil[player]
	if not map then
		map = {}
		unreachableUntil[player] = map
	end
	map[server] = os.clock() + Config.UnreachableCooldown
end

local function createPath()
	return PathfindingService:CreatePath({
		AgentRadius = Config.AgentRadius,
		AgentHeight = Config.AgentHeight,
		AgentCanJump = Config.AgentCanJump,
		WaypointSpacing = Config.WaypointSpacing,
	})
end

-- Returns path length on success, or nil if blocked.
local function computePathLength(from: Vector3, to: Vector3): (number?, { PathWaypoint }?)
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

-- Pick the reachable coin with the shortest walk path among nearby candidates.
local function pickBestTarget(player: Player, origin: Vector3): (BasePart?, { PathWaypoint }?)
	local coins = listAvailableCoins()
	if #coins == 0 then
		return nil, nil
	end

	for _, c in coins do
		c.straightDist = (c.pos - origin).Magnitude
	end
	table.sort(coins, function(a, b)
		return a.straightDist < b.straightDist
	end)

	local limit = math.min(Config.MaxPathCandidates, #coins)
	local bestServer: BasePart? = nil
	local bestWaypoints: { PathWaypoint }? = nil
	local bestLength = math.huge

	for i = 1, limit do
		local c = coins[i]
		if not isOnCooldown(player, c.server) and CoinCollect.IsAvailable(c.server) then
			-- Already in pickup range — no path needed.
			if c.straightDist <= Config.CollectRadius then
				return c.server, {}
			end

			local length, waypoints = computePathLength(origin, c.pos)
			if length and waypoints and length < bestLength then
				bestLength = length
				bestServer = c.server
				bestWaypoints = waypoints
			elseif not length then
				markUnreachable(player, c.server)
			end
		end
	end

	return bestServer, bestWaypoints
end

local function tryVacuumNearby(player: Player, origin: Vector3)
	local radiusSq = Config.CollectRadius * Config.CollectRadius
	for _, c in listAvailableCoins() do
		local offset = c.pos - origin
		if offset:Dot(offset) <= radiusSq then
			CoinCollect.TryCollect(player, c.server)
		end
	end
end

local function followWaypoints(player: Player, humanoid: Humanoid, root: BasePart, target: BasePart, waypoints: { PathWaypoint })
	for i, waypoint in waypoints do
		if i == 1 then
			continue
		end
		if not GamePassCache.Owns(player) then
			return
		end
		if not CoinCollect.IsAvailable(target) then
			return
		end
		if not player.Character or humanoid.Parent ~= player.Character then
			return
		end

		-- Dynamic: grab anything that comes into range while walking (e.g. overlapping spawns).
		tryVacuumNearby(player, root.Position)
		if not CoinCollect.IsAvailable(target) then
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
		while not finished and os.clock() < deadline do
			if not CoinCollect.IsAvailable(target) then
				if conn then
					conn:Disconnect()
				end
				return
			end
			tryVacuumNearby(player, root.Position)
			if (root.Position - (CoinCollect.GetVisualPosition(target) or waypoint.Position)).Magnitude <= Config.CollectRadius then
				if conn then
					conn:Disconnect()
				end
				CoinCollect.TryCollect(player, target)
				return
			end
			task.wait(0.1)
		end
		if conn then
			conn:Disconnect()
		end
		if not finished then
			markUnreachable(player, target)
			return
		end
	end

	if CoinCollect.IsAvailable(target) then
		CoinCollect.TryCollect(player, target)
	end
end

local function runOwner(player: Player)
	if busy[player] then
		return
	end
	if not GamePassCache.Owns(player) then
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

	busy[player] = true
	local ok, err = pcall(function()
		tryVacuumNearby(player, root.Position)

		local target, waypoints = pickBestTarget(player, root.Position)
		if not target then
			return
		end
		if not waypoints or #waypoints == 0 then
			CoinCollect.TryCollect(player, target)
			return
		end
		followWaypoints(player, humanoid, root, target, waypoints)
	end)
	busy[player] = false
	if not ok then
		warn("[AutoCollect] error for", player.Name, err)
	end
end

Players.PlayerRemoving:Connect(function(player)
	busy[player] = nil
	unreachableUntil[player] = nil
end)

task.spawn(function()
	while true do
		for _, player in Players:GetPlayers() do
			task.spawn(runOwner, player)
		end
		task.wait(Config.ReplanInterval)
	end
end)
