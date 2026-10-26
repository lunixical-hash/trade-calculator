-- Entirely local. Press Play, set the command bar to Client, paste this.
-- Finds CoinVisual, steers around walls, and moves your character on this client.
-- The green line is parented to the camera, so only you see it.

local player = game.Players.LocalPlayer
if not player then
	warn("[AutoCollect] Switch the command bar to Client, then paste again.")
	return
end

local camera = workspace.CurrentCamera
local VISUAL = "CoinVisual"
local SERVER = "Coin_Server"

local coins = {}
local params = RaycastParams.new()
params.FilterType = Enum.RaycastFilterType.Exclude

local function worldPosition(inst)
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

local function watch(inst)
	if inst.Name == VISUAL and worldPosition(inst) then
		coins[inst] = true
	end
end

for _, inst in workspace:GetDescendants() do
	if inst:IsDescendantOf(workspace) then
		watch(inst)
	end
end
workspace.DescendantAdded:Connect(watch)
workspace.DescendantRemoving:Connect(function(inst)
	coins[inst] = nil
end)

local function taken(inst)
	if inst:IsA("BasePart") and inst.Transparency >= 1 then
		return true
	end
	local server = inst:FindFirstAncestor(SERVER)
	if server and server:IsA("BasePart") and server.Transparency >= 1 then
		return true
	end
	return false
end

local function nearest(origin)
	local best, bestPos, bestDist = nil, nil, 1000
	for inst in coins do
		if inst.Parent and not taken(inst) then
			local pos = worldPosition(inst)
			if pos then
				local flat = Vector3.new(pos.X - origin.X, 0, pos.Z - origin.Z)
				if flat.Magnitude < bestDist then
					best, bestPos, bestDist = inst, pos, flat.Magnitude
				end
			end
		end
	end
	return best, bestPos
end

local function refreshIgnore()
	local ignore = {}
	if player.Character then
		table.insert(ignore, player.Character)
	end
	table.insert(ignore, camera)
	for inst in coins do
		table.insert(ignore, inst)
		local server = inst:FindFirstAncestor(SERVER)
		if server then
			table.insert(ignore, server)
		end
	end
	params.FilterDescendantsInstances = ignore
end

local function wayIsOpen(fromPos, dir, distance)
	local hit = workspace:Raycast(fromPos + Vector3.new(0, 2, 0), dir * distance, params)
	return hit == nil
end

local function steer(fromPos, toPos)
	local flat = Vector3.new(toPos.X - fromPos.X, 0, toPos.Z - fromPos.Z)
	if flat.Magnitude < 0.05 then
		return Vector3.zero
	end
	local forward = flat.Unit
	if wayIsOpen(fromPos, forward, 4) then
		return forward
	end
	local right = forward:Cross(Vector3.yAxis)
	for _, turn in { 35, -35, 70, -70, 110, -110, 160, -160 } do
		local dir = CFrame.Angles(0, math.rad(turn), 0):VectorToWorldSpace(forward)
		if wayIsOpen(fromPos, dir, 4) then
			return dir.Unit
		end
	end
	return forward
end

local folder = camera:FindFirstChild("AutoCollectPath")
if folder then
	folder:Destroy()
end
folder = Instance.new("Folder")
folder.Name = "AutoCollectPath"
folder.Parent = camera

local function place(part, worldPos)
	part.CFrame = camera.CFrame:ToObjectSpace(CFrame.new(worldPos))
end

local function makeNode(name, size)
	local part = Instance.new("Part")
	part.Name = name
	part.Anchored = true
	part.CanCollide = false
	part.CanQuery = false
	part.CanTouch = false
	part.Material = Enum.Material.Neon
	part.Color = Color3.fromRGB(0, 255, 80)
	part.Shape = Enum.PartType.Ball
	part.Size = size
	part.Parent = folder
	local attachment = Instance.new("Attachment")
	attachment.Parent = part
	return part, attachment
end

local startNode, startAtt = makeNode("Start", Vector3.new(0.6, 0.6, 0.6))
local goalNode, goalAtt = makeNode("Goal", Vector3.new(1.3, 1.3, 1.3))
local beam = Instance.new("Beam")
beam.Attachment0 = startAtt
beam.Attachment1 = goalAtt
beam.Width0 = 0.35
beam.Width1 = 0.35
beam.FaceCamera = true
beam.LightEmission = 1
beam.Color = ColorSequence.new(Color3.fromRGB(0, 255, 80))
beam.Parent = folder

pcall(function()
	local module = player.PlayerScripts:FindFirstChild("PlayerModule")
	if module then
		require(module):GetControls():Disable()
	end
end)

local seen = 0
for _ in coins do
	seen += 1
end
print("[AutoCollect] local, CoinVisual found:", seen)

game:GetService("RunService").Heartbeat:Connect(function(dt)
	camera = workspace.CurrentCamera
	if camera and folder.Parent ~= camera then
		folder.Parent = camera
	end
	local character = player.Character
	local root = character and character:FindFirstChild("HumanoidRootPart")
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	if not root or not humanoid or humanoid.Health <= 0 or not camera then
		beam.Enabled = false
		return
	end

	refreshIgnore()
	local _, goal = nearest(root.Position)
	if not goal then
		beam.Enabled = false
		return
	end

	local dir = steer(root.Position, goal)
	beam.Enabled = true
	place(startNode, root.Position)
	place(goalNode, goal)

	if dir.Magnitude < 0.05 then
		return
	end

	humanoid.AutoRotate = true
	humanoid.PlatformStand = false
	humanoid:Move(dir, false)
	local speed = math.max(humanoid.WalkSpeed, 16)
	local step = dir * speed * math.min(dt, 0.05)
	local nextPos = root.Position + step
	root.AssemblyLinearVelocity = Vector3.new(step.X / math.max(dt, 0.001), root.AssemblyLinearVelocity.Y, step.Z / math.max(dt, 0.001))
	root.CFrame = CFrame.lookAt(nextPos, nextPos + dir)
end)
