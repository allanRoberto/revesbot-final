# Padrão dos similares, 5 ocorrencias, 10 puxados.
import time
import requests
import os
import re
from datetime import datetime
import pytz
from collections import deque, Counter
from colorama import Fore, Style, init

# Inicializa o colorama para que funcione em todos os terminais
init(autoreset=True)

# --- CONFIGURAÇÕES GLOBAIS ---
# Bot "Patchoko bot" enviando chat pessoal
TOKEN = '8390745428:AAHX5Iaahc3AKPVFxYCl7-EQvzSeiivuuvI'
CHAT_ID = '1800974676'
INTERVALO = 5 # segundos entre verificações
ASSERTIVIDADE_MINIMA = 84.99
MIN_AMOSTRAS_INICIAL = 10
MIN_AMOSTRAS_CONTINUO = 20

# TIMEZONE BRASÍLIA
FUSO_BRASILIA = pytz.timezone("America/Sao_Paulo")

# --- VIZINHOS NA ROLETA EUROPEIA ---
VIZINHOS = {
    0: (26, 32), 1: (33, 20), 2: (21, 25), 3: (35, 26), 4: (19, 21),
    5: (10, 24), 6: (34, 27), 7: (29, 28), 8: (30, 23), 9: (22, 18),
    10: (23, 5), 11: (36, 30), 12: (28, 35), 13: (27, 36), 14: (20, 31),
    15: (32, 19), 16: (24, 33), 17: (25, 34), 18: (22, 29), 19: (15, 4),
    20: (1, 14), 21: (4, 2), 22: (9, 18), 23: (8, 10), 24: (5, 16),
    25: (2, 17), 26: (3, 0), 27: (6, 13), 28: (7, 12), 29: (18, 7),
    30: (11, 8), 31: (14, 9), 32: (0, 15), 33: (16, 1), 34: (17, 6),
    35: (12, 3), 36: (13, 11)
}

# --- DICIONÁRIO DE ESPELHOS ---
ESPELHOS = {
    1: [10], 2: [20, 22], 3: [30], 6: [9], 9: [6], 10: [1], 11: [11],
    12: [21], 13: [31], 16: [19], 19: [16], 20: [2, 22], 21: [12],
    22: [2, 20], 23: [32], 26: [29], 29: [26], 30: [3], 31: [13],
    32: [23],
}

# --- MESAS, FICHAS E PROVEDORES ---
MESAS_API = {
    "Brazilian Roulette": "https://api.revesbot.com.br/history/pragmatic-brazilian-roulette",
    "Auto Roulette": "https://api.revesbot.com.br/history/pragmatic-auto-roulette",
    "Immersive Roulette Deluxe": "https://api.revesbot.com.br/history/pragmatic-immersive-roulette-deluxe",
    "Mega Roulette": "https://api.revesbot.com.br/history/pragmatic-mega-roulette",
    "Auto Mega Roulette": "https://api.revesbot.com.br/history/pragmatic-auto-mega-roulette",
}

FICHAS_MINIMAS = {
    "Brazilian Roulette": 0.50, "Auto Roulette": 0.50, "Immersive Roulette Deluxe": 0.50,
    "Mega Roulette": 0.50, "Auto Mega Roulette": 0.50,
}

MESAS_PROVEDORES = {
    "Brazilian Roulette": "Pragmatic", "Auto Roulette": "Pragmatic",
    "Immersive Roulette Deluxe": "Pragmatic", "Mega Roulette": "Pragmatic",
    "Auto Mega Roulette": "Pragmatic",
}

PROVEDORES_BLOQUEADOS = ["EVOLUTION"]

# --- VARIÁVEIS DE ESTADO ---
history = {f"{MESAS_PROVEDORES[mesa]}:{mesa}": deque(maxlen=500) for mesa in MESAS_API.keys()}
monitoramento_sinais = {}
estatisticas = {
    "entradas": 0, "greens": 0, "reds": 0, "tentativas": Counter(),
    "greens_por_ficha_e_tentativa": Counter(), "reds_por_ficha": Counter(),
    "reds_por_ficha_e_tentativa": Counter()
}

