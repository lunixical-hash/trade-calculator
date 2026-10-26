-- LocalScript: StarterPlayer.StarterPlayerScripts/AutoCollect
-- ONE file: config + pathfinding + MoveTo + collect/award.
--
-- WARNING: Awards run on the client. Exploiters can grant themselves coins
-- unless you later add a thin server validator. Chosen for simplicity/smoothness.

local PathfindingService = game:GetService("PathfindingService")
local Players = game:GetService("Players")
local Workspace = game:GetService("Workspace")

local player = Players.LocalPlayer

----------------------------------------------------------------
-- Config (edit here)
----------------------------------------------------------------
local Config = {
	CollectRadius = 1000, -- studs
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
}

----------------------------------------------------------------
-- Collect / award (client-side — see warning at top)
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

local function getVisualPosition(coin: Instance): Vector3?
	local server = getCoinServer(coin)
	if not server then
		return nil
	end
	local visual = server:FindFirstChild(Config.CoinVisualName)
	if visual and visual:IsA("BasePart") then
		return visual.Position
	end
	return server.Position
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

-- Replace if your economy is not leaderstats.Coins (still client-side).
local function award(amount: number)
	local stats = player:FindFirstChild("leaderstats")
	local coins = stats and stats:FindFirstChild("Coins")
	if coins and coins:IsA("IntValue") then
		coins.Value += amount
	end
end

local function tryCollect(coin: Instance): boolean
	if not isAvailable(coin) then
		return false
	end
	local character = player.Character
	if not character then
		return false
	end
	local root = character:FindFirstChild("HumanoidRootPart")
	if not (root and root:IsA("BasePart")) then
		return false
	end
	local pos = getVisualPosition(coin)
	if not pos or (pos - root.Position).Magnitude > Config.CollectRadius then
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

	award(amount)

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
-- Pathfinding + MoveTo (smooth on all devices)
----------------------------------------------------------------
type Candidate = { server: BasePart, pos: Vector3, straightDist: number }

local busy = false
local unreachableUntil: { [BasePart]: number } = {}

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

local function isOnCooldown(server: BasePart): boolean
	local untilTime = unreachableUntil[server]
	return untilTime ~= nil and os.clock() < untilTime
end

local function markUnreachable(server: BasePart)
	unreachableUntil[server] = os.clock() + Config.UnreachableCooldown
end

local function tryVacuumNearby(origin: Vector3)
	local radiusSq = Config.CollectRadius * Config.CollectRadius
	for _, c in listAvailableCoins() do
		local offset = c.pos - origin
		if offset:Dot(offset) <= radiusSq then
			tryCollect(c.server)
		end
	end
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

local function pickBestTarget(origin: Vector3): (BasePart?, { PathWaypoint }?)
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
		if not isOnCooldown(c.server) and isAvailable(c.server) then
			if c.straightDist <= Config.CollectRadius then
				return c.server, {}
			end
			local length, waypoints = computePathLength(origin, c.pos)
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
		if not isAvailable(target) then
			return
		end
		local character = player.Character
		if not character or humanoid.Parent ~= character then
			return
		end

		tryVacuumNearby(root.Position)
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

			tryVacuumNearby(root.Position)
			local targetPos = getVisualPosition(target) or waypoint.Position
			if (root.Position - targetPos).Magnitude <= Config.CollectRadius then
				if conn then
					conn:Disconnect()
				end
				tryCollect(target)
				return
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

	if isAvailable(target) then
		tryCollect(target)
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
		tryVacuumNearby(root.Position)

		local target, waypoints = pickBestTarget(root.Position)
		if not target then
			return
		end
		if not waypoints or #waypoints == 0 then
			tryCollect(target)
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
