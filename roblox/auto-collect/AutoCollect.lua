-- Client only. Press Play, set the command bar to Client, paste this.
-- Finds CoinVisual, builds a path around walls, walks there.
-- Green line is local. Your server still collects the coins.

local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local Workspace = game:GetService("Workspace")

local player = Players.LocalPlayer
if not player then
	warn("[AutoCollect] Command bar is on the server. Switch it to Client and paste again.")
	return
end

local VISUAL = "CoinVisual"
local SERVER = "Coin_Server"
local CELL = 4
local ARRIVE = 3.5
local STEP_UP = 6

local coins: { [Instance]: boolean } = {}
local rayParams = RaycastParams.new()
rayParams.FilterType = Enum.RaycastFilterType.Exclude

local function worldPosition(inst: Instance): Vector3?
	if inst:IsA("BasePart") then
		return inst.Position
	end
	if inst:IsA("Model") then
		return inst:GetPivot().Position
	end
	if inst:IsA("Attachment") then
		return inst.WorldPosition
	end
	if inst.Parent and inst.Parent:IsA("BasePart") then
		return inst.Parent.Position
	end
	local child = inst:FindFirstChildWhichIsA("BasePart", true)
	if child then
		return child.Position
	end
	return nil
end

local function watch(inst: Instance)
	if inst.Name == VISUAL and inst:IsDescendantOf(Workspace) and worldPosition(inst) ~= nil then
		coins[inst] = true
	end
end

for _, inst in Workspace:GetDescendants() do
	watch(inst)
end
Workspace.DescendantAdded:Connect(watch)
Workspace.DescendantRemoving:Connect(function(inst)
	coins[inst] = nil
end)

local function taken(inst: Instance): boolean
	if inst:IsA("BasePart") and inst.Transparency >= 1 then
		return true
	end
	local server = if inst.Name == SERVER then inst else inst:FindFirstAncestor(SERVER)
	if server and server:IsA("BasePart") and server.Transparency >= 1 then
		return true
	end
	return false
end

local function available(inst: Instance): boolean
	return coins[inst] == true and inst.Parent ~= nil and worldPosition(inst) ~= nil and not taken(inst)
end

local function coinPosition(inst: Instance): Vector3
	return worldPosition(inst) :: Vector3
end

local function refreshFilter()
	local ignore = {}
	if player.Character then
		table.insert(ignore, player.Character)
	end
	for inst in coins do
		table.insert(ignore, inst)
		local server = inst:FindFirstAncestor(SERVER)
		if server then
			table.insert(ignore, server)
		end
	end
	rayParams.FilterDescendantsInstances = ignore
end

local function blocked(a: Vector3, b: Vector3): boolean
	local delta = b - a
	if delta.Magnitude < 0.05 then
		return false
	end
	local flat = Vector3.new(delta.X, 0, delta.Z)
	local side = if flat.Magnitude > 0.01 then flat.Unit:Cross(Vector3.yAxis) * 2 else Vector3.zero
	for _, offset in { Vector3.zero, side, -side } do
		local hit = Workspace:Raycast(a + Vector3.new(0, 2.5, 0) + offset, delta, rayParams)
		if hit then
			return true
		end
	end
	return false
end

local function ground(x: number, z: number, hintY: number): Vector3?
	local hit = Workspace:Raycast(Vector3.new(x, hintY + 12, z), Vector3.new(0, -80, 0), rayParams)
	if hit then
		return hit.Position + Vector3.new(0, 3, 0)
	end
	return nil
end

local function lengthOf(points: { Vector3 }): number
	local total = 0
	for i = 2, #points do
		total += (points[i] - points[i - 1]).Magnitude
	end
	return total
end