estatisticas_por_tipo_de_sinal = {
    "Similaridade": {"entradas": 0, "greens": 0, "reds": 0}
}

# NOVAS ESTATÍSTICAS BRUTAS
estatisticas_brutas = {
    "total_entradas": Counter(), "greens": Counter(), "reds": Counter()
}
ranking_fichas = {}
sinais_enviados_telegram = {}
sinais_acumulados_internamente = {}

sinais_por_hora = {hora: 0 for hora in range(24)}
total_sinais_dia = 0
ultima_hora = datetime.now(FUSO_BRASILIA).hour
START_TIME = time.time()

# Armazena o último gatilho analisado para cada mesa
ultimo_gatilho_analisado = {}
ultimo_resultado_ranking = None # Alterado para None para o primeiro envio

# Variáveis para controle de erro
tempo_espera_erro = 0
contador_erros_consecutivos = 0

# --- FUNÇÃO PARA DEFINIR MAX TENTATIVAS ---
def get_max_tentativas(num_fichas):
    return 5 if num_fichas < 8 else 4

# --- FUNÇÕES DE TELEGRAM ---
def enviar_telegram(msg: str, parse_mode='Markdown'):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    try:
        requests.post(url, data={'chat_id': CHAT_ID, 'text': msg, 'parse_mode': parse_mode})
    except:
        pass

def enviar_sinal_telegram_imediato(dados_sinal):
    """Envia o sinal para o Telegram imediatamente após a validação."""
    total_fichas = dados_sinal['fichas']
    mesa = dados_sinal['mesa']
    link_api = dados_sinal['link_api']

    # Calcula a assertividade para incluir na mensagem
    sinais_acumulados = sinais_acumulados_internamente.get(mesa, {}).get(total_fichas, None)
    num_amostras = 0
    assertividade = 0.0
    if sinais_acumulados:
        num_amostras = len(sinais_acumulados['resultados'])
        if num_amostras > 0:
            greens = sinais_acumulados['resultados'].count('Green')
            assertividade = (greens / num_amostras * 100)

    mensagem = (
        f"🎯 **SINAL ENVIADO**\n"
        f"🎰 Mesa: {mesa}\n"
        f"💰 Ficha mínima: {FICHAS_MINIMAS.get(mesa, 0)}\n"
        f"♻️ Gatilho: {dados_sinal['gatilho']}\n"
        f"🎯 Alvos Principais: {', '.join(map(str, sorted(set(dados_sinal['alvos']))))}\n"
        f"💰 Fichas: {total_fichas} ({dados_sinal['max_tentativas']} tentativas)\n"
        f"📊 Assertividade Atual: {assertividade:.2f}% ({greens}/{num_amostras})\n"
        f"🔗 API: {link_api}\n"
    )
    enviar_telegram(mensagem)

