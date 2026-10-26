-- Paste this whole file into the Studio command bar while the game is playing.
-- The command bar must be set to Client (not Server). The F9 console cannot run code.
-- It only walks. Your server still collects coins.
-- Output lines start with [AutoCollect].

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local Workspace = game:GetService("Workspace")

local sourceScript = nil
pcall(function()
	sourceScript = script
end)

if sourceScript ~= nil then
	local runContext = nil
	pcall(function()
		runContext = (sourceScript :: any).RunContext
	end)
	local runsOnClient = sourceScript:IsA("LocalScript") or runContext == Enum.RunContext.Client
	if not runsOnClient then
		warn("[AutoCollect] This is running on the server. In the command bar, switch Server to Client, then paste again.")
		return
	end
end

local player = Players.LocalPlayer
if not player then
	warn("[AutoCollect] No local player. Press Play, set the command bar to Client, then paste this again. Server mode and the F9 window will not move your character.")
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
	AgentCanJump = true,
	CellSize = 4,
	MaxStepUp = 6,
	ArriveDistance = 3.5,
	StuckTimeout = 4,
	MaxPathCandidates = 8,
	MaxSearchNodes = 2500,
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

local pathFolder = Workspace:FindFirstChild("AutoCollectPath")
if pathFolder then
	pathFolder:Destroy()
end
pathFolder = Instance.new("Folder")
pathFolder.Name = "AutoCollectPath"
pathFolder.Parent = Workspace

local function clearPathLine()
	pathFolder:ClearAllChildren()
end