local function buildPath(from: Vector3, to: Vector3): { Vector3 }?
	refreshFilter()
	local start = ground(from.X, from.Z, from.Y) or from
	local goal = ground(to.X, to.Z, to.Y) or to
	if not blocked(start, goal) then
		return { start, goal }
	end

	local span = (Vector3.new(goal.X - start.X, 0, goal.Z - start.Z)).Magnitude
	local cell = math.clamp(math.ceil(span / 40), CELL, 12)
	local pad = cell * 3
	local minX = math.min(start.X, goal.X) - pad
	local minZ = math.min(start.Z, goal.Z) - pad
	local cols = math.floor((math.abs(goal.X - start.X) + pad * 2) / cell) + 1
	local rows = math.floor((math.abs(goal.Z - start.Z) + pad * 2) / cell) + 1
	if cols * rows > 8000 then
		return nil
	end

	local function pack(ix: number, iz: number): number
		return ix * 100000 + iz
	end
	local function at(ix: number, iz: number, hintY: number): Vector3?
		return ground(minX + ix * cell, minZ + iz * cell, hintY)
	end

	local sx = math.clamp(math.floor((start.X - minX) / cell + 0.5), 0, cols - 1)
	local sz = math.clamp(math.floor((start.Z - minZ) / cell + 0.5), 0, rows - 1)
	local gx = math.clamp(math.floor((goal.X - minX) / cell + 0.5), 0, cols - 1)
	local gz = math.clamp(math.floor((goal.Z - minZ) / cell + 0.5), 0, rows - 1)
	if not at(sx, sz, start.Y) or not at(gx, gz, goal.Y) then
		return nil
	end

	local open = { { x = sx, z = sz, f = 0 } }
	local function up(i: number)
		while i > 1 do
			local p = math.floor(i / 2)
			if open[p].f <= open[i].f then
				break
			end
			open[p], open[i] = open[i], open[p]
			i = p
		end
	end
	local function down(i: number)
		while true do
			local l = i * 2
			local r = l + 1
			local s = i
			if l <= #open and open[l].f < open[s].f then
				s = l
			end
			if r <= #open and open[r].f < open[s].f then
				s = r
			end
			if s == i then
				break
			end
			open[s], open[i] = open[i], open[s]
			i = s
		end
	end
	local function push(x: number, z: number, f: number)
		table.insert(open, { x = x, z = z, f = f })
		up(#open)
	end
	local function pop()
		local top = open[1]
		local last = table.remove(open)
		if #open > 0 and last then
			open[1] = last
			down(1)
		end
		return top
	end

	local came: { [number]: number } = {}
	local cost: { [number]: number } = { [pack(sx, sz)] = 0 }
	local found = false
	local seen = 0
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

	while #open > 0 and seen < 2500 do
		local node = pop()
		seen += 1
		if node.x == gx and node.z == gz then
			found = true
			break
		end
		local here = at(node.x, node.z, start.Y)
		local key = pack(node.x, node.z)
		if here then
			for _, dir in dirs do
				local nx = node.x + dir[1]
				local nz = node.z + dir[2]
				if nx >= 0 and nz >= 0 and nx < cols and nz < rows then
					local nxt = at(nx, nz, here.Y)
					if nxt and math.abs(nxt.Y - here.Y) <= STEP_UP and not blocked(here, nxt) then
						local nk = pack(nx, nz)
						local nc = (cost[key] or 0) + dir[3]
						if cost[nk] == nil or nc < cost[nk] then
							cost[nk] = nc
							came[nk] = key
							push(nx, nz, nc + math.abs(gx - nx) + math.abs(gz - nz))
						end
					end
				end
			end
		end
	end
	if not found then
		return nil
	end

	local points = { goal }
	local cursor: number? = pack(gx, gz)
	local guard = 0
	while cursor and cursor ~= pack(sx, sz) and guard < 5000 do
		local ix = math.floor(cursor / 100000)
		local iz = cursor - ix * 100000
		local pos = at(ix, iz, goal.Y)
		if pos then
			table.insert(points, 1, pos)
		end
		cursor = came[cursor]
		guard += 1
	end
	table.insert(points, 1, start)
	return points
end

local lineFolder = Instance.new("Folder")
lineFolder.Name = "AutoCollectPath"
lineFolder.Parent = Workspace

local function showLine(points: { Vector3 })
	lineFolder:ClearAllChildren()
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
		node.Shape = Enum.PartType.Ball
		node.Size = if i == #points then Vector3.new(1.4, 1.4, 1.4) else Vector3.new(0.5, 0.5, 0.5)
		node.Position = position
		node.Parent = lineFolder
		local attachment = Instance.new("Attachment")
		attachment.Parent = node
		attachments[i] = attachment
	end
	for i = 1, #attachments - 1 do
		local beam = Instance.new("Beam")
		beam.Attachment0 = attachments[i]
		beam.Attachment1 = attachments[i + 1]
		beam.Width0 = 0.4
		beam.Width1 = 0.4
		beam.FaceCamera = true
		beam.LightEmission = 1
		beam.Color = ColorSequence.new(Color3.fromRGB(0, 255, 80))
		beam.Parent = lineFolder
	end
end

local walkHumanoid: Humanoid? = nil
local walkDirection = Vector3.zero

pcall(function()
	RunService:UnbindFromRenderStep("AutoCollectWalk")
end)
RunService:BindToRenderStep("AutoCollectWalk", Enum.RenderPriority.Camera.Value + 1, function()
	local humanoid = walkHumanoid
	if humanoid and humanoid.Parent and walkDirection.Magnitude > 0.05 then
		humanoid:Move(walkDirection, false)
	end
end)

pcall(function()
	local scripts = player:FindFirstChild("PlayerScripts")
	if scripts then
		local module = scripts:FindFirstChild("PlayerModule")
		if module and module:IsA("ModuleScript") then
			require(module):GetControls():Disable()
			print("[AutoCollect] default controls disabled so the walk is not cancelled")
		end
	end
end)

local function nearestCoin(origin: Vector3): (Instance?, Vector3?)
	local best: Instance? = nil
	local bestPos: Vector3? = nil
	local bestDist = math.huge
	for inst in coins do
		if available(inst) then
			local pos = coinPosition(inst)
			local dist = (Vector3.new(pos.X, 0, pos.Z) - Vector3.new(origin.X, 0, origin.Z)).Magnitude
			if dist < bestDist and dist <= 1000 then
				best = inst
				bestPos = pos
				bestDist = dist
			end
		end
	end
	return best, bestPos
end

local function walkPath(humanoid: Humanoid, root: BasePart, coin: Instance, points: { Vector3 })
	humanoid.Sit = false
	humanoid.PlatformStand = false
	humanoid.AutoRotate = true
	walkHumanoid = humanoid
	showLine(points)
	print("[AutoCollect] walking", coin:GetFullName())

	local index = 2
	local stuck = os.clock()
	local closest = math.huge
	while index <= #points do
		if not available(coin) or humanoid.Parent ~= player.Character then
			break
		end
		local point = points[index]
		local flat = Vector3.new(point.X - root.Position.X, 0, point.Z - root.Position.Z)
		if flat.Magnitude <= ARRIVE then
			index += 1
			stuck = os.clock()
			closest = math.huge
			continue
		end
		if flat.Magnitude < closest - 0.25 then
			closest = flat.Magnitude
			stuck = os.clock()
		elseif os.clock() - stuck > 4 then
			break
		end
		if point.Y > root.Position.Y + 2.5 then
			humanoid.Jump = true
		end
		local startNode = lineFolder:FindFirstChild("Start")
		if startNode and startNode:IsA("BasePart") then
			startNode.Position = root.Position
		end
		walkDirection = flat.Unit
		humanoid:Move(walkDirection, false)
		RunService.Heartbeat:Wait()
	end

	walkDirection = Vector3.zero
	walkHumanoid = nil
	humanoid:Move(Vector3.zero, false)
	lineFolder:ClearAllChildren()
end

local seen = 0
for _ in coins do
	seen += 1
end
print("[AutoCollect] client running, CoinVisual found:", seen)

while true do
	local character = player.Character
	local root = character and character:FindFirstChild("HumanoidRootPart")
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	if root and root:IsA("BasePart") and humanoid and humanoid.Health > 0 then
		local coin, pos = nearestCoin(root.Position)
		if coin and pos then
			local points = buildPath(root.Position, pos) or { root.Position, pos }
			walkPath(humanoid, root, coin, points)
		end
	end
	task.wait(0.2)
end
