import asyncio
import json
import os
import websockets
from redis import Redis
from dotenv import load_dotenv

load_dotenv()

EVOLUTION_WS_URL = "wss://a8-latam.evo-games.com/public/lobby/socket/v2/sx2i4kpro6tqmnwi?messageFormat=json&device=Desktop&features=opensAt%2CmultipleHero%2CshortThumbnails%2CskipInfosPublished%2Csmc%2CuniRouletteHistory%2CbacHistoryV2%2Cfilters%2CtableDecorations&instance=rxgr6t-sx2i4kpro6tqmnwi-&EVOSESSIONID=sx2i4kpro6tqmnwis2lbw3bczki3tqvu35f3bd2abc4aad9ea8bd75ce1baf159d81e255d2b450fd69&client_version=6.20250430.211110.51485-e49a43b23d"
#EVOLUTION_WS_URL = "wss://a8-latam.evo-games.com/public/lobby/socket/v2/sx2i4kpro6tqmnwi?messageFormat=json&device=Desktop&features=opensAt%2CmultipleHero%2CshortThumbnails%2CskipInfosPublished%2Csmc%2CuniRouletteHistory%2CbacHistoryV2%2Cfilters%2CtableDecorations&instance=4nmcr8-sx2i4kpro6tqmnwi-&EVOSESSIONID=sx2i4kpro6tqmnwis2ld3illceogpfshd53a881858143c0b2e364dbbe66b4ce646bd00699d84369f&client_version=6.20250430.211110.51485-e49a43b23d"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://www.evolution.com"
}

ids_to_slug = {
    "mvrcophqscoqosd6" : "nao-definido",
    "LightningTable01" : "lightning-roulette",
    "lr6t4k3lcd4qgyrk" : "grand-casino-roulette",
    "laiayvwaiczqe2p7" : "auto-lightning-roulette",
    "SpeedAutoRo00001" : "speed-auto-roulette",
    "LightningSpain01" : "lightning-spanish-roulette",
    "vctlz20yfnmp1ylr" : "1",
    "7x0b1tgh7agmf6hv" : "2",
    "wzg6kdkad1oe7m5k" : "vip-roulette",
    "PorROU0000000001" : "4",
    "7x0b1tgh7agmf6hv" : "5",
    "p675txa7cdt6za26" : "6",
    "7nyiaws9tgqrzaz3" : "7",
    "01rb77cq1gtenhmo" : "8",
    "pnkk4iuchw7blb2p" : "9",
    "XxxtremeLigh0001" : "xxx-extreme-lightning",
    "lkcbrbdckjxajdol" : "10",
    "GoldVaultRo00001" : "gold-vault-roulette",
    "oqa3v7a2t25ydg5e" : "11",
    "k37tle5hfceqacik" : "12",
    "PorROULigh000001" : "13",
    "DoubleBallRou001" : "14",
    "48z5pjps3ntvqc1b" : "15",
}   

PING_INTERVAL = 30  # segundos

async def handle_connection(ws):
    async def keep_alive():
        while True:
            try:
                await ws.ping()
                await asyncio.sleep(PING_INTERVAL)
            except Exception as e:
                print(f"⚠️ Erro no ping: {e}")
                break  # Sai do loop para forçar reconexão

    keep_alive_task = asyncio.create_task(keep_alive())

    try:
        async for msg in ws:
            data = json.loads(msg)
            if data.get("type") == "lobby.historyUpdated":
                args = data.get("args", {})
                for table_id, content in args.items():
                    results = content.get("results", [])
                    flat_numbers = [
                        int(item["number"])
                        for entry in results for item in entry
                        if isinstance(item, dict) and "number" in item
                    ]
                    if flat_numbers:
                        #redis.lpush(f"history:{table_id}", *map(str, flat_numbers))
                        #redis.ltrim(f"history:{table_id}", 0, 49)
                        slug = ids_to_slug.get(table_id, table_id)
                        print(f"🎯 {slug}: {flat_numbers}")
 
    finally:
        keep_alive_task.cancel()
        try:
            await keep_alive_task
        except asyncio.CancelledError:
            pass


async def connect_and_consume():
    while True:
        try:
            async with websockets.connect(EVOLUTION_WS_URL, additional_headers=HEADERS) as ws:
                await handle_connection(ws)
        except Exception as e:
            print(f"⚠️ Erro na conexão WebSocket: {e}")
            print("🔁 Tentando reconectar em 5 segundos...")
            await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(connect_and_consume())

