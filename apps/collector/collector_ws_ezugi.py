import websocket
import json
import time
import logging
import datetime
import os

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


class Ezugi :
    def __init__(self):
        self.desiredArgs = {
            "221008": "ezugi-roleta-skyline",
            "221000": "ezugi-roleta-rapida",
            "411000":  "ezugi-roleta-espanhola",
            "431000": "ezugi-roleta-del-sol",
            "221003": "ezugi-roleta-diamante",
            "611007": "ezugi-vip-roleta",
            "221005": "ezugi-roleta-namaste",
            "221002": "ezugi-roleta-de-velocidade-automatica",
            "221004": "ezugi-roleta-automatica-prestige",
            "5001"  : "ezugi-roleta-automatica",
            "221009": "ezugi--roleta-automatica-de-futebol",
            "221007": "ezugi-criquete-roleta-automatica",
            "1000"  : "ezugi-roleta-italiana",
            "501000": "ezugi-roleta-turca",
            "601000": "ezugi-roleta-russa",
            "241000": "ezugi-roleta-da-sorte",
            "611000": "ezugi-portomaso-roleta-2",
            "321000": "ezugi-marina-roleta-1",
            "321001": "ezugi-marina-roleta-2",
            "611003": "ezugi-oracle-360-roleta",
            "611001": "ezugi-oracle-real-roleta",
            "481004": "ezugi-ez-dealer-roleta-brazil",
            "481001": "ezugi-ez-dealer-roleta-tailandes",
            "481002": "ezugi-ez-dealer-roleta-japones",
            "481003": "ezugi-ez-dealer-roleta-chines",
        }
        self.max_reconnect_attempts = 3
        self.reconnect_attempts = 0
        self.results = {}
    
    def connect_to_wss(self):
        def on_open(ws):
            print("Connection opened")
    
        def on_error(ws, error):
            print("Error:", error)
        
        def on_close(self):
            if self.reconnect_attempts < self.max_reconnect_attempts:
                self.reconnect_attempts += 1
                print(f"Attempt to reconnect ({self.reconnect_attempts})...")
                time.sleep(5)
                self.start()
            else:
                print("Max reconnect attempts reached. Starting over...")
                self.reconnect_attempts = 0
                self.start()

        def on_message(ws, message):
            try:
                data = json.loads(message)

                if "tableId" in data and data["tableId"] in self.desiredArgs:
                    table_name = self.desiredArgs[data["tableId"]]

                    if "GameResults" in data and "WinningNumber" in data["GameResults"]:
                        winning_number = int(data["GameResults"]["WinningNumber"])

                        now = datetime.datetime.now(UTC)

                        inserted = collection.insert_one({
                            "roulette_id": table_name,
                            "roulette_name" : table_name,
                            "value": winning_number,
                            "timestamp": now
                        })

                        # Publica o resultado antes do housekeeping do Mongo para reduzir latencia no front.
                        r.publish("new_result", json.dumps({
                            "slug": table_name,
                            "result": winning_number,
                            "full_result": {
                                "_id": str(inserted.inserted_id),
                                "roulette_id": table_name,
                                "roulette_name": table_name,
                                "value": winning_number,
                                "timestamp": now.isoformat(),
                            },
                        }))

                        # trim para 500
                        count = collection.count_documents({"roulette_id": table_name})
                        if count > 2000:
                            exced = count - 2000
                            antigos = collection.find(
                                {"roulette_id": table_name},
                                sort=[("timestamp", 1)],
                                limit=exced
                            )
                            ids = [d["_id"] for d in antigos]
                            collection.delete_many({"_id": {"$in": ids}})
                        print(f"[{table_name}] ✅ Resultado salvo: {winning_number}")

                elif "TablesList" in data:
                    for table in data["TablesList"]:
                        if table["tableId"] in self.desiredArgs:
                            table_name = self.desiredArgs[table["tableId"]]
                            if "WinningNumber" in table:
                                winning_number = int(table["WinningNumber"])
                                now = datetime.datetime.now(UTC)

                                inserted = collection.insert_one({
                                    "roulette_id": table_name,
                                    "roulette_name" : table_name,
                                    "value": winning_number,
                                    "timestamp": now
                                })

                                # Publica o resultado antes do housekeeping do Mongo para reduzir latencia no front.
                                r.publish("new_result", json.dumps({
                                    "slug": table_name,
                                    "result": winning_number,
                                    "full_result": {
                                        "_id": str(inserted.inserted_id),
                                        "roulette_id": table_name,
                                        "roulette_name": table_name,
                                        "value": winning_number,
                                        "timestamp": now.isoformat(),
                                    },
                                }))

                                # trim para 500
                                count = collection.count_documents({"roulette_id": table_name})
                                if count > 500:
                                    exced = count - 500
                                    antigos = collection.find(
                                        {"roulette_id": table_name},
                                        sort=[("timestamp", 1)],
                                        limit=exced
                                    )
                                    ids = [d["_id"] for d in antigos]
                                    collection.delete_many({"_id": {"$in": ids}})

                                print(f"[{table_name}] ✅ Resultado salvo: {winning_number}")

            except json.JSONDecodeError:
                print(f"Error decoding message: {message}")
            
            
        self.initiate_connection(on_open, on_message, on_error, on_close)

    def initiate_connection(self, on_open, on_message, on_error, on_close) :
        ws_url = "wss://engine.livetables.io/GameServer/lobby"
        ws = websocket.WebSocketApp(
            ws_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open,
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
    Ezugi().start()
