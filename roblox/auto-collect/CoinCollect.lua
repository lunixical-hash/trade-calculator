-- ModuleScript: ServerScriptService/AutoCollect/CoinCollect
-- Single authoritative award path. Manual pickup and auto-collect both use TryCollect.

local Players = game:GetService("Players")

local Config = require(script.Parent.Config)

local CoinCollect = {}
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

function CoinCollect.GetVisualPosition(coin: Instance): Vector3?
	local server = getCoinServer(coin)
	if not server then
		return nil
	end
	local visual = getCoinVisual(server)
	return visual and visual.Position or nil
end

-- True only for coins that are still available (not already collected / fading out).
function CoinCollect.IsAvailable(coin: Instance): boolean
	if collecting[coin] or not coin.Parent then
		return false
	end
	local server = getCoinServer(coin)
	if not server or not server.Parent then
		return false
	end
	-- Intentional: collected coins set Transparency to 1 before they are destroyed.
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

-- Award coins. Replace with your economy API if you do not use leaderstats.Coins.
local function award(player: Player, amount: number)
	local stats = player:FindFirstChild("leaderstats")
	local coins = stats and stats:FindFirstChild("Coins")
	if coins and coins:IsA("IntValue") then
		coins.Value += amount
	end
end

function CoinCollect.TryCollect(player: Player, coin: Instance): boolean
	if not CoinCollect.IsAvailable(coin) then
		return false
	end
	if not player.Character then
		return false
	end

	local server = getCoinServer(coin)
	if not server then
		return false
	end

	collecting[coin] = true
	collecting[server] = true

	local amount = coinValue(coin)

	-- Match existing game behavior: hide immediately, destroy a moment later.
	-- Do not Destroy() here — that would race auto-collect onto a fading coin.
	server.Transparency = Config.CollectedTransparency
	local visual = server:FindFirstChild(Config.CoinVisualName)
	if visual and visual:IsA("BasePart") then
		visual.Transparency = Config.CollectedTransparency
	end
	if server:IsA("BasePart") then
		server.CanTouch = false
		server.CanQuery = false
	end

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

-- Optional: hook touch pickup to the same path (bind on CoinVisual or Coin_Server).
function CoinCollect.BindTouch(coin: Instance)
	local server = getCoinServer(coin)
	if not server then
		return
	end
	local touchPart = getCoinVisual(server) or server
	touchPart.Touched:Connect(function(hit)
		local character = hit:FindFirstAncestorOfClass("Model")
		local player = character and Players:GetPlayerFromCharacter(character)
		if player then
			CoinCollect.TryCollect(player, server)
		end
	end)
end

return CoinCollect
