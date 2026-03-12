import asyncio, json, logging, os, datetime, requests, time, websocket
import pytz

from websockets.exceptions import ConnectionClosedError

from datetime import UTC 

from helpers.utils.redis_client import r

from pymongo import MongoClient


DEFAULT_MONGO_URL_FALLBACK = "mongodb+srv://revesbot:DlBnGmlimRZpIblr@cluster0.c14fnit.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
MONGO_URL = os.getenv("MONGO_URL")
MONGO_URL_FALLBACK_USED = False
if not MONGO_URL:
    MONGO_URL = DEFAULT_MONGO_URL_FALLBACK
    MONGO_URL_FALLBACK_USED = True

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
if MONGO_URL_FALLBACK_USED:
    logger.warning("[config] MONGO_URL ausente; usando fallback hardcoded (deprecated).")

# Mongo
client = MongoClient(MONGO_URL)
db = client["roleta_db"]
collection = db["history"]


class Pragmatic : 
    def __init__(self):
        self.desiredArgs = {
            "210": "pragmatic-auto-mega-roulette",
            "204": "pragmatic-mega-roulette",
            "292": "pragmatic-immersive-roulette-deluxe",
            "213": "pragmatic-korean-roulette",
            "225": "pragmatic-auto-roulette",
            "201": "pragmatic-roulette-2",
            "266": "pragmatic-vip-auto-roulette",
            "226": "pragmatic-speed-auto-roulette",
            "230": "pragmatic-roulete-3",
            "203": "pragmatic-speed-roulette-1",
            "227": "pragmatic-roulette-1",
            "545": "pragmatic-vip-roulette",
            "211a1": "pragmatic-lucky-6-roulette",
            "208": "pragmatic-turkish-mega-roulette",
            "287": "pragmatic-mega-roulette-brazilian",
            "298": "pragmatic-italian-mega-roulette",
            "224": "pragmatic-turkish-roulette",
            "240": "pragmatic-powerup-roulette",
            "205": "pragmatic-speed-roulette-2",
            "233": "pragmatic-romanian-roulette",
            "234": "pragmatic-roulette-italian",
            "237": "pragmatic-brazilian-roulette",
            "222": "pragmatic-german-roulette",
            "221": "pragmatic-russian-roulette",  
            "223": "pragmatic-roulette-italia-tricolore",
            "262": "pragmatic-vietnamese-roulette",
            "206": "pragmatic-roulette-macao"
        }
        self.max_reconnect_attempts = 3
        self.reconnect_attempts = 0
        self.results = {}


    def connect_to_wss(self):
        def on_message(ws, message) :

            data = json.loads(message)
            print(data)
            table_id = data.get("tableId")

            if table_id not in self.desiredArgs or "last20Results" not in data:
                return

            slug = self.desiredArgs[table_id]

            last_result = data["last20Results"][0]
            result = int(last_result["result"])
            game_id = last_result.get("gameId")

            now = datetime.datetime.now(UTC)

            full_result = collection.insert_one({
                "roulette_id": slug,
                "roulette_name" : slug,
                "value": result,
                "timestamp": now
            })

            # trim para 500
            count = collection.count_documents({"roulette_id": slug})
            if count > 200000:
                exced = count - 200000
                antigos = collection.find(
                    {"roulette_id": slug},
                    sort=[("timestamp", 1)],
                    limit=exced
                )
                ids = [d["_id"] for d in antigos]

                collection.delete_many({"_id": {"$in": ids}})

            # Configurar timezone Brasil
            tz_br = pytz.timezone("America/Sao_Paulo")

            br_time = now.astimezone(tz_br)

            """ r.publish("new_result", json.dumps({"slug": slug, "result": result, "full_result" : {
                "_id": str(full_result.inserted_id),
                "roulette_id": slug,
                "roulette_name" : slug,
                "value": result,
                "timestamp": now.isoformat(),
                "timestamp_br": br_time.isoformat(),
                "date": br_time.strftime("%Y-%m-%d"),
                "time": br_time.strftime("%H:%M:%S"),
                "hour": br_time.hour,
                "minute": br_time.minute,
                "day_of_week": br_time.strftime("%A"),
                "formatted": br_time.strftime("%d/%m/%Y %H:%M:%S"),
            }}))
 """
          
                
            print(f"[{slug}] ✅ Resultado salvo: {result} (gameId: {game_id})")
        
        def on_error(ws, error):
            print("Error:", error)

        def on_close(ws, close_status_code, close_msg):
            print("### closed ###")
            self.on_ws_close()
        
        def on_open(ws):
        

            subscribe_message = {
                "type": "subscribe",
                "isDeltaEnabled": True,
                "casinoId": "ppcdd00000006702",
                "key": list(self.desiredArgs.keys()),
                "currency": "BRL"
            }
            print("Connection opened")
            ws.send(json.dumps(subscribe_message))

        self.initiate_connection(on_open, on_message, on_error, on_close)

    def initiate_connection(self, on_open, on_message, on_error, on_close) :
        wss_url = "wss://dga.pragmaticplaylive.net/ws"

        headers = {
            "Origin": "https://client.pragmaticplaylive.net",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        }

        ws = websocket.WebSocketApp(
            wss_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )

        ws.run_forever()

    def on_ws_close(self):
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            print(f"Attempt to reconnect ({self.reconnect_attempts})...")
            time.sleep(1)
            self.connect_to_wss()
        else:
            print("Max reconnect attempts reached. Starting over...")
            self.reconnect_attempts = 0
            self.start()

    def start(self):
        self.reconnect_attempts = 0
        self.connect_to_wss()

if __name__ == "__main__":
    Pragmatic().start()
