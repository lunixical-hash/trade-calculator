-- LocalScript: StarterPlayer.StarterPlayerScripts/AutoCollectClient
-- Pathfinding + Humanoid:MoveTo on the client for smooth movement on all devices.
-- Fires RequestCollect; server validates and awards (never trust this script for grants).

local PathfindingService = game:GetService("PathfindingService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Workspace = game:GetService("Workspace")

local player = Players.LocalPlayer
local folder = ReplicatedStorage:WaitForChild("AutoCollect")
local Config = require(folder:WaitForChild("Config"))
local requestCollect = folder:WaitForChild("RequestCollect") :: RemoteEvent

type Candidate = { server: BasePart, pos: Vector3, straightDist: number }

local busy = false
local unreachableUntil: { [BasePart]: number } = {}
local lastRequestAt: { [BasePart]: number } = {}

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

-- Client-side preview of availability (server re-checks before awarding).
local function isAvailable(coin: Instance): boolean
	if not coin.Parent then
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

local function requestCollectCoin(server: BasePart)
	local now = os.clock()
	local last = lastRequestAt[server]
	if last and (now - last) < Config.ClientRequestCooldown then
		return
	end
	lastRequestAt[server] = now
	requestCollect:FireServer(server)
end

local function tryVacuumNearby(origin: Vector3)
	local radiusSq = Config.CollectRadius * Config.CollectRadius
	for _, c in listAvailableCoins() do
		local offset = c.pos - origin
		if offset:Dot(offset) <= radiusSq then
			requestCollectCoin(c.server)
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
				requestCollectCoin(target)
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
		requestCollectCoin(target)
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
			requestCollectCoin(target)
			return
		end
		followWaypoints(humanoid, root, target, waypoints)
	end)
	busy = false
	if not ok then
		warn("[AutoCollect] client error", err)
	end
end

task.spawn(function()
	while true do
		runOnce()
		task.wait(Config.ReplanInterval)
	end
end)
