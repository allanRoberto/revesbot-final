import json
import logging
import os
import datetime
import requests
import time
import websocket
import threading
from datetime import UTC
from helpers.utils.redis_client import r
from pymongo import MongoClient

DEFAULT_MONGO_URL_FALLBACK = "mongodb+srv://revesbot:DlBnGmlimRZpIblr@cluster0.c14fnit.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
MONGO_URL = os.getenv("MONGO_URL")
MONGO_URL_FALLBACK_USED = False
if not MONGO_URL:
    MONGO_URL = DEFAULT_MONGO_URL_FALLBACK
    MONGO_URL_FALLBACK_USED = True

DEFAULT_EVOLUTION_USERNAME_FALLBACK = "allanrsilva"
DEFAULT_EVOLUTION_PASSWORD_FALLBACK = "419300@Al"

# Configuração de logging mais detalhada
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
if MONGO_URL_FALLBACK_USED:
    logger.warning("[config] MONGO_URL ausente; usando fallback hardcoded (deprecated).")

# Mongo
client = MongoClient(MONGO_URL)
db = client["roleta_db"]
collection = db["history"]


class Evolution:
    def __init__(self):
        evolution_username = os.getenv("EVOLUTION_USERNAME")
        if not evolution_username:
            evolution_username = DEFAULT_EVOLUTION_USERNAME_FALLBACK
            logger.warning("[config] EVOLUTION_USERNAME ausente; usando fallback hardcoded (deprecated).")

        evolution_password = os.getenv("EVOLUTION_PASSWORD")
        if not evolution_password:
            evolution_password = DEFAULT_EVOLUTION_PASSWORD_FALLBACK
            logger.warning("[config] EVOLUTION_PASSWORD ausente; usando fallback hardcoded (deprecated).")

        self.url = "https://vaidebet.bet.br/api/user/login"
        self.payloadLogin = {
            "requestBody": {
                "username": evolution_username,
                "email": "null",
                "phone": "null",
                "keepLoggedIn": "null",
                "password": evolution_password,
                "loginType": "1",
            }
        }

        self.headersLogin = {
            "Content-Type": "application/json",
            "Origin": "https://m.vaidebet.bet.br",
            "Referer": "https://m.vaidebet.bet.br/",
        }

        self.urlevo = "https://vaidebet.bet.br/api/user/casinoapi/openGame"

        self.desiredArgs = {
            "7nyiaws9tgqrzaz3": "evolution-Football-studio-roulette",
            "7x0b1tgh7agmf6hv": "evolution-immersive-roulette",
            "8clwnwrupuvf0osq": "evolution-ruleta-en-vivo",
            "48z5pjps3ntvqc1b": "evolution-auto-roulette",
            "AmericanTable001": "evolution-american-roulette",
            "01rb77cq1gtenhmo": "evolution-auto-roulette-vip",
            "LightningSpain01": "evolution-ruleta-relampago-en-vivo",
            "LightningTable01": "evolution-lightning-roulette",
            "PorROU0000000001": "evolution-roleta-ao-vivo",
            "PorROULigh000001": "evolution-roleta-relampago",
            "RedDoorRoulette1": "evolution-red-door-roulette",
            "SpeedAutoRo00001": "evolution-speed-auto-roulette",
            "XxxtremeLigh0001": "evolution-xxxtreme-lightning-roulette",
            "f1f4rm9xgh4j3u2z": "evolution-auto-roulette-la-partage",
            "k37tle5hfceqacik": "evolution-auto-lightning-roulette",
            "laiayvwaiczqe2p7": "evolution-ruleta-automatica",
            "lkcbrbdckjxajdol": "evolution-speed-roulette",
            "oqa3v7a2t25ydg5e": "evolution-ruleta-bola-rapida-en-vivo",
            "p675txa7cdt6za26": "evolution-ruleta-en-espanol",
            "vctlz20yfnmp1ylr": "evolution-roulette",
            "wzg6kdkad1oe7m5k": "evolution-vip-roulette",
            "mrpuiwhx5slaurcy": "evolution-hippodrome-grand-casino",
            "DoubleBallRou001": "evolution-double-ball-roulette",
        }

        self.max_reconnect_attempts = 5  # Aumentado para mais tentativas
        self.reconnect_attempts = 0
        self.reconnect_delay = 5  # Delay inicial entre reconexões
        self.max_reconnect_delay = 60  # Delay máximo entre reconexões
        self.evoSessionId = None
        self.results = {}
        self.ws = None
        self.running = True
        self.last_message_time = time.time()
        self.ping_interval = 30  # Intervalo de ping em segundos
        self.ping_thread = None
        self.session_refresh_interval = 3600  # Renovar sessão a cada 1 hora
        self.last_session_refresh = time.time()

    def pegar_session(self, attempt=1, max_attempts=5):
        """Obtém uma nova sessão com tratamento de erro melhorado"""
        if attempt > max_attempts:
            logger.error(f"Max attempts ({max_attempts}) reached. Waiting before retry...")
            time.sleep(30)
            return self.pegar_session(1, max_attempts)  # Reinicia as tentativas
        
        try:
            with requests.Session() as session:
                # Timeout para evitar travamento
                response = session.post(
                    self.url, 
                    json=self.payloadLogin, 
                    headers=self.headersLogin,
                    timeout=30
                )

                if response.status_code != 200:
                    raise Exception(f"Login falhou com status code: {response.status_code}")

                logger.info("Login bem-sucedido!")
                dados = response.json()
                traderId = dados["data"]["traderId"]
                pgUser = dados["data"]["code"]
                s7oryO9STV = response.headers.get("s7oryO9STV")

                headersEvo = {
                    "Content-Type": "application/json",
                    "Origin": "https://m.vaidebet.bet.br",
                    "Referer": "https://m.vaidebet.bet.br/",
                    "s7oryO9STV": s7oryO9STV,
                    "X-Pgdevice": "d",
                    "X-Pgtradername": str(traderId),
                    "X-Pgusername": pgUser,
                }

                payloadEvo = {
                    "requestBody": {
                        "gameId": "20801",
                        "channel": "web",
                        "vendorId": 130,
                        "redirectUrl": "https://m.vaidebet.bet.br/ptb/games/livecasino/detail/20801",
                    },
                    "identity": None,
                    "device": "d",
                    "languageId": 23,
                }

                response2 = session.post(
                    self.urlevo, 
                    json=payloadEvo, 
                    headers=headersEvo,
                    timeout=30
                )

                data = response2.json()
                url = data["data"]["gameUrl"]
                response = session.get(url, timeout=30)

                EVOSESSIONID = (
                    response.history[2]
                    .headers["Set-Cookie"]
                    .split("EVOSESSIONID=")[1]
                    .split(";")[0]
                )

                self.last_session_refresh = time.time()
                return EVOSESSIONID

        except requests.exceptions.Timeout:
            logger.error(f"Attempt {attempt} failed: Request timeout")
            time.sleep(5 * attempt)  # Backoff progressivo
            return self.pegar_session(attempt + 1, max_attempts)
        except Exception as e:
            logger.error(f"Attempt {attempt} failed with error: {e}")
            time.sleep(5 * attempt)  # Backoff progressivo
            return self.pegar_session(attempt + 1, max_attempts)

    def refresh_session_if_needed(self):
        """Verifica se a sessão precisa ser renovada"""
        current_time = time.time()
        if current_time - self.last_session_refresh > self.session_refresh_interval:
            logger.info("Refreshing session...")
            new_session = self.pegar_session()
            if new_session:
                self.evoSessionId = new_session
                return True
        return False

    def send_ping(self):
        """Envia ping periodicamente para manter a conexão viva"""
        while self.running and self.ws:
            try:
                time.sleep(self.ping_interval)
                if self.ws and self.ws.sock and self.ws.sock.connected:
                    # Envia um ping frame
                    self.ws.ping()
                    logger.debug("Ping sent")
                    
                    # Verifica se recebemos mensagens recentemente
                    if time.time() - self.last_message_time > 120:  # 2 minutos sem mensagens
                        logger.warning("No messages received for 2 minutes, reconnecting...")
                        self.ws.close()
                        break
            except Exception as e:
                logger.error(f"Error sending ping: {e}")
                break

    def connect_to_wss(self):
        def on_message(ws, message):
            try:
                self.last_message_time = time.time()
                message = json.loads(message)

                # Heartbeat/keepalive response
                if message.get("type") == "lobby.ping":
                    pong_message = {
                        "id": message.get("id"),
                        "type": "lobby.pong"
                    }
                    ws.send(json.dumps(pong_message))
                    logger.debug("Pong sent")
                    return

                if message.get("type") == "lobby.historyUpdated":
                    for arg in message.get("args", {}):
                        if arg in self.desiredArgs:
                            game_name = self.desiredArgs[arg]
                            game_results = message["args"][arg]["results"][0][0]['number']

                            if game_results is not None:
                                slug = game_name
                                last_result = game_results
                                result = int(last_result)
                                now = datetime.datetime.now(UTC)

                                try:
                                    res = collection.insert_one({
                                        "roulette_id": slug,
                                        "roulette_name": slug,
                                        "value": result,
                                        "timestamp": now
                                    })
                                    logger.info(f"Documento inserido com _id={res.inserted_id}")
                                    # Publica o resultado antes do housekeeping do Mongo para reduzir latencia no front.
                                    r.publish("new_result", json.dumps({
                                        "slug": slug,
                                        "result": result,
                                        "full_result": {
                                            "_id": str(res.inserted_id),
                                            "roulette_id": slug,
                                            "roulette_name": slug,
                                            "value": result,
                                            "timestamp": now.isoformat(),
                                        },
                                    }))

                                except Exception as e:
                                    logger.error(f"Erro ao inserir documento no MongoDB: {e}", exc_info=True)

                                # Trim para 2000
                                count = collection.count_documents({"roulette_id": slug})
                                if count > 50000:
                                    excess = count - 50000
                                    antigos = collection.find(
                                        {"roulette_id": slug},
                                        sort=[("timestamp", 1)],
                                        limit=excess
                                    )
                                    ids = [d["_id"] for d in antigos]
                                    collection.delete_many({"_id": {"$in": ids}})
                                logger.info(f"[{slug}] ✅ Resultado salvo: {result}")
                            else:
                                logger.warning(f"No results found for {game_name}")

            except json.JSONDecodeError as e:
                logger.error(f"Error decoding message: {e}")
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)

        def on_error(ws, error):
            logger.error(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            logger.info(f"WebSocket closed - Status: {close_status_code}, Message: {close_msg}")
            if self.ping_thread and self.ping_thread.is_alive():
                self.running = False
                self.ping_thread.join(timeout=5)
            self.on_ws_close()

        def on_open(ws):
            logger.info("WebSocket connection opened")
            self.reconnect_attempts = 0  # Reset counter on successful connection
            self.reconnect_delay = 5  # Reset delay
            
            # Inicia thread de ping
            self.running = True
            self.ping_thread = threading.Thread(target=self.send_ping, daemon=True)
            self.ping_thread.start()
            
            # Envia mensagem inicial
            message = {
                "id": "jbjrenmu5j",
                "type": "lobby.initLobby",
                "args": {"version": 2},
            }
            ws.send(json.dumps(message))
            logger.info("Init lobby message sent")

        self.initiate_connection(on_open, on_message, on_error, on_close)

    def initiate_connection(self, on_open, on_message, on_error, on_close):
        """Inicia a conexão WebSocket com configurações otimizadas"""
        # Verifica se precisa renovar a sessão
        if self.refresh_session_if_needed():
            logger.info("Session refreshed before connecting")

        wss_url = f"wss://vaidebetoss.evo-games.com/public/lobby/socket/v2/s3xlf5xgpo4qfdwx?messageFormat=json&device=Desktop&features=opensAt%2CmultipleHero%2CshortThumbnails%2CskipInfosPublished%2Csmc%2CuniRouletteHistory%2CbacHistoryV2%2Cfilters%2CtableDecorations&instance=cjysk7-s3xlf5xgpo4qfdwx-&EVOSESSIONID={self.evoSessionId}&client_version=6.20250520.71644.51887-e2cf87eb3b"

        # Habilita trace para debug (desabilite em produção)
        # websocket.enableTrace(True)
        
        self.ws = websocket.WebSocketApp(
            wss_url,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            header={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
        )
        
        # Run with automatic reconnection
        self.ws.run_forever(
            ping_interval=30,  # Envia ping a cada 30 segundos
            ping_timeout=10,   # Timeout de 10 segundos para o pong
            reconnect=5        # Tenta reconectar após 5 segundos
        )

    def on_ws_close(self):
        """Lida com o fechamento da conexão WebSocket com backoff exponencial"""
        if self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            # Backoff exponencial com limite máximo
            delay = min(self.reconnect_delay * (2 ** (self.reconnect_attempts - 1)), self.max_reconnect_delay)
            logger.info(f"Tentativa de reconexão {self.reconnect_attempts}/{self.max_reconnect_attempts} em {delay} segundos...")
            time.sleep(delay)
            self.connect_to_wss()
        else:
            logger.warning("Máximo de tentativas de reconexão atingido. Reiniciando do zero...")
            self.reconnect_attempts = 0
            time.sleep(30)  # Espera 30 segundos antes de reiniciar completamente
            self.start()

    def start(self):
        """Inicia o processo de coleta"""
        logger.info("Iniciando Evolution WebSocket Collector...")
        self.reconnect_attempts = 0
        
        while True:
            try:
                evoSessionId = self.pegar_session()
                if evoSessionId:
                    self.evoSessionId = evoSessionId
                    logger.info(f"Session obtained: {evoSessionId[:20]}...")
                    self.connect_to_wss()
                else:
                    logger.error("Failed to obtain session, retrying in 30 seconds...")
                    time.sleep(30)
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                self.running = False
                if self.ws:
                    self.ws.close()
                break
            except Exception as e:
                logger.error(f"Unexpected error in main loop: {e}", exc_info=True)
                time.sleep(30)

if __name__ == "__main__":
    try:
        Evolution().start()
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