def enviar_relatorio(dados_sinal, status, tentativa_vitoria=None, max_tentativas=None):
    global estatisticas, estatisticas_por_tipo_de_sinal, ranking_fichas, ultimo_resultado_ranking

    fichas_da_jogada = len(dados_sinal['alvos'])

    # Contabiliza os resultados nas estatísticas brutas (sempre)
    estatisticas_brutas["total_entradas"][fichas_da_jogada] += 1
    if status == 'Green':
        estatisticas_brutas["greens"][fichas_da_jogada] += 1
    else:
        estatisticas_brutas["reds"][fichas_da_jogada] += 1

    mesa = dados_sinal['mesa']
    gatilho = dados_sinal['gatilho']
    alvos = dados_sinal['alvos']
    link_api = dados_sinal['link_api']
    tipo_sinal = dados_sinal['tipo']

    estatisticas['entradas'] += 1
    estatisticas_por_tipo_de_sinal[tipo_sinal]['entradas'] += 1

    if max_tentativas is None:
        return

    if status == 'Green':
        estatisticas['greens'] += 1
        estatisticas_por_tipo_de_sinal[tipo_sinal]['greens'] += 1
        estatisticas['tentativas'][(tentativa_vitoria, max_tentativas)] += 1
        estatisticas['greens_por_ficha_e_tentativa'][(fichas_da_jogada, tentativa_vitoria, max_tentativas)] += 1
        msg_status = (
            f"✅ _Green_ na {tentativa_vitoria}/{max_tentativas} tentativa!\n"
        )
    else:
        estatisticas['reds'] += 1
        estatisticas_por_tipo_de_sinal[tipo_sinal]['reds'] += 1
        estatisticas['reds_por_ficha'][(fichas_da_jogada, max_tentativas)] += 1
        estatisticas['reds_por_ficha_e_tentativa'][(fichas_da_jogada, max_tentativas)] += 1
        msg_status = f"❌ _Red_ (nenhum alvo nos últimos {max_tentativas} sorteios)."

    assertividade = (estatisticas['greens']/estatisticas['entradas']*100) if estatisticas['entradas']>0 else 0

    tentativas_str_list = []
    for (tentativa, max_tent), count in sorted(estatisticas['tentativas'].items()):
        tentativas_str_list.append(f"{tentativa}/{max_tent} - {count} vitórias")
    tentativas_str = "\n".join(tentativas_str_list)

    ganhos_por_fichas = {}
    for (fichas, tentativa, max_tentativa), count in estatisticas['greens_por_ficha_e_tentativa'].items():
        if fichas not in ganhos_por_fichas:
            ganhos_por_fichas[fichas] = []
        ganhos_por_fichas[fichas].append(f"{count}x {tentativa}/{max_tentativa}")

    greens_str = "\n".join([f"{fichas} fichas - ({' | '.join(itens)})" for fichas, itens in sorted(ganhos_por_fichas.items())])

    perdas_por_fichas = {}
    for (fichas, max_tentativa), count in estatisticas['reds_por_ficha_e_tentativa'].items():
        if fichas not in perdas_por_fichas:
            perdas_por_fichas[fichas] = []
        perdas_por_fichas[fichas].append(f"{count}x {max_tentativa}")

    reds_str = "\n".join([f"{fichas} fichas - ({' | '.join(itens)})" for fichas, itens in sorted(perdas_por_fichas.items())])

    assertividade_similaridade = (estatisticas_por_tipo_de_sinal['Similaridade']['greens'] / estatisticas_por_tipo_de_sinal['Similaridade']['entradas'] * 100) if estatisticas_por_tipo_de_sinal['Similaridade']['entradas'] > 0 else 0

    mensagem = (
        f"✅ **RELATÓRIO DE RESULTADOS**\n"
        f"🎰 Mesa: {mesa}\n"
        f"🔗 API: {link_api}\n"
        f"♻️ Gatilho: {gatilho}\n"
        f"🎯 Alvos: {', '.join(map(str, sorted(set(alvos))))}\n"
        f"--- {tipo_sinal.upper()} ---\n{msg_status}\n---\n"
        f"RESUMO GERAL:\n\n"
        f"📈 Total Entradas: {estatisticas['entradas']}\n"
        f"✅ Greens: {estatisticas['greens']}\n"
        f"❌ Reds: {estatisticas['reds']}\n"
        f"📊 Assertividade: {assertividade:.2f}%\n"
        f"-----------------\n"
        f"📈 Entradas {tipo_sinal}: {estatisticas_por_tipo_de_sinal[tipo_sinal]['entradas']}\n"
        f"✅ Greens {tipo_sinal}: {estatisticas_por_tipo_de_sinal[tipo_sinal]['greens']}\n"
        f"❌ Reds {tipo_sinal}: {estatisticas_por_tipo_de_sinal[tipo_sinal]['reds']}\n"
        f"📊 Assertividade {tipo_sinal}: {assertividade_similaridade:.2f}%\n"
        f"---\n"
        f"📊 Estatísticas por Tentativa:\n{tentativas_str}\n"
        f"---\n"
        f"💰 Relatório ganhos e fichas\n"
        f"✅ Green\n{greens_str}\n"
        f"❌ Red\n{reds_str}"
    )
    enviar_telegram(mensagem)

    # Lógica de atualização do ranking para envio no terminal e no telegram
    novo_ranking_ordenado = []
    for mesa, dados_fichas in sinais_acumulados_internamente.items():
        for fichas, dados in dados_fichas.items():
            resultados = dados['resultados']
            total_amostras = len(resultados)

            if total_amostras >= 10:
                greens = resultados.count('Green')
                reds = resultados.count('Red')
                assertividade = (greens / total_amostras * 100) if total_amostras > 0 else 0
                novo_ranking_ordenado.append((assertividade, mesa, fichas, greens, reds, total_amostras))

    novo_ranking_ordenado.sort(key=lambda x: x[0], reverse=True)

    if novo_ranking_ordenado != ultimo_resultado_ranking:
        exibir_ranking_debug()
        enviar_ranking_telegram(novo_ranking_ordenado) # NOVO: Envia o ranking completo para o Telegram
        ultimo_resultado_ranking = novo_ranking_ordenado

