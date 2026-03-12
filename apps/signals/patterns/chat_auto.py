import asyncio
import json
import requests
import redis.asyncio as redis

# ============================
# CONFIGURAÇÕES
# ============================

BET_API_URL = "http://localhost:3000/api/bet"
REDIS_URL = "redis://:09T6iVOEmt7p0lEEXiRZATotvS70fPzK@45.179.88.134:6379"
RESULT_CHANNEL = "new_result"  # ajuste conforme seu canal


# ============================
# ENVIO DA APOSTA
# ============================

def enviar_aposta(bets: list[int], roulette_url: str, gales: int = 3, attempts: int = 3):
    """Envia a aposta para a API de betting."""
    
    payload = {
        "bets": bets,
        "attempts": attempts,
        "roulette_url": roulette_url,
        "gales": gales
    }

    print(f"\n📡 Enviando aposta: {bets}")

    try:
        resp = requests.post(
            BET_API_URL,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload),
            timeout=10
        )

        print(f"✅ Resposta: {resp.status_code}")
        
        try:
            print(resp.json())
        except Exception:
            print(resp.text)
            
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Erro ao enviar aposta: {e}")
        return False


# ============================
# INPUT DO USUÁRIO
# ============================

def parse_numbers(input_str: str) -> list[int]:
    """Converte string de números separados por vírgula/espaço em lista de int."""
    
    # remove espaços extras e divide por vírgula ou espaço
    input_str = input_str.strip()
    
    if not input_str:
        return []
    
    # suporta "1,2,3" ou "1 2 3" ou "1, 2, 3"
    parts = input_str.replace(",", " ").split()
    
    numbers = []
    for p in parts:
        try:
            numbers.append(int(p))
        except ValueError:
            print(f"⚠️  '{p}' não é um número válido, ignorando...")
    
    return numbers


def coletar_configuracao() -> dict:
    """Coleta os dados de configuração do usuário."""
    
    print("\n" + "=" * 50)
    print("🎰 CONFIGURAÇÃO DA APOSTA COM GATILHO")
    print("=" * 50)
    
    # Números da aposta
    print("\n📊 Números da aposta (separados por vírgula ou espaço):")
    print("   Exemplo: 1, 2, 3, 14, 15, 16")
    bets_input = input("   > ")
    bets = parse_numbers(bets_input)
    
    if not bets:
        print("❌ Nenhum número de aposta válido!")
        return None
    
    print(f"   ✓ Apostando em: {bets}")
    
    # Gatilhos
    print("\n🎯 Números gatilho (separados por vírgula ou espaço):")
    print("   Quando um desses números cair, a aposta é enviada")
    triggers_input = input("   > ")
    triggers = parse_numbers(triggers_input)
    
    if not triggers:
        print("❌ Nenhum gatilho válido!")
        return None
    
    print(f"   ✓ Gatilhos: {triggers}")
    
    # Slug da mesa
    print("\n🎲 Slug da mesa:")
    print("   Exemplo: pragmatic-brazilian-roulette")
    slug = input("   > ").strip()
    
    if not slug:
        print("❌ Slug não pode ser vazio!")
        return None
    
    print(f"   ✓ Mesa: {slug}")
    
    # URL da roleta (para o bot)
    print("\n🔗 URL da roleta (para o bot de apostas):")
    print("   Exemplo: https://lotogreen.bet.br/play/450")
    roulette_url = input("   > ").strip()
    
    if not roulette_url:
        print("❌ URL não pode ser vazia!")
        return None
    
    # Gales
    print("\n🔄 Quantidade de gales (padrão: 3):")
    gales_input = input("   > ").strip()
    gales = int(gales_input) if gales_input.isdigit() else 3
    
    print(f"   ✓ Gales: {gales}")
    
    # Confirmação
    print("\n" + "=" * 50)
    print("📋 RESUMO DA CONFIGURAÇÃO:")
    print(f"   Apostas:  {bets}")
    print(f"   Gatilhos: {triggers}")
    print(f"   Mesa:     {slug}")
    print(f"   URL:      {roulette_url}")
    print(f"   Gales:    {gales}")
    print("=" * 50)
    
    confirm = input("\n✅ Confirma? (s/n): ").strip().lower()
    
    if confirm != "s":
        print("❌ Configuração cancelada.")
        return None
    
    return {
        "bets": bets,
        "triggers": set(triggers),  # set para lookup O(1)
        "slug": slug,
        "roulette_url": roulette_url,
        "gales": gales
    }


# ============================
# LISTENER DO REDIS
# ============================

