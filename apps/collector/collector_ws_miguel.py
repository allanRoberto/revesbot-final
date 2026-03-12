import asyncio, json, logging, os, datetime, requests, time, websocket

from websockets.exceptions import ConnectionClosedError

from datetime import UTC 

from helpers.utils.redis_client import r

from pymongo import MongoClient


MONGO_URL = os.getenv("MONGO_URL")

logging.basicConfig(level=logging.INFO)

# Mongo
client = MongoClient(MONGO_URL)
db = client["roleta_db"]
collection = db["history"]


class Results : 
    def __init__(self):

        self.ignoredArgs = {
            "Ruleta Latinoamérica bet36" : "Ruleta Latinoamérica bet36",
            "American Roulette" : "American Roulette",
            "bet365 Roulette" : "bet365 Roulette",
            "bet365 Dutch Roulette" : "bet365 Dutch Roulette",
            "Ruleta Latinoamérica bet365" : "Ruleta Latinoamérica bet365",
            "Slingshot": "Slingshot",
            "Prime Slingshot" : "Prime Slingshot",
            "Ruleta Latinoamérica bet365" : "Ruleta Latinoamérica bet365",
            "Spread Bet Roulette" : "Spread Bet Roulette",
            "bet365 Roulette" : "bet365 Roulette",
            "Roleta Brasileira bet365" : "Roleta Brasileira bet365",
            "bet365 Dutch Roulette" : "bet365 Dutch Roulette",
            "Super Spin Roulette" : "Super Spin Roulette",
            "Roleta Green" : "Roleta Green",
            "Roleta Azure" : "Roleta Azure",
            "Ruby Roulette" : "Ruby Roulette",
            "Roleta Rapida 1" : "Roleta Rapida 1",
            "Roleta Rapida 2" : "Roleta Rapida 2",
            "VIP Roulette - The Club" : "VIP Roulette - The Club"
        }

        self.desiredArgs = {
            "Quantum Auto Roulette": "playtech-quantum-auto-roulette",
            "Quantum Roulette Live": "playtech-quantum-roulette",
            "Prestige Roulette" : "playtech-prestige-roulette",
            "Bucharest Roulette" : "playtech-bucharest-roulette",
            "Greek Quantum Roulette": "playtech-greek-quantum-roulette",
            "Greek Roulette": "playtech-greek-roulette",
            "Mega Fire Blaze Roulette Live": "playtech-mega-fire-blaze-roulette-live",
            "Turkish Roulette" : "playtech-turkish-roulette",
            "Arabic Roulette" : "playtech-arabic-roulette",
            "Roleta Brasileira" : "playtech-roleta-brasileira",
            "Football Roulette" : "playtech-football-roulette",
            "Football French Roulette" : "playtech-football-french-roulette",
            "Roulette Italiana" : "playtech-roulette-italiana",

            # "Roulette Macao" : "pragmatic-roulette-macao",
            # "Roleta Brasileira Pragmatic" : "pragmatic-brazilian-roulette",
            # "Mega Roulette" : "pragmatic-mega-roulette",
            # "Power Up Roulette": "pragmatic-powerup-roulette",
            # "Immersive Roulette Deluxe": "pragmatic-immersive-roulette-deluxe",
            # "Auto Mega Roulette": "pragmatic-auto-mega-roulette",
            # "Auto Roulette": "pragmatic-auto-roulette",

            # "7x0b1tgh7agmf6hv": "evolution-immersive-roulette",
            # "8clwnwrupuvf0osq": "evolution-ruleta-en-vivo",
            # "48z5pjps3ntvqc1b": "evolution-auto-roulette",
            # "01rb77cq1gtenhmo": "evolution-auto-roulette-vip",
            # "LightningSpain01": "evolution-ruleta-relampago-en-vivo",
            # "LightningTable01": "evolution-lightning-roulette",
            # "PorROU0000000001": "evolution-roleta-ao-vivo",
            # "PorROULigh000001": "evolution-roleta-relampago",
            # "SpeedAutoRo00001": "evolution-speed-auto-roulette",
            # "XxxtremeLigh0001": "evolution-xxxtreme-lightning-roulette",
            # "laiayvwaiczqe2p7": "evolution-ruleta-automatica",
            # "lkcbrbdckjxajdol": "evolution-speed-roulette",
            # "oqa3v7a2t25ydg5e": "evolution-ruleta-bola-rapida-en-vivo",
            # "p675txa7cdt6za26": "evolution-ruleta-en-espanol",
            # "vctlz20yfnmp1ylr": "evolution-roulette",
            # "wzg6kdkad1oe7m5k": "evolution-vip-roulette",



            
        }
        self.max_reconnect_attempts = 3
        self.reconnect_attempts = 0
        self.results = {}


    def connect_to_wss(self):
        def on_message(ws, message) :

            data = json.loads(message)

            game_key = data.get("key")

            game_type = data.get("game_type")
            game  = data.get("game")
            results = data.get("results")


            if not game_type == "roleta" :
                return

            if game_key not in self.desiredArgs:
                if game_key in self.ignoredArgs : 
                    #print(f"🔴 Roleta ignorada {game}")
                    return
                print(f"\n\nIgnorando resultado da roleta {game} - {game_key} - {results}\n\n")
                return
            
            slug = self.desiredArgs[game_key]   
            result = int(results[0])

            #print(f"[{slug}] ✅ Resultado salvo: {results[0]}")

            now = datetime.datetime.now(UTC)

            collection.insert_one({
                "roulette_id": slug,
                "roulette_name" : slug,
                "value": result,
                "timestamp": now
            })

            # trim para 500
            count = collection.count_documents({"roulette_id": slug})
            if count > 50000:
                exced = count - 50000
                antigos = collection.find(
                    {"roulette_id": slug},
                    sort=[("timestamp", 1)],
                    limit=exced
                )
                ids = [d["_id"] for d in antigos]

                collection.delete_many({"_id": {"$in": ids}})

            r.publish("new_result", json.dumps({"slug": slug, "result": result}))

            print(f"[{slug}] ✅ Resultado salvo: {result} (gameId: {game})")
        
        def on_error(ws, error):
            print("Error:", error)

        def on_close(ws, close_status_code, close_msg):
            print("### closed ###")
            self.on_ws_close()
        
        def on_open(ws):
            print("Connection opened")
           

        self.initiate_connection(on_open, on_message, on_error, on_close)

    def initiate_connection(self, on_open, on_message, on_error, on_close) :
        wss_url = "ws://177.93.108.140:8777"

    
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
    Results().start()