# NOVO: Função para enviar o ranking completo para o Telegram
def enviar_ranking_telegram(ranking_data):
    if not ranking_data:
        return

    total_amostras_geral = 0
    total_greens_geral = 0
    total_reds_geral = 0

    # Header da mensagem
    mensagem = "*📊 RANKING DE MESAS - ATUALIZAÇÃO 📊*\n\n"

    for assertividade, mesa, fichas, greens, reds, total_amostras in ranking_data:
        mensagem += f"📊 Mesa: {mesa} | Fichas: {fichas} | Greens: {greens} | Reds: {reds} | Assertividade: {assertividade:.2f}% | Total: {total_amostras}\n"
        total_amostras_geral += total_amostras
        total_greens_geral += greens
        total_reds_geral += reds

    # Calcula a assertividade geral
    assertividade_geral = (total_greens_geral / total_amostras_geral * 100) if total_amostras_geral > 0 else 0

    # Adiciona a linha de total geral
    mensagem += f"\n--- *TOTAL GERAL* ---\n"
    mensagem += f"✅ Greens: {total_greens_geral}\n"
    mensagem += f"❌ Reds: {total_reds_geral}\n"
    mensagem += f"📈 Amostras: {total_amostras_geral}\n"
    mensagem += f"📊 Assertividade: {assertividade_geral:.2f}%\n"

    enviar_telegram(mensagem, parse_mode='Markdown')


def exibir_ranking_debug():
    global sinais_acumulados_internamente
    print(f"\n{Fore.MAGENTA}--- RANKING INTERNO DE FICHAS (DEBUG) ---{Style.RESET_ALL}")
    ranking_disponivel = False
    for mesa, dados_fichas in sinais_acumulados_internamente.items():
        for fichas, dados in dados_fichas.items():
            resultados = dados['resultados']
            entradas = len(resultados)

            if entradas > 0:
                greens = resultados.count('Green')
                reds = resultados.count('Red')
                assertividade = (greens / entradas * 100) if entradas > 0 else 0

                ranking_disponivel = True
                print(f"📊 Mesa: {mesa} | Fichas: {fichas} | Greens: {greens} | Reds: {reds} | Assertividade: {assertividade:.2f}% | Total: {entradas}")

    if not ranking_disponivel:
        print("Nenhum resultado de sinal (10-14 fichas) ainda.")

# --- FUNÇÃO AUXILIAR PARA VIZINHOS ---
def get_vizinhos_roleta(numero, vizinhos_dict, count=1):
    protecoes = set()
    if numero in vizinhos_dict:
        v = vizinhos_dict[numero]
        protecoes.add(v[0])
        protecoes.add(v[1])
        if count > 1:
            vizinhos_vizinho_dir = vizinhos_dict.get(v[0], ())
            vizinhos_vizinho_esq = vizinhos_dict.get(v[1], ())
            protecoes.update(vizinhos_vizinho_dir)
            protecoes.update(vizinhos_vizinho_esq)
    return list(protecoes)

