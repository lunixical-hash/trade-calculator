-- ModuleScript: ServerScriptService/AutoCollect/GamePassCache
-- Server-authoritative ownership via MarketplaceService:UserOwnsGamePassAsync.

local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")

local Config = require(script.Parent.Config)

local GamePassCache = {}
local owns: { [number]: boolean } = {}
local lastCheck: { [number]: number } = {}

local function refresh(userId: number): boolean
	if Config.GamePassId == 0 then
		owns[userId] = false
		lastCheck[userId] = os.clock()
		return false
	end

	local ok, result = pcall(function()
		return MarketplaceService:UserOwnsGamePassAsync(userId, Config.GamePassId)
	end)
	owns[userId] = ok and result == true
	lastCheck[userId] = os.clock()
	return owns[userId]
end

function GamePassCache.Owns(player: Player): boolean
	local userId = player.UserId
	local interval = Config.OwnershipRecheckSeconds
	local checked = lastCheck[userId]
	if checked == nil then
		return refresh(userId)
	end
	if interval > 0 and (os.clock() - checked) >= interval then
		return refresh(userId)
	end
	return owns[userId] == true
end

function GamePassCache.Recheck(player: Player): boolean
	return refresh(player.UserId)
end

Players.PlayerAdded:Connect(function(player)
	refresh(player.UserId)
end)

Players.PlayerRemoving:Connect(function(player)
	owns[player.UserId] = nil
	lastCheck[player.UserId] = nil
end)

for _, player in Players:GetPlayers() do
	task.spawn(refresh, player.UserId)
end

return GamePassCache
