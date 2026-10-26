-- Script: ServerScriptService/AutoCollectServer
-- Authoritative coin awards only. Client handles pathfinding / MoveTo.
-- Never trust the client for grants — validate instance, availability, distance.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local folder = ReplicatedStorage:FindFirstChild("AutoCollect")
if not folder then
	folder = Instance.new("Folder")
	folder.Name = "AutoCollect"
	folder.Parent = ReplicatedStorage
end

-- Expect Config ModuleScript under ReplicatedStorage/AutoCollect (place from this pack).
local Config = require(folder:WaitForChild("Config"))

local requestCollect = folder:FindFirstChild("RequestCollect")
if not requestCollect then
	requestCollect = Instance.new("RemoteEvent")
	requestCollect.Name = "RequestCollect"
	requestCollect.Parent = folder
end

local collecting: { [Instance]: boolean } = {}

local function getCoinServer(coin: Instance): BasePart?
	if typeof(coin) ~= "Instance" then
		return nil
	end
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
	-- Intentional: collected coins stay at Transparency = 1 until delayed destroy.
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

local function rootPosition(player: Player): Vector3?
	local character = player.Character
	if not character then
		return nil
	end
	local root = character:FindFirstChild("HumanoidRootPart")
	if root and root:IsA("BasePart") then
		return root.Position
	end
	return nil
end

local function withinCollectRange(player: Player, coin: Instance): boolean
	local origin = rootPosition(player)
	local coinPos = getVisualPosition(coin)
	if not origin or not coinPos then
		return false
	end
	local maxDist = Config.CollectRadius + Config.ServerDistanceSlack
	return (coinPos - origin).Magnitude <= maxDist
end

-- Shared authoritative collect path (also usable from other server scripts).
local function tryCollect(player: Player, coin: Instance): boolean
	if not isAvailable(coin) then
		return false
	end
	if not withinCollectRange(player, coin) then
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

requestCollect.OnServerEvent:Connect(function(player: Player, coin: Instance)
	if typeof(coin) ~= "Instance" then
		return
	end
	-- Only accept Coin_Server parts under a CoinContainer (anti-spoof).
	local server = getCoinServer(coin)
	if not server then
		return
	end
	local container = server:FindFirstAncestor(Config.CoinContainerName)
	if not container then
		return
	end
	tryCollect(player, server)
end)

-- Optional: expose for other server scripts via _G is avoided; bindable if needed later.
print("[AutoCollect] server ready — awards are authoritative; client moves only")