# --- FUNÇÕES DE PROCESSAMENTO ---
def extrair_numeros(json_data):
    try:
        if isinstance(json_data, str):
            return [int(n) for n in re.findall(r'\d+', json_data)]
        elif isinstance(json_data, list):
            return [int(n) for n in json_data if isinstance(n, int)]
        elif isinstance(json_data, dict):
            for chave in ["results", "data", "lastNumbers"]:
                if chave in json_data and isinstance(json_data[chave], list):
                    return [int(n) for n in json_data[chave] if isinstance(n, int)]
            for v in json_data.values():
                if isinstance(v, list) and all(isinstance(n, int) for n in v):
                    return v
            return []
    except:
        return []

def processar_resultados(provedor, nome_mesa, numeros_recentes):
    global monitoramento_sinais, sinais_por_hora, total_sinais_dia, ultimo_gatilho_analisado

    if len(numeros_recentes) < 20:
        return

    mesa_key = f"{provedor}:{nome_mesa}"
    history[mesa_key].extendleft(reversed(numeros_recentes))
    numeros_historico = list(history[mesa_key])

    num_gatilho = numeros_recentes[0]

    if ultimo_gatilho_analisado.get(nome_mesa) == num_gatilho:
        return

    ocorrencias = [i for i, n in enumerate(numeros_historico) if n == num_gatilho]
    if len(ocorrencias) < 6:
        print(f"❌ SINAL NÃO GERADO: Menos de 5 ocorrências do gatilho {num_gatilho} encontradas para análise.")
        return

    ocorrencias_a_analisar = ocorrencias[1:6]
    grupos_similaridade = []
    debug_info = []

    for idx_ocorrencia in ocorrencias_a_analisar:
        # Garante que não haverá index fora dos limites
        start_combo1 = idx_ocorrencia + 1
        end_combo1 = start_combo1 + 10
        combo1 = numeros_historico[start_combo1:end_combo1]

        # Para pegar o "antes", a posição inicial não pode ser menor que 0
        start_combo2 = max(0, idx_ocorrencia - 10)
        end_combo2 = idx_ocorrencia
        combo2 = numeros_historico[start_combo2:end_combo2]

        # Encontra os similares entre os dois combos
        similares = set(combo1) & set(combo2)
        grupos_similaridade.append(similares)
        debug_info.append({
            "gatilho": num_gatilho,
            "posicao_hist": idx_ocorrencia,
            "combo1": combo1,
            "combo2": combo2,
            "similares": list(sorted(similares))
        })

    alvos = set()
    protecoes = set()
    for grupo in grupos_similaridade:
        alvos.update(grupo)

    if not alvos:
        print(f"❌ SINAL NÃO GERADO: Nenhuma similaridade encontrada entre os combos nas 5 últimas ocorrências.")
        ultimo_gatilho_analisado[nome_mesa] = num_gatilho
        return

    if 0 not in alvos:
        alvos.add(0)

    for alvo in alvos:
        protecoes.update(ESPELHOS.get(alvo, []))
    protecoes = protecoes - alvos

    alvos_completos = alvos.union(protecoes)
    total_fichas = len(alvos_completos)

    if not (10 <= total_fichas <= 14):
        print(f"❌ SINAL NÃO GERADO: Total de fichas ({total_fichas}) fora do intervalo de 10-14.")
        ultimo_gatilho_analisado[nome_mesa] = num_gatilho
        return

    max_tentativas = get_max_tentativas(total_fichas)
    link_api = MESAS_API.get(nome_mesa)

    # Prepara o objeto do sinal
    dados_sinal = {
        'mesa': nome_mesa,
        'alvos': list(alvos_completos),
        'ultimos': numeros_recentes[:1],
        'gatilho': num_gatilho,
        'tentativas': 0,
        'ultimo_numero_checado': numeros_recentes[0],
        'link_api': link_api,
        'tipo': "Similaridade",
        'max_tentativas': max_tentativas,
        'fichas': total_fichas,
        'enviado_telegram': False
    }

    # --- DEPURANDO SINAL ---
    print()
    print(f"{Fore.CYAN}[DEBUG SINAL]{Style.RESET_ALL} Mesa: {nome_mesa}")
    print(f"Gatilho: {num_gatilho}")
    print(f"Alvos Principais: {sorted(list(alvos))}")
    if protecoes:
        print(f"Proteções (Espelhos): {sorted(list(protecoes))}")
    print(f"Fichas: {total_fichas}")
    print(f"Tentativas: {max_tentativas}")
    print("Detalhes da análise:")
    for d in debug_info:
        print(f"    - Gatilho: {d['gatilho']} na posição {d['posicao_hist']}")
        print(f"    - Combo antes: {d['combo2']}")
        print(f"    - Combo depois: {d['combo1']}")
        print(f"    - Similares: {d['similares']}")
    print(f"Últimos números analisados: {numeros_recentes[:10]}")

    # --- LÓGICA DE ENVIO IMEDIATO VS. MONITORAMENTO INTERNO ---
    sinais_acumulados_internamente.setdefault(nome_mesa, {}).setdefault(total_fichas, {'resultados': deque(maxlen=MIN_AMOSTRAS_CONTINUO)})

    # A verificação inicial é feita com os dados do deque
    num_amostras = len(sinais_acumulados_internamente[nome_mesa][total_fichas]['resultados'])
    greens = sinais_acumulados_internamente[nome_mesa][total_fichas]['resultados'].count('Green')
    assertividade = (greens / num_amostras * 100) if num_amostras > 0 else 0.0

    # Lógica de decisão: enviar para o Telegram ou monitorar internamente
    # A decisão de enviar é feita aqui, no momento que o sinal é gerado.
    if num_amostras >= MIN_AMOSTRAS_INICIAL and assertividade >= ASSERTIVIDADE_MINIMA:
        print(f"✅ ASSERTIVIDADE OK: {assertividade:.2f}% >= {ASSERTIVIDADE_MINIMA}%. ENVIANDO SINAL!")
        dados_sinal['enviado_telegram'] = True
        enviar_sinal_telegram_imediato(dados_sinal)
    else:
        print(f"❌ ASSERTIVIDADE ABAIXO DO MINIMO OU AMOSTRAS INSUFICIENTES: {assertividade:.2f}% ({num_amostras} amostras). Monitorando internamente.")
        dados_sinal['enviado_telegram'] = False

    # Adiciona o sinal gerado à lista de monitoramento, independentemente se foi enviado ou não
    monitoramento_sinais[nome_mesa] = dados_sinal

    ultimo_gatilho_analisado[nome_mesa] = num_gatilho
    hora_brasilia = datetime.now(FUSO_BRASILIA).hour
    sinais_por_hora[hora_brasilia]+=1
    total_sinais_dia+=1