-- Neon parts and Beams created here exist only on this client.
local function showPathLine(points: { Vector3 })
	clearPathLine()
	if #points < 2 then
		return
	end
	local attachments = {}
	for i, position in points do
		local node = Instance.new("Part")
		node.Name = if i == 1 then "Start" else "Node"
		node.Anchored = true
		node.CanCollide = false
		node.CanQuery = false
		node.CanTouch = false
		node.Material = Enum.Material.Neon
		node.Color = Color3.fromRGB(0, 255, 80)
		node.Size = if i == #points then Vector3.new(1.4, 1.4, 1.4) else Vector3.new(0.55, 0.55, 0.55)
		node.Shape = Enum.PartType.Ball
		node.Position = position
		node.Parent = pathFolder
		local attachment = Instance.new("Attachment")
		attachment.Parent = node
		attachments[i] = attachment
	end
	for i = 1, #attachments - 1 do
		local beam = Instance.new("Beam")
		beam.Name = "Heading"
		beam.Attachment0 = attachments[i]
		beam.Attachment1 = attachments[i + 1]
		beam.Width0 = 0.45
		beam.Width1 = 0.45
		beam.Color = ColorSequence.new(Color3.fromRGB(0, 255, 80))
		beam.FaceCamera = true
		beam.LightEmission = 1
		beam.Segments = 1
		beam.Parent = pathFolder
	end
	log("green heading line drawn,", #points, "points (only you can see it)")
end

local function stickLineToPlayer(root: BasePart)
	local startNode = pathFolder:FindFirstChild("Start")
	if startNode and startNode:IsA("BasePart") then
		startNode.Position = root.Position
	end
end

local function markUnreachable(server: BasePart, reason: string)
	unreachableUntil[server] = os.clock() + Config.UnreachableCooldown
	log("no path to", server:GetFullName(), "—", reason)
end

-- Our own pathfinder. Raycasts around walls. Does not use PathfindingService.
local rayParams = RaycastParams.new()
rayParams.FilterType = Enum.RaycastFilterType.Exclude

local function refreshRayFilter()
	local filter = {}
	if player.Character then
		table.insert(filter, player.Character)
	end
	for part in tracked do
		if part.Parent then
			table.insert(filter, part)
		end
	end
	rayParams.FilterDescendantsInstances = filter
end

local function flatDir(a: Vector3, b: Vector3): Vector3
	local delta = Vector3.new(b.X - a.X, 0, b.Z - a.Z)
	if delta.Magnitude < 0.001 then
		return Vector3.zero
	end
	return delta.Unit
end

local function segmentBlocked(a: Vector3, b: Vector3): boolean
	local delta = b - a
	if delta.Magnitude < 0.05 then
		return false
	end
	local side = flatDir(a, b):Cross(Vector3.yAxis) * Config.AgentRadius
	local lifts = { 2, 4 }
	local offsets = { Vector3.zero, side, -side }
	for _, lift in lifts do
		for _, offset in offsets do
			local origin = a + Vector3.new(0, lift, 0) + offset
			local hit = Workspace:Raycast(origin, delta, rayParams)
			if hit then
				return true
			end
		end
	end
	return false
end

local function groundAt(x: number, z: number, hintY: number): Vector3?
	local origin = Vector3.new(x, hintY + 12, z)
	local hit = Workspace:Raycast(origin, Vector3.new(0, -80, 0), rayParams)
	if not hit then
		return nil
	end
	return hit.Position + Vector3.new(0, 3, 0)
end

local function simplify(points: { Vector3 }): { Vector3 }
	if #points <= 2 then
		return points
	end
	local simplified = { points[1] }
	local anchor = 1
	for i = 3, #points do
		if segmentBlocked(points[anchor], points[i]) then
			table.insert(simplified, points[i - 1])
			anchor = i - 1
		end
	end
	table.insert(simplified, points[#points])
	return simplified
end

local function pathLength(points: { Vector3 }): number
	local length = 0
	for i = 2, #points do
		length += (points[i] - points[i - 1]).Magnitude
	end
	return length
end

local function computePath(from: Vector3, to: Vector3): (number?, { Vector3 }?, string)
	refreshRayFilter()
	local goal = groundAt(to.X, to.Z, to.Y) or to
	local start = groundAt(from.X, from.Z, from.Y) or from
	if not segmentBlocked(start, goal) then
		local direct = { start, goal }
		return pathLength(direct), direct, "direct"
	end

	local span = (Vector3.new(goal.X, 0, goal.Z) - Vector3.new(start.X, 0, start.Z)).Magnitude
	local cell = math.clamp(math.ceil(span / 40), Config.CellSize, 12)
	local pad = cell * 3
	local minX = math.min(start.X, goal.X) - pad
	local minZ = math.min(start.Z, goal.Z) - pad
	local maxX = math.max(start.X, goal.X) + pad
	local maxZ = math.max(start.Z, goal.Z) + pad
	local cols = math.floor((maxX - minX) / cell) + 1
	local rows = math.floor((maxZ - minZ) / cell) + 1
	if cols < 2 or rows < 2 or cols * rows > 8000 then
		return nil, nil, "area too large for the grid"
	end

	local function pack(ix: number, iz: number): number
		return ix * 100000 + iz
	end
	local function worldOf(ix: number, iz: number, hintY: number): Vector3?
		return groundAt(minX + ix * cell, minZ + iz * cell, hintY)
	end

	local startIx = math.clamp(math.floor((start.X - minX) / cell + 0.5), 0, cols - 1)
	local startIz = math.clamp(math.floor((start.Z - minZ) / cell + 0.5), 0, rows - 1)
	local goalIx = math.clamp(math.floor((goal.X - minX) / cell + 0.5), 0, cols - 1)
	local goalIz = math.clamp(math.floor((goal.Z - minZ) / cell + 0.5), 0, rows - 1)

	local startPos = worldOf(startIx, startIz, start.Y)
	local goalPos = worldOf(goalIx, goalIz, goal.Y)
	if not startPos or not goalPos then
		return nil, nil, "no floor at the start or the coin"
	end

	local dirs = {
		{ 1, 0, 1 },
		{ -1, 0, 1 },
		{ 0, 1, 1 },
		{ 0, -1, 1 },
		{ 1, 1, 1.414 },
		{ 1, -1, 1.414 },
		{ -1, 1, 1.414 },
		{ -1, -1, 1.414 },
	}

	local open = { { ix = startIx, iz = startIz, f = 0 } }
	local function heapUp(i: number)
		while i > 1 do
			local parent = math.floor(i / 2)
			if open[parent].f <= open[i].f then
				break
			end
			open[parent], open[i] = open[i], open[parent]
			i = parent
		end
	end
	local function heapDown(i: number)
		while true do
			local left = i * 2
			local right = left + 1
			local smallest = i
			if left <= #open and open[left].f < open[smallest].f then
				smallest = left
			end
			if right <= #open and open[right].f < open[smallest].f then
				smallest = right
			end
			if smallest == i then
				break
			end
			open[smallest], open[i] = open[i], open[smallest]
			i = smallest
		end
	end
	local function push(ix: number, iz: number, f: number)
		table.insert(open, { ix = ix, iz = iz, f = f })
		heapUp(#open)
	end
	local function pop()
		local top = open[1]
		local last = table.remove(open)
		if #open > 0 and last then
			open[1] = last
			heapDown(1)
		end
		return top
	end

	local came: { [number]: number } = {}
	local cost: { [number]: number } = { [pack(startIx, startIz)] = 0 }
	local seen = 0
	local found = false

	while #open > 0 and seen < Config.MaxSearchNodes do
		local node = pop()
		seen += 1
		if node.ix == goalIx and node.iz == goalIz then
			found = true
			break
		end
		local nodeKey = pack(node.ix, node.iz)
		if node.f > (cost[nodeKey] or 0) + math.abs(goalIx - node.ix) + math.abs(goalIz - node.iz) then
			-- stale heap entry
		else
			local here = worldOf(node.ix, node.iz, start.Y)
			if here then
				for _, dir in dirs do
					local nix = node.ix + dir[1]
					local niz = node.iz + dir[2]
					if nix >= 0 and niz >= 0 and nix < cols and niz < rows then
						local nxt = worldOf(nix, niz, here.Y)
						if nxt and math.abs(nxt.Y - here.Y) <= Config.MaxStepUp and not segmentBlocked(here, nxt) then
							local nextKey = pack(nix, niz)
							local nextCost = (cost[nodeKey] or 0) + dir[3]
							if cost[nextKey] == nil or nextCost < cost[nextKey] then
								cost[nextKey] = nextCost
								came[nextKey] = nodeKey
								local heuristic = math.abs(goalIx - nix) + math.abs(goalIz - niz)
								push(nix, niz, nextCost + heuristic)
							end
						end
					end
				end
			end
		end
	end

	if not found then
		return nil, nil, string.format("custom grid found no opening (%d cells checked)", seen)
	end

	local cells = {}
	local cursor = pack(goalIx, goalIz)
	local startKey = pack(startIx, startIz)
	local guard = 0
	while cursor ~= startKey and guard < 5000 do
		local ix = math.floor(cursor / 100000)
		local iz = cursor - ix * 100000
		local pos = worldOf(ix, iz, goal.Y)
		if pos then
			table.insert(cells, 1, pos)
		end
		cursor = came[cursor]
		if cursor == nil then
			break
		end
		guard += 1
	end
	table.insert(cells, 1, start)
	table.insert(cells, goal)
	local points = simplify(cells)
	return pathLength(points), points, "grid"
end

local function pickBestTarget(origin: Vector3): (BasePart?, { Vector3 }?)
	local coins = listAvailableCoins(origin)
	if #coins == 0 then
		return nil, nil
	end
	table.sort(coins, function(a, b)
		return a.straightDist < b.straightDist
	end)

	local bestServer: BasePart? = nil
	local bestWaypoints: { Vector3 }? = nil
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
		showPathLine(bestWaypoints)
		log(string.format("walking to %s (%d studs, %d waypoints, custom path)", bestServer:GetFullName(), math.floor(bestLength), #bestWaypoints))
	else
		clearPathLine()
	end
	return bestServer, bestWaypoints
end

-- Real walking via Humanoid:Move, applied after the default controls so it is not cancelled.
-- Not MoveTo, and not a position tween. Uses WalkSpeed, walk animation, and collisions.
local walkHumanoid: Humanoid? = nil
local walkDirection = Vector3.zero

RunService:BindToRenderStep("AutoCollectWalk", Enum.RenderPriority.Input.Value + 5, function()
	local humanoid = walkHumanoid
	if humanoid and humanoid.Parent and walkDirection.Magnitude > 0.05 then
		humanoid:Move(walkDirection, false)
	end
end)

local function stopWalking()
	walkDirection = Vector3.zero
	local humanoid = walkHumanoid
	walkHumanoid = nil
	if humanoid and humanoid.Parent then
		humanoid:Move(Vector3.zero, false)
	end
end

local function followWaypoints(humanoid: Humanoid, root: BasePart, target: BasePart, waypoints: { Vector3 })
	if humanoid.Sit then
		humanoid.Sit = false
	end
	humanoid.PlatformStand = false
	humanoid.AutoRotate = true
	walkHumanoid = humanoid

	local index = 2
	local stuckSince = os.clock()
	local bestDistance = math.huge

	while index <= #waypoints do
		if not isAvailable(target) then
			stopWalking()
			clearPathLine()
			log("coin gone or already transparent, picking another")
			return
		end
		if humanoid.Parent ~= player.Character then
			stopWalking()
			return
		end

		local position = waypoints[index]
		local flat = Vector3.new(position.X - root.Position.X, 0, position.Z - root.Position.Z)
		local distance = flat.Magnitude
		if distance <= Config.ArriveDistance then
			index += 1
			stuckSince = os.clock()
			bestDistance = math.huge
			continue
		end

		if distance < bestDistance - 0.25 then
			bestDistance = distance
			stuckSince = os.clock()
		elseif os.clock() - stuckSince > Config.StuckTimeout then
			stopWalking()
			markUnreachable(target, "walk stalled before the next path point")
			return
		end

		if Config.AgentCanJump and position.Y > root.Position.Y + 2.5 then
			humanoid.Jump = true
		end

		walkDirection = flat.Unit
		stickLineToPlayer(root)
		RunService.Heartbeat:Wait()
	end

	stopWalking()
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
		stopWalking()
		warn("[AutoCollect] error:", err)
	end
end

log("started for", player.Name, "from", if sourceScript then sourceScript:GetFullName() else "command bar")
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
