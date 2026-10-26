-- Script: ServerScriptService/AutoCollect/AutoCollectService
-- Heartbeat-style loop: owners auto-collect available nearby coins only.

local Players = game:GetService("Players")
local Workspace = game:GetService("Workspace")

local Config = require(script.Parent.Config)
local CoinCollect = require(script.Parent.CoinCollect)
local GamePassCache = require(script.Parent.GamePassCache)

local function rootPosition(character: Model): Vector3?
	local root = character:FindFirstChild("HumanoidRootPart")
	if root and root:IsA("BasePart") then
		return root.Position
	end
	return nil
end

-- Maps change often: Workspace.<MapName>.CoinContainer.Coin_Server.CoinVisual
local function eachAvailableCoinServer(callback: (BasePart) -> ())
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
					callback(server)
				end
			end
		end
	end
end

local function sweep(player: Player)
	if not GamePassCache.Owns(player) then
		return
	end
	local character = player.Character
	if not character then
		return
	end
	local origin = rootPosition(character)
	if not origin then
		return
	end

	local radiusSq = Config.CollectRadius * Config.CollectRadius

	eachAvailableCoinServer(function(server)
		local pos = CoinCollect.GetVisualPosition(server)
		if not pos then
			return
		end
		local offset = pos - origin
		if offset:Dot(offset) <= radiusSq then
			CoinCollect.TryCollect(player, server)
		end
	end)
end

task.spawn(function()
	while true do
		for _, player in Players:GetPlayers() do
			task.spawn(sweep, player)
		end
		task.wait(Config.LoopInterval)
	end
end)
