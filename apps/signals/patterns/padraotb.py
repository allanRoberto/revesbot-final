import requests
import asyncio
import os
import re
import collections
from datetime import datetime
from core.api import RouletteAPI
from dotenv import load_dotenv

load_dotenv()

# --- DEFINIÇÕES GLOBAIS ---
ROULETTE_WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]
ESPELHOS = {
    6: 9, 9: 6, 12: 21, 19: 16, 16: 19, 21: 12, 23: 32, 32: 23, 29: 26, 26: 29,
    31: 13, 13: 31, 1: 10, 10: 1, 2: 20, 20: 2, 3: 30, 30: 3
}

GLOBAL_STATS = {"green": 0, "red": 0}
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8163117177:AAEkKSKUiprvUhcsHYZsjS-USWfElF5jNIs")
CHAT_ID = os.getenv("CHAT_ID", "-1002470133269")
BUTTON_TEXT = os.getenv("BUTTON_TEXT", "ACESSE A MESA")
TABLE_STATE = {}
# A sua lista de TABLE_TO_MONITOR continua aqui
TABLES_TO_MONITOR = [
    {"name": "Brazilian Roulette", "slug": "pragmatic-brazilian-roulette", "link": "https://lotogreen.bet.br/play/450"},
    {"name": "Mega Roulette", "slug": "pragmatic-mega-roulette", "link": "https://lotogreen.bet.br/play/550"},
    {"name": "Brazilian Roulette", "slug": "pragmatic-brazilian-roulette", "link": "https://lotogreen.bet.br/play/450"},
    {"name": "Auto Roulette", "slug": "pragmatic-auto-roulette", "link": "https://lotogreen.bet.br/play/373"},
    {"name": "Auto Mega Roulette", "slug": "pragmatic-auto-mega-roulette", "link": "https://lotogreen.bet.br/play/543"},
    {"name": "Immersive Roulette Deluxe", "slug": "pragmatic-immersive-roulette-deluxe", "link": "https://lotogreen.bet.br/play/8261"},
    {"name": "Roulette Macao", "slug": "pragmatic-roulette-macao", "link": "https://lotogreen.bet.br/play/457"},
    {"name": "PowerUP Roulette", "slug": "pragmatic-powerup-roulette", "link": "https://lotogreen.bet.br/play/457"},
]

HISTORY_SIZE = 350

def enviar_telegram(message, button_url):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[AVISO] TELEGRAM_TOKEN ou CHAT_ID não configurados.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "reply_markup": {"inline_keyboard": [[{"text": BUTTON_TEXT, "url": button_url}]]}
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [TELEGRAM] Mensagem enviada com sucesso.")
        return True
    except Exception as e:
        error_details = e.response.json() if hasattr(e, 'response') else str(e)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERRO TELEGRAM] Falha ao enviar: {error_details}")
        return False

def get_neighbors(number, num_casas=1):
    if number is None or number not in ROULETTE_WHEEL_ORDER: return set()
    idx = ROULETTE_WHEEL_ORDER.index(number)
    neighbors = set()
    length = len(ROULETTE_WHEEL_ORDER)
    for i in range(1, num_casas + 1):
        neighbors.add(ROULETTE_WHEEL_ORDER[(idx + i) % length])
        neighbors.add(ROULETTE_WHEEL_ORDER[(idx - i + length) % length])
    return neighbors

def get_espelho(numero):
    return ESPELHOS.get(numero)

def get_terminal(n):
    return n % 10

def get_terminals(number):
    # Esta função agora aceita um terminal (0-9) ou um número completo
    term = number if number < 10 else get_terminal(number)
    return {n for n in range(37) if get_terminal(n) == term}

# --- NOVA LÓGICA: ESTRATÉGIA TB-SIDE ---
def analisar_tb_side(historico, table_state, table_name):
    # Parte 1: Verificar se o novo número ativa um padrão pendente
    novo_numero = historico[0]
    sugestao_encontrada = None
    
    # Usamos uma cópia para poder modificar a lista original durante a iteração
    for i, pattern in reversed(list(enumerate(table_state['tb_side_pending']))):
        if novo_numero == pattern['activator_num']:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [{table_name}] TB-SIDE ATIVADO: O número {novo_numero} retornou.")
            
            sugestao_encontrada = {
                'type': 'entrada',
                'alvos': [f"Terminal {pattern['target_terminal']}"],
                'numeros_completos': sorted(list(pattern['bets'])),
                'justificativa': f"Ativação do padrão TB-Side pelo número {novo_numero}."
            }
            # Remove o padrão da lista de pendentes para não ser ativado de novo
            del table_state['tb_side_pending'][i]
            # Retorna a primeira ativação encontrada (a mais recente)
            return sugestao_encontrada

    # Parte 2: Procurar por um novo padrão para "armar"
    if len(historico) < 2:
        return None

    low_num = historico[0]
    lookback_num = historico[1]

    # Condição de "arme": número da 1a dúzia depois de um da 2a ou 3a
    if (1 <= low_num <= 10) and (lookback_num >= 13):
        # Verifica se o histórico é longo o suficiente para a contagem
        if len(historico) > lookback_num:
            reference_num = historico[lookback_num]
            target_terminal = get_terminal(reference_num)
            
            # Monta a aposta
            bets = set()
            numeros_terminais = get_terminals(target_terminal)
            bets.update(numeros_terminais)
            for num in numeros_terminais:
                bets.update(get_neighbors(num, 1))
            bets.add(0) # Proteção no zero
            
            # Cria o padrão pendente
            new_pattern = {
                'activator_num': low_num,
                'target_terminal': target_terminal,
                'bets': bets,
                'armed_at': datetime.now().strftime('%H:%M:%S')
            }
            
            # Adiciona à lista de pendentes e envia aviso
            table_state['tb_side_pending'].append(new_pattern)
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [{table_name}] TB-SIDE ARMADO: Aguardando retorno do número {low_num} para apostar no terminal {target_terminal}.")
            
            # Limita o número de padrões pendentes para evitar sobrecarga de memória
            if len(table_state['tb_side_pending']) > 10:
                table_state['tb_side_pending'].pop(0)

    return None


