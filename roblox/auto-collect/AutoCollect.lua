-- Script: ServerScriptService/AutoCollect
-- Free AFK auto-collect for every player (PC / mobile / tablet / console).
-- Fully server-driven: no client UI or device input required.
-- Coins: Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
-- Collected coins fade (Transparency = 1) then destroy — those are skipped.

local PathfindingService = game:GetService("PathfindingService")
local Players = game:GetService("Players")
local Workspace = game:GetService("Workspace")

----------------------------------------------------------------
-- Config (edit here)
----------------------------------------------------------------
local Config = {
	-- Studs. High value = strong AFK magnet / pickup range around the character.
	CollectRadius = 1000,
	ReplanInterval = 0.35,

	CoinContainerName = "CoinContainer",
	CoinServerName = "Coin_Server",
	CoinVisualName = "CoinVisual",

	CollectedTransparency = 1,
	DestroyAfterSeconds = 2,

	CoinValueAttribute = "Value",
	DefaultCoinValue = 1,

	-- Pathfinding agent (R6 + R15). Lower AgentRadius if stuck in tight halls.
	AgentRadius = 2,
	AgentHeight = 5,
	AgentCanJump = true,
	WaypointSpacing = 4,
	MoveToTimeout = 3, -- slightly forgiving for high-latency mobile / console
	MoveToRepulse = 0.35, -- re-issue MoveTo so client input cannot cancel walking
	MaxPathCandidates = 12,
	UnreachableCooldown = 4,
}

----------------------------------------------------------------
-- Collect (server-authoritative; skips already-taken coins)
----------------------------------------------------------------
local collecting: { [Instance]: boolean } = {}

local function getCoinServer(coin: Instance): BasePart?
	if coin.Name == Config.CoinServerName and coin:IsA("BasePart") then
		return coin
	end
	local server = coin:FindFirstChild(Config.CoinServerName)
	if server and server:IsA("BasePart") then
		return server
	end
	if coin:IsA("BasePart") then
		return coin
	end
	return nil
end

local function getCoinVisual(coinServer: BasePart): BasePart?
	local visual = coinServer:FindFirstChild(Config.CoinVisualName)
	if visual and visual:IsA("BasePart") then
		return visual
	end
	return coinServer
end

local function getVisualPosition(coin: Instance): Vector3?
	local server = getCoinServer(coin)
	if not server then
		return nil
	end
	local visual = getCoinVisual(server)
	return visual and visual.Position or nil
end

local function isAvailable(coin: Instance): boolean
	if collecting[coin] or not coin.Parent then
		return false
	end
	local server = getCoinServer(coin)
	if not server or not server.Parent then
		return false
	end
	if server.Transparency >= Config.CollectedTransparency then
		return false
	end
	return true
end

local function coinValue(coin: Instance): number
	local server = getCoinServer(coin) or coin
	local v = server:GetAttribute(Config.CoinValueAttribute)
	if typeof(v) == "number" then
		return v
	end
	return Config.DefaultCoinValue
end

-- Replace with your economy API if you do not use leaderstats.Coins.
local function award(player: Player, amount: number)
	local stats = player:FindFirstChild("leaderstats")
	local coins = stats and stats:FindFirstChild("Coins")
	if coins and coins:IsA("IntValue") then
		coins.Value += amount
	end
end

local function tryCollect(player: Player, coin: Instance): boolean
	if not isAvailable(coin) or not player.Character then
		return false
	end
	local server = getCoinServer(coin)
	if not server then
		return false
	end

	collecting[coin] = true
	collecting[server] = true

	local amount = coinValue(coin)
	server.Transparency = Config.CollectedTransparency
	local visual = server:FindFirstChild(Config.CoinVisualName)
	if visual and visual:IsA("BasePart") then
		visual.Transparency = Config.CollectedTransparency
	end
	server.CanTouch = false
	server.CanQuery = false

	award(player, amount)

	task.delay(Config.DestroyAfterSeconds, function()
		collecting[coin] = nil
		collecting[server] = nil
		if server.Parent then
			server:Destroy()
		elseif coin.Parent then
			coin:Destroy()
		end
	end)

	return true