# --- MONITORAMENTO DE SINAIS ---
def monitorar_sinais_ativos():
    global monitoramento_sinais, sinais_acumulados_internamente, ultimo_resultado_ranking
    sinais_para_remover = []
    novo_resultado_ranking = False

    for nome_mesa, dados_sinal in list(monitoramento_sinais.items()):
        api_url = MESAS_API.get(nome_mesa)
        if not api_url:
            sinais_para_remover.append(nome_mesa)
            continue
        try:
            resp = requests.get(api_url, timeout=20)
            if resp.status_code == 200:
                numeros = extrair_numeros(resp.json())
                if not numeros or numeros[0] == dados_sinal['ultimo_numero_checado']:
                    continue

                novos = []
                for n in numeros:
                    if n == dados_sinal['ultimo_numero_checado']:
                        break
                    novos.append(n)

                max_tentativas = dados_sinal['max_tentativas']
                fichas_do_sinal = dados_sinal['fichas']

                # Certifica-se que a estrutura para o deque existe
                sinais_acumulados_internamente.setdefault(nome_mesa, {}).setdefault(fichas_do_sinal, {'resultados': deque(maxlen=MIN_AMOSTRAS_CONTINUO)})

                final_status = None
                tentativa_vitoria = None

                # O loop abaixo processa os novos resultados e encontra o status final
                for novo_num in reversed(novos):
                    dados_sinal['tentativas'] += 1

                    if novo_num in dados_sinal['alvos']:
                        final_status = 'Green'
                        tentativa_vitoria = dados_sinal['tentativas']
                        break

                    if dados_sinal['tentativas'] >= max_tentativas:
                        final_status = 'Red'
                        break

                # Se um resultado final for determinado, processa e remove o sinal
                if final_status:
                    # Adiciona o resultado ao deque de resultados para cálculo de assertividade
                    sinais_acumulados_internamente[nome_mesa][fichas_do_sinal]['resultados'].append(final_status)

                    print(f"[MONITOR] {nome_mesa} - Número: {numeros[0]} - Resultado: {final_status} (Tentativas: {dados_sinal['tentativas']}/{max_tentativas})")

                    # Se o sinal foi enviado, envia o relatório final.
                    # Se não foi enviado, mas a assertividade agora é boa, envia o sinal (e o relatório) agora.
                    if dados_sinal['enviado_telegram']:
                        # Envia o relatório de resultado para o sinal que já tinha sido enviado
                        enviar_relatorio(dados_sinal, final_status, tentativa_vitoria, max_tentativas)
                    else:
                        # Checa a assertividade da amostra atualizada.
                        resultados_recentes = sinais_acumulados_internamente[nome_mesa][fichas_do_sinal]['resultados']
                        total_amostras = len(resultados_recentes)
                        greens_ranking = resultados_recentes.count('Green')
                        assertividade_ranking = (greens_ranking / total_amostras * 100) if total_amostras > 0 else 0.0

                        if total_amostras >= MIN_AMOSTRAS_INICIAL and assertividade_ranking >= ASSERTIVIDADE_MINIMA:
                            # A assertividade agora é suficiente, envia o sinal para o Telegram
                            print(f"✅ ASSERTIVIDADE OK: {assertividade_ranking:.2f}% >= {ASSERTIVIDADE_MINIMA}%. ENVIANDO SINAL AGORA (ATRASADO)!")
                            dados_sinal['enviado_telegram'] = True
                            enviar_sinal_telegram_imediato(dados_sinal)
                            # E também envia o relatório do resultado que acabou de ser encontrado
                            enviar_relatorio(dados_sinal, final_status, tentativa_vitoria, max_tentativas)
                        else:
                            # O sinal não foi enviado, e o resultado não melhorou a assertividade.
                            print(f"❌ O sinal não foi enviado, assertividade ainda baixa: {assertividade_ranking:.2f}%.")

                    # Remove o sinal da lista de monitoramento
                    sinais_para_remover.append(nome_mesa)

                # Atualiza o último número checado para continuar o monitoramento
                dados_sinal['ultimo_numero_checado'] = numeros[0]

            else:
                print(f"{Fore.RED}[ERRO] Falha ao monitorar mesa {nome_mesa}: Status {resp.status_code}{Style.RESET_ALL}")
                sinais_para_remover.append(nome_mesa)
                continue
        except Exception as e:
            print(f"{Fore.RED}[ERRO] Falha ao monitorar mesa {nome_mesa}: {e}{Style.RESET_ALL}")
            sinais_para_remover.append(nome_mesa)
            continue

    for nome_mesa in sinais_para_remover:
        if nome_mesa in monitoramento_sinais:
            del monitoramento_sinais[nome_mesa]
            novo_resultado_ranking = True

    if novo_resultado_ranking:
        novo_ranking_ordenado = []
        for mesa, dados_fichas in sinais_acumulados_internamente.items():
            for fichas, dados in dados_fichas.items():
                resultados = dados['resultados']
                total_amostras = len(resultados)
                if total_amostras >= 10:
                    greens = resultados.count('Green')
                    reds = resultados.count('Red')
                    assertividade = (greens / total_amostras * 100) if total_amostras > 0 else 0
                    novo_ranking_ordenado.append((assertividade, mesa, fichas, greens, reds, total_amostras))

        novo_ranking_ordenado.sort(key=lambda x: x[0], reverse=True)
        exibir_ranking_debug()
        enviar_ranking_telegram(novo_ranking_ordenado) # NOVO: Envia o ranking completo para o Telegram
        ultimo_resultado_ranking = novo_ranking_ordenado