async def monitorar_tabela(table_config):
    slug, name, link = table_config['slug'], table_config['name'], table_config['link']
    api = RouletteAPI()

    if slug not in TABLE_STATE:
        TABLE_STATE[slug] = {
            "historico_completo": [], 
            "aposta_ativa": {"status": False},
            # Novo estado para a estratégia TB-Side
            "tb_side_pending": [] 
        }
    
    try:
        response = await api.api(slug, num_results=HISTORY_SIZE)
        if response and response.get("results"):
            TABLE_STATE[slug]["historico_completo"] = [int(r) for r in response["results"]]
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [SETUP - {name}] Histórico de {len(response['results'])} resultados carregado.")
    except Exception as e:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERRO] Falha ao carregar histórico inicial para {name}: {e}")
        return

    while True:
        try:
            aposta_ativa = TABLE_STATE[slug]["aposta_ativa"]
            response = await api.api(slug, num_results=1)
            if not response or not response.get("results"): await asyncio.sleep(5); continue
            
            novo_numero = int(response["results"][0])
            if TABLE_STATE[slug]["historico_completo"] and novo_numero == TABLE_STATE[slug]["historico_completo"][0]: await asyncio.sleep(5); continue
            
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}][{name}] NOVO NÚMERO: {novo_numero}")
            
            TABLE_STATE[slug]["historico_completo"].insert(0, novo_numero)
            if len(TABLE_STATE[slug]["historico_completo"]) > HISTORY_SIZE:
                TABLE_STATE[slug]["historico_completo"].pop()
            
            historico_atual = TABLE_STATE[slug]["historico_completo"]

            if aposta_ativa.get("status"):
                aposta_ativa["tentativas_restantes"] -= 1
                vitoria = novo_numero in aposta_ativa["numeros_completos"]
                
                if vitoria:
                    GLOBAL_STATS["green"] += 1
                    report = (f"✅ GREEN - {name}\n\n"
                              f"O número {novo_numero} foi sorteado! Vitória na tentativa {3 - aposta_ativa['tentativas_restantes']}.\n\n"
                              f"📊 Estatísticas: {GLOBAL_STATS['green']} Greens | {GLOBAL_STATS['red']} Reds")
                    enviar_telegram(report, link)
                    aposta_ativa["status"] = False
                elif aposta_ativa["tentativas_restantes"] <= 0:
                    GLOBAL_STATS["red"] += 1
                    report = (f"❌ RED - {name}\n\n"
                              f"O sinal não se concretizou. Alvos eram: {aposta_ativa['numeros_completos']}\n\n"
                              f"📊 Estatísticas: {GLOBAL_STATS['green']} Greens | {GLOBAL_STATS['red']} Reds")
                    enviar_telegram(report, link)
                    aposta_ativa["status"] = False
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{name}] Tentativa {3 - aposta_ativa['tentativas_restantes']}/3 falhou.")
            
            if not aposta_ativa.get("status"):
                # Chama a nova função de análise TB-Side
                sugestao = analisar_tb_side(historico_atual, TABLE_STATE[slug], name)
                
                if sugestao and sugestao['type'] == 'entrada':
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{name}] SUGESTÃO TB-SIDE ENCONTRADA")
                    TABLE_STATE[slug]["aposta_ativa"] = {"status": True, "tentativas_restantes": 3, **sugestao}
                    
                    msg = (f"🚨 ENTRADA CONFIRMADA (TB-Side) - {name} 🚨\n\n"
                           f"Análise: {sugestao['justificativa']}\n\n"
                           f"🎯 Alvo: {sugestao['alvos']}\n"
                           f"🛡️ Proteções Ativadas!\n\n"
                           f"📲 Fazer entrada em:\n{sugestao['numeros_completos']}\n\n"
                           f"⚠️ Apostar por até 3 tentativas.")
                    enviar_telegram(msg, link)
            
            await asyncio.sleep(10)
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [ERRO CRÍTICO - {name}] Erro no loop: {e}")
            import traceback
            traceback.print_exc()
            await asyncio.sleep(30)

async def main_async():
    tasks = [monitorar_tabela(table_info) for table_info in TABLES_TO_MONITOR]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Iniciando o monitoramento de roletas com a nova estratégia TB-Side...")
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Monitoramento encerrado pelo usuário.")