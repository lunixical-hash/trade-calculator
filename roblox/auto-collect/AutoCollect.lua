-- Regular LocalScript. Put it in StarterGui (not StarterPlayerScripts).
-- Paste this whole file into a LocalScript named AutoCollect. It only walks.
-- Your server still collects coins.
-- Output window lines start with [AutoCollect] so you can see why it is or isn't moving.

local PathfindingService = game:GetService("PathfindingService")
local Players = game:GetService("Players")
local Workspace = game:GetService("Workspace")

local runContext = nil
pcall(function()
	runContext = (script :: any).RunContext
end)
local runsOnClient = script:IsA("LocalScript") or runContext == Enum.RunContext.Client
if not runsOnClient then
	warn("[AutoCollect] This is a " .. script.ClassName .. " running on the server. Use a LocalScript, or set this Script's RunContext to Client.")
	return
end

local player = Players.LocalPlayer
if not player then
	warn("[AutoCollect] Players.LocalPlayer is nil. This has to run on the client. Put a LocalScript in StarterGui.")
	return
end

local Config = {
	SearchRadius = 1000,
	ReplanInterval = 0.35,
	StatusInterval = 2,

	CoinServerName = "Coin_Server",
	CoinVisualName = "CoinVisual",
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

type Candidate = { server: BasePart, pos: Vector3, straightDist: number }

local tracked: { [BasePart]: boolean } = {}
local namedNodes = 0
local skippedNotPart = 0
local busy = false
local unreachableUntil: { [BasePart]: number } = {}
local lastStatus = ""
local loggedSample = false

local function log(...)
	print("[AutoCollect]", ...)
end

local function resolvePart(inst: Instance): BasePart?
	if inst:IsA("BasePart") then
		return inst
	end
	local visual = inst:FindFirstChild(Config.CoinVisualName, true)
	if visual and visual:IsA("BasePart") then
		return visual
	end
	local part = inst:FindFirstChildWhichIsA("BasePart", true)
	if part then
		return part
	end
	return nil
end

local function consider(inst: Instance)
	if inst.Name ~= Config.CoinServerName then
		return
	end
	if not inst:IsDescendantOf(Workspace) then
		return
	end
	namedNodes += 1
	local part = resolvePart(inst)
	if not part then
		skippedNotPart += 1
		log("found", inst:GetFullName(), "class", inst.ClassName, "but no BasePart to walk to")
		return
	end
	tracked[part] = true
	if not loggedSample then
		loggedSample = true
		log("sample coin", inst:GetFullName(), "class", inst.ClassName, "part", part:GetFullName(), "transparency", part.Transparency)
	end
end

for _, inst in Workspace:GetDescendants() do
	consider(inst)
end

Workspace.DescendantAdded:Connect(function(inst)
	consider(inst)
	if inst.Name == Config.CoinServerName then
		log("new coin appeared:", inst:GetFullName())
	end
end)

Workspace.DescendantRemoving:Connect(function(inst)
	if inst:IsA("BasePart") then
		tracked[inst] = nil
		unreachableUntil[inst] = nil
	end
end)

local function isAvailable(server: BasePart): boolean
	return tracked[server] == true and server.Parent ~= nil and server.Transparency < Config.CollectedTransparency
end

local function rootAndHumanoid(character: Model): (BasePart?, Humanoid?)
	local root = character:FindFirstChild("HumanoidRootPart")
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if root and root:IsA("BasePart") and humanoid then
		return root, humanoid
	end
	return nil, nil
end

local function countTracked(): (number, number)
	local total = 0
	local available = 0
	for server in tracked do
		if server.Parent then
			total += 1
			if isAvailable(server) then
				available += 1
			end
		end
	end
	return total, available
end

local function listAvailableCoins(origin: Vector3): { Candidate }
	local list: { Candidate } = {}
	local radiusSq = Config.SearchRadius * Config.SearchRadius
	for server in tracked do
		if isAvailable(server) then
			local pos = server.Position
			local visual = server:FindFirstChild(Config.CoinVisualName)
			if visual and visual:IsA("BasePart") then
				pos = visual.Position
			elseif server.Name ~= Config.CoinServerName then
				local parent = server.Parent
				if parent then
					local nested = parent:FindFirstChild(Config.CoinVisualName)
					if nested and nested:IsA("BasePart") then
						pos = nested.Position
					end
				end
			end
			local offset = pos - origin
			if offset:Dot(offset) <= radiusSq then
				table.insert(list, { server = server, pos = pos, straightDist = offset.Magnitude })
			end
		end
	end
	return list
end

local function markUnreachable(server: BasePart, reason: string)
	unreachableUntil[server] = os.clock() + Config.UnreachableCooldown
	log("no path to", server:GetFullName(), "—", reason)
end

local function computePath(from: Vector3, to: Vector3): (number?, { PathWaypoint }?, string)
	local path = PathfindingService:CreatePath({
		AgentRadius = Config.AgentRadius,
		AgentHeight = Config.AgentHeight,
		AgentCanJump = Config.AgentCanJump,
		WaypointSpacing = Config.WaypointSpacing,
	})
	local ok, err = pcall(function()
		path:ComputeAsync(from, to)
	end)
	if not ok then
		return nil, nil, tostring(err)
	end
	if path.Status ~= Enum.PathStatus.Success then
		return nil, nil, tostring(path.Status)
	end
	local waypoints = path:GetWaypoints()
	if #waypoints == 0 then
		return nil, nil, "empty waypoints"
	end
	local length = 0
	for i = 2, #waypoints do
		length += (waypoints[i].Position - waypoints[i - 1].Position).Magnitude
	end
	return length, waypoints, "ok"
end

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
		local untilTime = unreachableUntil[c.server]
		if untilTime ~= nil and os.clock() < untilTime then
			continue
		end
		if isAvailable(c.server) then
			local length, waypoints, reason = computePath(origin, c.pos)
			if length and waypoints and length < bestLength then
				bestLength = length
				bestServer = c.server
				bestWaypoints = waypoints
			elseif not length then
				markUnreachable(c.server, reason)
			end
		end
	end

	if bestServer and bestWaypoints then
		log(string.format("walking to %s (%d studs, %d waypoints)", bestServer:GetFullName(), math.floor(bestLength), #bestWaypoints))
	end
	return bestServer, bestWaypoints
end

local function followWaypoints(humanoid: Humanoid, root: BasePart, target: BasePart, waypoints: { PathWaypoint })
	if humanoid.Sit then
		humanoid.Sit = false
	end
	humanoid.PlatformStand = false
	humanoid.AutoRotate = true

	for i, waypoint in waypoints do
		if i == 1 then
			continue
		end
		if not isAvailable(target) then
			log("coin gone or already transparent, picking another")
			return
		end
		if humanoid.Parent ~= player.Character then
			return
		end
		if waypoint.Action == Enum.PathWaypointAction.Jump then
			humanoid.Jump = true
		end
		humanoid:MoveTo(waypoint.Position)

		local finished = false
		local conn = humanoid.MoveToFinished:Connect(function()
			finished = true
		end)
		local deadline = os.clock() + Config.MoveToTimeout
		local nextPulse = os.clock()
		while not finished and os.clock() < deadline do
			if not isAvailable(target) or humanoid.Parent ~= player.Character then
				conn:Disconnect()
				return
			end
			if os.clock() >= nextPulse then
				humanoid:MoveTo(waypoint.Position)
				nextPulse = os.clock() + Config.MoveToRepulse
			end
			task.wait(0.1)
		end
		conn:Disconnect()
		if not finished then
			markUnreachable(target, "MoveTo timed out (character did not arrive)")
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
		if target and waypoints then
			followWaypoints(humanoid, root, target, waypoints)
		end
	end)
	busy = false
	if not ok then
		warn("[AutoCollect] error:", err)
	end
end

log("started for", player.Name, "from", script:GetFullName(), "class", script.ClassName)
local total, available = countTracked()
log(string.format("initial scan: named Coin_Server=%d, walkable parts=%d, available(transparency<1)=%d, no-part=%d", namedNodes, total, available, skippedNotPart))
if namedNodes == 0 then
	log("NO coins found in Workspace. The ReplicatedStorage template does not count. Coins must be named Coin_Server and be in the map that is currently in Workspace.")
elseif available == 0 and total > 0 then
	log("Coins were found, but every one has Transparency >= 1, so they are treated as already collected and skipped.")
end

task.spawn(function()
	while true do
		local character = player.Character
		local root = character and character:FindFirstChild("HumanoidRootPart")
		local totalNow, availableNow = countTracked()
		local near = 0
		if root and root:IsA("BasePart") then
			near = #listAvailableCoins(root.Position)
		end
		local line = string.format(
			"status character=%s tracked=%d available=%d within1000=%d busy=%s",
			character ~= nil and "yes" or "NO",
			totalNow,
			availableNow,
			near,
			tostring(busy)
		)
		if line ~= lastStatus then
			lastStatus = line
			log(line)
		end
		task.wait(Config.StatusInterval)
	end
end)

task.spawn(function()
	while true do
		runOnce()
		task.wait(Config.ReplanInterval)
	end
end)