end

----------------------------------------------------------------
-- Character helpers (all devices / R6 / R15)
----------------------------------------------------------------
local function rootAndHumanoid(character: Model): (BasePart?, Humanoid?)
	local root = character:FindFirstChild("HumanoidRootPart")
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if root and root:IsA("BasePart") and humanoid then
		return root, humanoid
	end
	return nil, nil
end

-- Server must own the root or MoveTo is ignored when the client owns physics
-- (common on mobile / console when any thumbstick / touch input is active).
local function takeServerControl(root: BasePart)
	pcall(function()
		root:SetNetworkOwner(nil)
	end)
end

local function releaseServerControl(player: Player)
	local character = player.Character
	if not character then
		return
	end
	local root = character:FindFirstChild("HumanoidRootPart")
	if root and root:IsA("BasePart") then
		pcall(function()
			root:SetNetworkOwner(player)
		end)
	end
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

----------------------------------------------------------------
-- Pathfinding AFK loop (all players, all devices)
----------------------------------------------------------------
type Candidate = { server: BasePart, pos: Vector3, straightDist: number }

local busy: { [Player]: boolean } = {}
local unreachableUntil: { [Player]: { [BasePart]: number } } = {}

local function listAvailableCoins(): { Candidate }
	local list: { Candidate } = {}
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
				local pos = getVisualPosition(server)
				if pos then
					table.insert(list, { server = server, pos = pos, straightDist = 0 })
				end
			end
		end
	end
	return list
end

local function isOnCooldown(player: Player, server: BasePart): boolean
	local map = unreachableUntil[player]
	local untilTime = map and map[server]
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

	local bestServer: BasePart? = nil
	local bestWaypoints: { PathWaypoint }? = nil
	local bestLength = math.huge
	local limit = math.min(Config.MaxPathCandidates, #coins)

	for i = 1, limit do
		local c = coins[i]
		if not isOnCooldown(player, c.server) and isAvailable(c.server) then
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
			tryCollect(player, c.server)
		end
	end
end

local function followWaypoints(player: Player, humanoid: Humanoid, root: BasePart, target: BasePart, waypoints: { PathWaypoint })
	takeServerControl(root)
	prepareHumanoid(humanoid)

	for i, waypoint in waypoints do
		if i == 1 then
			continue
		end
		if not isAvailable(target) then
			return
		end
		if not player.Character or humanoid.Parent ~= player.Character then
			return
		end

		tryVacuumNearby(player, root.Position)
		if not isAvailable(target) then
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
			if not player.Character or humanoid.Parent ~= player.Character then
				if conn then
					conn:Disconnect()
				end
				return
			end

			-- Keep server ownership + re-assert MoveTo (touch/gamepad can cancel it).
			takeServerControl(root)
			if os.clock() >= nextPulse then
				humanoid:MoveTo(waypoint.Position)
				nextPulse = os.clock() + Config.MoveToRepulse
			end

			tryVacuumNearby(player, root.Position)
			local targetPos = getVisualPosition(target) or waypoint.Position
			if (root.Position - targetPos).Magnitude <= Config.CollectRadius then
				if conn then
					conn:Disconnect()
				end
				tryCollect(player, target)
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

	if isAvailable(target) then
		tryCollect(player, target)
	end
end

local function runPlayer(player: Player)
	if busy[player] then
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
			tryCollect(player, target)
			return
		end
		followWaypoints(player, humanoid, root, target, waypoints)
	end)
	busy[player] = false
	releaseServerControl(player)
	if not ok then
		warn("[AutoCollect] error for", player.Name, err)
	end
end

Players.PlayerRemoving:Connect(function(player)
	busy[player] = nil
	unreachableUntil[player] = nil
end)

Players.PlayerAdded:Connect(function(player)
	player.CharacterAdded:Connect(function()
		-- Fresh character starts with normal client ownership; loop takes over when walking.
	end)
end)

task.spawn(function()
	while true do
		for _, player in Players:GetPlayers() do
			task.spawn(runPlayer, player)
		end
		task.wait(Config.ReplanInterval)
	end
end)