# --- FUNÇÃO PARA ENVIAR RELATÓRIO HORÁRIO ---
def enviar_relatorio_horario():
    global sinais_por_hora, total_sinais_dia
    agora = datetime.now(FUSO_BRASILIA)
    mensagem = f"📈 *RELATÓRIO HORÁRIO*\n\n"
    for hora in sorted(sinais_por_hora.keys()):
        if sinais_por_hora[hora] > 0:
            mensagem += f"Sinais entre {hora:02d}:00 e {(hora + 1) % 24:02d}:00: {sinais_por_hora[hora]}\n"
    mensagem += f"\n--- *TOTAL DO DIA* ---\n"
    mensagem += f"Sinais totais do dia: {total_sinais_dia}\n"
    enviar_telegram(mensagem, parse_mode='Markdown')

# --- LOOP PRINCIPAL ---
print(f"{Fore.BLUE}[🤖 BOT INICIADO]{Style.RESET_ALL} Monitorando mesas...")
enviar_telegram("🤖 Bot de Gatilhos iniciado com sucesso!")

while True:
    headers = {"User-Agent": "Mozilla/5.0"}
    bloqueados_upper = [p.upper() for p in PROVEDORES_BLOQUEADOS]

    if contador_erros_consecutivos > 0:
        tempo_espera = min(300, 2 ** contador_erros_consecutivos)
        print(f"🚨 {Fore.RED}Múltiplos erros de conexão detectados. Esperando {tempo_espera}s antes da próxima tentativa...{Style.RESET_ALL}")
        time.sleep(tempo_espera)

    try:
        erros_nesta_rodada = False
        for nome_mesa, api_url in MESAS_API.items():
            provedor = MESAS_PROVEDORES.get(nome_mesa, "Desconhecido")
            if provedor.upper() in bloqueados_upper:
                continue
            try:
                resp = requests.get(api_url, headers=headers, timeout=20)
                if resp.status_code == 200:
                    numeros = extrair_numeros(resp.json())
                    print(f"{Fore.YELLOW}[UPDATE]{Style.RESET_ALL} Mesa: {nome_mesa} - Últimos 10 numeros: {numeros[:10]}")
                    processar_resultados(provedor, nome_mesa, numeros)
                else:
                    print(f"{Fore.RED}[ERRO]{Style.RESET_ALL} API da mesa {nome_mesa} retornou status {resp.status_code}.")
                    erros_nesta_rodada = True
            except requests.exceptions.Timeout:
                print(f"{Fore.RED}[ERRO]{Style.RESET_ALL} Tempo de espera da API da mesa {nome_mesa} excedido.")
                erros_nesta_rodada = True
            except requests.exceptions.RequestException as e:
                print(f"{Fore.RED}[ERRO]{Style.RESET_ALL} Não foi possível conectar a API da mesa {nome_mesa}: {e}")
                erros_nesta_rodada = True

        if erros_nesta_rodada:
            contador_erros_consecutivos += 1
        else:
            contador_erros_consecutivos = 0

    except Exception as e:
        print(f"❌ {Fore.RED}ERRO GERAL NO LOOP PRINCIPAL: {e}{Style.RESET_ALL}")
        contador_erros_consecutivos += 1

    monitorar_sinais_ativos()

    # Relatórios horários
    agora = datetime.now(FUSO_BRASILIA)
    if agora.minute == 0 and agora.hour != ultima_hora:
        enviar_relatorio_horario()
        if agora.hour == 0:
            sinais_por_hora = {h: 0 for h in range(24)}
            total_sinais_dia = 0
        ultima_hora = agora.hour

    if contador_erros_consecutivos == 0:
        time.sleep(INTERVALO)