async def listen_redis(config: dict):
    """Escuta o canal Redis e dispara aposta quando gatilho é acionado."""
    
    print(f"\n👂 Conectando ao Redis: {REDIS_URL}")
    
    r = await redis.from_url(REDIS_URL)
    pubsub = r.pubsub()
    await pubsub.subscribe(RESULT_CHANNEL)
    
    print(f"✅ Inscrito no canal: {RESULT_CHANNEL}")
    print(f"⏳ Aguardando gatilhos: {config['triggers']}")
    print("-" * 50)
    
    # Estado do monitoramento
    triggers_ativos = set(config["triggers"])  # gatilhos disponíveis
    apostas_pendentes = {}  # {trigger: {"attempts_left": N, "gale": 0}}
    total_reds = 0  # reds consecutivos globais
    numeros_recebidos = 0  # contador total de números
    
    MAX_REDS_CONSECUTIVOS = 2
    MAX_NUMEROS = 50
    
    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, 
                timeout=1.0
            )
            
            if message is None:
                continue
            
            try:
                data = json.loads(message["data"])
            except (json.JSONDecodeError, TypeError):
                continue
            
            slug = data.get("slug")
            number = data.get("result")
            
            # Ignora se não for a mesa configurada
            if slug != config["slug"]:
                continue
            
            if number is None:
                continue
            
            numeros_recebidos += 1
            print(f"\n🔢 [{numeros_recebidos}/{MAX_NUMEROS}] Número: {number}")
            
            # Verifica limite de números
            if numeros_recebidos >= MAX_NUMEROS:
                print(f"\n⛔ LIMITE DE {MAX_NUMEROS} NÚMEROS ATINGIDO!")
                print("🛑 Encerrando script...")
                break
            
            # Verifica apostas pendentes (resultado das apostas anteriores)
            for trigger, estado in list(apostas_pendentes.items()):
                if number in config["bets"]:
                    # WIN!
                    print(f"✅ WIN! Número {number} está na aposta (gatilho: {trigger})")
                    total_reds = 0  # reseta reds consecutivos
                    triggers_ativos.add(trigger)  # libera gatilho novamente
                    del apostas_pendentes[trigger]
                    print(f"🔓 Gatilho {trigger} liberado para nova aposta")
                else:
                    # RED
                    estado["attempts_left"] -= 1
                    estado["gale"] += 1
                    
                    if estado["attempts_left"] > 0:
                        print(f"❌ RED (Gale {estado['gale']}/{config['gales']}) - Aguardando próximo número...")
                    else:
                        # Perdeu todos os gales
                        print(f"💀 RED FINAL! Perdeu aposta do gatilho {trigger}")
                        total_reds += 1
                        del apostas_pendentes[trigger]
                        triggers_ativos.add(trigger)  # libera mesmo assim
                        
                        # Verifica reds consecutivos
                        if total_reds >= MAX_REDS_CONSECUTIVOS:
                            print(f"\n⛔ {MAX_REDS_CONSECUTIVOS} REDS CONSECUTIVOS!")
                            print("🛑 Encerrando script...")
                            return
                
                # Só processa uma aposta pendente por número
                break
            
            # Verifica se é um gatilho ativo (sem aposta pendente)
            if number in triggers_ativos and number not in apostas_pendentes:
                print(f"\n🎯 GATILHO ACIONADO! Número {number}")
                
                # Remove do set de gatilhos ativos
                triggers_ativos.discard(number)
                
                print("⏳ Aguardando 2 segundos...")
                await asyncio.sleep(2)
                
                enviar_aposta(
                    bets=config["bets"],
                    roulette_url=config["roulette_url"],
                    gales=config["gales"]
                )
                
                # Adiciona como aposta pendente
                apostas_pendentes[number] = {
                    "attempts_left": config["gales"] + 1,  # tentativa inicial + gales
                    "gale": 0
                }
                
                print(f"👀 Monitorando resultado... ({config['gales']} gales disponíveis)")
            
            # Status atual
            if apostas_pendentes:
                print(f"📊 Apostas pendentes: {list(apostas_pendentes.keys())}")
            print(f"🎯 Gatilhos disponíveis: {triggers_ativos if triggers_ativos else 'nenhum'}")
            print(f"💔 Reds consecutivos: {total_reds}/{MAX_REDS_CONSECUTIVOS}")
                
    except asyncio.CancelledError:
        print("\n🛑 Monitoramento cancelado.")
    finally:
        await pubsub.unsubscribe(RESULT_CHANNEL)
        await r.close()
        
        # Resumo final
        print("\n" + "=" * 50)
        print("📋 RESUMO FINAL")
        print(f"   Números recebidos: {numeros_recebidos}")
        print(f"   Reds consecutivos: {total_reds}")
        print("=" * 50)


# ============================
# MAIN
# ============================

async def main():
    config = coletar_configuracao()
    
    if config is None:
        return
    
    print("\n🚀 Iniciando monitoramento...")
    
    try:
        await listen_redis(config)
    except KeyboardInterrupt:
        print("\n👋 Encerrando...")


if __name__ == "__main__":
    asyncio.run(main())