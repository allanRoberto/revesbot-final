import requests
import asyncio
import os
import re
from collections import Counter, defaultdict
from itertools import permutations
from core.api import RouletteAPI
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do arquivo .env
load_dotenv()

# --- DEFINIÇÕES GLOBAIS DA ROLETA ---
ROULETTE_WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]

NUMEROS_ROLETA = {
    0: {'cor': 'verde', 'duzia': None, 'coluna': None, 'par_impar': None, 'alto_baixo': None},
    1: {'cor': 'vermelho', 'duzia': 1, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'baixo'},
    2: {'cor': 'preto', 'duzia': 1, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'baixo'},
    3: {'cor': 'vermelho', 'duzia': 1, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'baixo'},
    4: {'cor': 'preto', 'duzia': 1, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'baixo'},
    5: {'cor': 'vermelho', 'duzia': 1, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'baixo'},
    6: {'cor': 'preto', 'duzia': 1, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'baixo'},
    7: {'cor': 'vermelho', 'duzia': 1, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'baixo'},
    8: {'cor': 'preto', 'duzia': 1, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'baixo'},
    9: {'cor': 'vermelho', 'duzia': 1, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'baixo'},
    10: {'cor': 'preto', 'duzia': 1, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'baixo'},
    11: {'cor': 'preto', 'duzia': 2, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'baixo'},
    12: {'cor': 'vermelho', 'duzia': 1, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'baixo'},
    13: {'cor': 'preto', 'duzia': 2, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'baixo'},
    14: {'cor': 'vermelho', 'duzia': 2, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'baixo'},
    15: {'cor': 'preto', 'duzia': 2, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'baixo'},
    16: {'cor': 'vermelho', 'duzia': 2, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'baixo'},
    17: {'cor': 'preto', 'duzia': 2, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'baixo'},
    18: {'cor': 'vermelho', 'duzia': 2, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'baixo'},
    19: {'cor': 'vermelho', 'duzia': 2, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'alto'},
    20: {'cor': 'preto', 'duzia': 2, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'alto'},
    21: {'cor': 'vermelho', 'duzia': 2, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'alto'},
    22: {'cor': 'preto', 'duzia': 3, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'alto'},
    23: {'cor': 'vermelho', 'duzia': 3, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'alto'},
    24: {'cor': 'preto', 'duzia': 3, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'alto'},
    25: {'cor': 'vermelho', 'duzia': 3, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'alto'},
    26: {'cor': 'preto', 'duzia': 3, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'alto'},
    27: {'cor': 'vermelho', 'duzia': 3, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'alto'},
    28: {'cor': 'preto', 'duzia': 3, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'alto'},
    29: {'cor': 'preto', 'duzia': 3, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'alto'},
    30: {'cor': 'vermelho', 'duzia': 3, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'alto'},
    31: {'cor': 'preto', 'duzia': 3, 'coluna': 1, 'par_impar': 'impar', 'alto_baixo': 'alto'},
    32: {'cor': 'vermelho', 'duzia': 3, 'coluna': 2, 'par_impar': 'par', 'alto_baixo': 'alto'},
    33: {'cor': 'preto', 'duzia': 3, 'coluna': 3, 'par_impar': 'impar', 'alto_baixo': 'alto'},
    34: {'cor': 'vermelho', 'duzia': 3, 'coluna': 1, 'par_impar': 'par', 'alto_baixo': 'alto'},
    35: {'cor': 'preto', 'duzia': 3, 'coluna': 2, 'par_impar': 'impar', 'alto_baixo': 'alto'},
    36: {'cor': 'vermelho', 'duzia': 3, 'coluna': 3, 'par_impar': 'par', 'alto_baixo': 'alto'}
}

# Correção das duzias e alto/baixo nos dados NUMEROS_ROLETA para a Roleta Europeia
for num in range(1, 37):
    if 1 <= num <= 12:
        NUMEROS_ROLETA[num]['duzia'] = 1
        NUMEROS_ROLETA[num]['alto_baixo'] = 'baixo'
    elif 13 <= num <= 24:
        NUMEROS_ROLETA[num]['duzia'] = 2
        NUMEROS_ROLETA[num]['alto_baixo'] = 'baixo' if num <= 18 else 'alto'
    elif 25 <= num <= 36:
        NUMEROS_ROLETA[num]['duzia'] = 3
        NUMEROS_ROLETA[num]['alto_baixo'] = 'alto'

ESPELHOS = {
    6: 9, 9: 6, 12: 21, 19: 16, 16: 19, 21: 12, 23: 32, 29: 26, 26: 29,
    31: 13, 13: 31, 10: 1, 1: 10, 11: 10, 2: 20, 20: 2, 22: 2, 3: 30, 30: 3
}

# --- ATENÇÃO AQUI: Credenciais mantidas no código, conforme sua preferência ---
# Certifique-se de que os valores a seguir NÃO estejam vazios. 
TELEGRAM_TOKEN =( "8163117177:AAEkKSKUiprvUhcsHYZsjS-USWfElF5jNIs")
CHAT_ID = ("-1002470133269")
BUTTON_TEXT = os.getenv("BUTTON_TEXT", "ACESSE A MESA")
BUTTON_URL = os.getenv("BUTTON_URL", "https://go.aff.lotogreen.com/gtog6xlw")

def escape_markdown_v2(text):
    chars_to_escape = r'_*[]()~`>#+=-|{}.!'
    escaped_text = re.sub(f"([{re.escape(chars_to_escape)}])", r"\\\1", text)
    return escaped_text

def enviar_telegram(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("[ERRO TELEGRAM] TELEGRAM_TOKEN ou CHAT_ID estão vazios. Verifique as definições no código.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    escaped_message = escape_markdown_v2(message)
    
    payload = {
        "chat_id": CHAT_ID,
        "text": escaped_message,
        "parse_mode": "MarkdownV2",
        "reply_markup": {
            "inline_keyboard": [[
                {"text": BUTTON_TEXT, "url": BUTTON_URL},
            ]]
        }
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status() 
        print(f"[TELEGRAM] Mensagem enviada com sucesso. Resposta: {response.json()}")
    except requests.exceptions.RequestException as e:
        print(f"[ERRO TELEGRAM] Falha ao enviar mensagem: {e}. URL: {url}")
    except Exception as e:
        print(f"[ERRO TELEGRAM] Erro inesperado ao enviar mensagem: {e}")

estatisticas = {"green": 0, "red": 0}
ultimo_resultado = None
historico_completo = []
aposta_ativa = {
    "status": False,
    "entrada_final": [],
    "tipo_padrao": "",
    "confianca": 0.0,
    "tentativas_restantes": 0,
    "rodadas_monitoradas_na_aposta": 0
}

def get_prop(numero, prop_nome):
    return NUMEROS_ROLETA.get(numero, {}).get(prop_nome)

def get_neighbors_from_wheel(number, num_casas=1):
    if number not in ROULETTE_WHEEL_ORDER:
        return []
    
    idx = ROULETTE_WHEEL_ORDER.index(number)
    neighbors = set()
    
    for i in range(1, num_casas + 1):
        neighbors.add(ROULETTE_WHEEL_ORDER[(idx + i) % len(ROULETTE_WHEEL_ORDER)])
        neighbors.add(ROULETTE_WHEEL_ORDER[(idx - i + len(ROULETTE_WHEEL_ORDER)) % len(ROULETTE_WHEEL_ORDER)])
        
    return sorted(list(neighbors))

def get_espelho(numero):
    return ESPELHOS.get(numero)

def get_digits(number):
    if number == 0:
        return [0]
    return [int(d) for d in str(int(number))]

def sum_digits(number):
    return sum(get_digits(number))

# MODIFICADO: min_len reduzido para aumentar a frequência de detecção
def detectar_repeticao(historico, prop_nome, min_len=3):
    if len(historico) < min_len:
        return None, 0, False

    primeira_prop = get_prop(historico[0], prop_nome)
    if prop_nome in ['duzia', 'coluna', 'alto_baixo', 'par_impar', 'cor'] and primeira_prop is None:
        return None, 0, False

    count = 0
    for num in historico:
        prop = get_prop(num, prop_nome)
        if prop == primeira_prop:
            count += 1
        else:
            break
    
    if count >= min_len:
        return primeira_prop, count, True 
    return None, 0, False

# MODIFICADO: min_ocorrencias reduzido para aumentar a frequência
def detectar_vizinhos_recorrentes(historico, janela_observacao=15, min_ocorrencias=1): 
    if len(historico) < 2 or len(historico) < janela_observacao:
        return None, None, None

    sub_historico = historico[1:janela_observacao + 1] 
    ultimo_sorteado = historico[0] 

    vizinhos_map = {n: set(get_neighbors_from_wheel(n, 1)) for n in ROULETTE_WHEEL_ORDER}

    conexao_vizinhos_frequencia = defaultdict(int)

    for i in range(len(sub_historico) - 1):
        n1 = sub_historico[i]
        n2 = sub_historico[i+1]

        if n2 in vizinhos_map.get(n1, set()): 
            conexao = (n1, n2) 
            conexao_vizinhos_frequencia[conexao] += 1
    
    melhor_conexao = None
    maior_frequencia = 0

    for conexao, freq in conexao_vizinhos_frequencia.items():
        if freq >= min_ocorrencias and freq > maior_frequencia:
            melhor_conexao = conexao
            maior_frequencia = freq
            
    if not melhor_conexao:
        return None, None, None

    gatilho_num = melhor_conexao[0]
    alvo_num = melhor_conexao[1]

    if ultimo_sorteado == gatilho_num:
        regiao_alvo = {alvo_num} | set(get_neighbors_from_wheel(alvo_num, 1))
        return regiao_alvo, gatilho_num, maior_frequencia
        
    return None, None, None

# MODIFICADO: min_ocorrencias reduzido para aumentar a frequência
def detectar_comportamento_antecedente(historico, janela_observacao=25, min_ocorrencias=1): 
    if len(historico) < 2 or len(historico) < janela_observacao:
        return None, None, None

    ultimo_sorteado = historico[0]
    
    sequencias_frequencia = defaultdict(int)
    
    for i in range(min(len(historico) - 1, janela_observacao - 1)):
        n_recente = historico[i]
        n_anterior = historico[i+1]
        
        sequencia = (n_anterior, n_recente) 
        sequencias_frequencia[sequencia] += 1
    
    melhor_sequencia = None
    maior_frequencia = 0

    for seq, freq in sequencias_frequencia.items():
        if freq >= min_ocorrencias and freq > maior_frequencia:
            melhor_sequencia = seq
            maior_frequencia = freq
    
    if not melhor_sequencia:
        return None, None, None

    gatilho_num = melhor_sequencia[0]
    alvo_num = melhor_sequencia[1]

    if ultimo_sorteado == gatilho_num:
        return gatilho_num, alvo_num, maior_frequencia
    
    return None, None, None

# NOVO PADRÃO: Detecção de repetições simples de Dúzia/Coluna/Alto_Baixo
def detectar_simples_duzia_coluna(historico, prop_name, min_consecutive=2):
    if len(historico) < min_consecutive:
        return None, None, 0 

    current_prop = get_prop(historico[0], prop_name)
    if current_prop is None: 
        return None, None, 0

    consecutive_count = 0
    for i in range(len(historico)):
        prop = get_prop(historico[i], prop_name)
        if prop == current_prop:
            consecutive_count += 1
        else:
            break
            
    if consecutive_count >= min_consecutive:
        target_prop = None
        if prop_name == 'duzia':
            if current_prop == 1: target_prop = 2
            elif current_prop == 2: target_prop = 3
            elif current_prop == 3: target_prop = 1
        elif prop_name == 'coluna':
            if current_prop == 1: target_prop = 2
            elif current_prop == 2: target_prop = 3
            elif current_prop == 3: target_prop = 1
        elif prop_name == 'alto_baixo': 
            if current_prop == 'baixo': target_prop = 'alto'
            elif current_prop == 'alto': target_prop = 'baixo'
        
        if target_prop is not None:
            return current_prop, target_prop, consecutive_count
            
    return None, None, 0

# CORRIGIDO: Bug da janela de lookback
def detectar_espelho_recente(historico, lookback=5):
    if len(historico) < 2:
        return None, None 
    
    ultimo_numero = historico[0]

    mirror_of_last = get_espelho(ultimo_numero)
    if mirror_of_last is not None:
        for i in range(1, min(len(historico), lookback + 1)): 
            if historico[i] == mirror_of_last:
                return ultimo_numero, mirror_of_last
    
    for i in range(1, min(len(historico), lookback + 1)):
        prev_number = historico[i]
        mirror_of_prev = get_espelho(prev_number)
        if mirror_of_prev is not None and mirror_of_prev == ultimo_numero:
            return prev_number, ultimo_numero 

    return None, None

def detectar_sincro_avancado(historico_4_numeros):
    if len(historico_4_numeros) < 4:
        return None, None, "Histórico insuficiente para SINCRO (min 4 números)"

    n4_recente, n3, n2, n1 = historico_4_numeros[0], historico_4_numeros[1], historico_4_numeros[2], historico_4_numeros[3]

    all_possible_sincro_results = set()

    res_sincro_1 = abs(n4_recente - n2) + n1
    if 0 <= res_sincro_1 <= 36: all_possible_sincro_results.add(res_sincro_1)

    res_sincro_2 = sum_digits(n4_recente) + n2
    if 0 <= res_sincro_2 <= 36: all_possible_sincro_results.add(res_sincro_2)
    
    res_sincro_3 = n3 + n4_recente - n1
    if 0 <= res_sincro_3 <= 36: all_possible_sincro_results.add(res_sincro_3)

    if len(all_possible_sincro_results) < 3: 
        return None, None, "Não há resultados suficientes para formar um SINCRO (menos de 3 combinações válidas)."

    possible_targets = list(all_possible_sincro_results)
    
    for i in range(len(possible_targets)):
        target_num = possible_targets[i]
        target_neighbors_direct = get_neighbors_from_wheel(target_num, 1) 
        
        found_neighbors_in_sincro_results = []
        
        for j in range(len(possible_targets)):
            if i == j: continue
            
            other_num = possible_targets[j]
            
            if other_num in target_neighbors_direct:
                found_neighbors_in_sincro_results.append(other_num)
        
        if len(found_neighbors_in_sincro_results) >= 2:
            return target_num, found_neighbors_in_sincro_results[:2], "SINCRO_COMPLEXO"
    
    return None, None, "Nenhum padrão SINCRO de vizinhança detectado."


def analisar_e_sugerir_apostas(historico_completo):
    sugestoes = [] 
    
    historico_analise_longa = historico_completo[:20] 
    historico_sincro_window = historico_completo[:4]

    if len(historico_analise_longa) < 4:
        print("[ANÁLISE] Histórico muito curto para análise profunda.")
        return []

    # --- Detecção de Padrões (com critérios ajustados ou novos padrões) ---
    
    # Cor: Min_len 3
    cor_repetida, cor_len, cor_strong = detectar_repeticao(historico_analise_longa, 'cor', min_len=3)
    if cor_repetida and cor_len >= 3:
        sug_cor = 'vermelho' if cor_repetida == 'preto' else 'preto' if cor_repetida == 'vermelho' else None
        if sug_cor:
            sugestoes.append({
                'tipo_padrao': f'Quebra de {cor_len}x {cor_repetida.capitalize()}',
                'propriedade_alvo': {'cor': sug_cor},
                'numeros_base': set(),
                'confianca': 0.6 + (cor_len - 2) * 0.05 
            })
    
    # Par/Impar: Min_len 3
    pi_repetido, pi_len, pi_strong = detectar_repeticao(historico_analise_longa, 'par_impar', min_len=3)
    if pi_repetido and pi_len >= 3:
        sug_pi = 'impar' if pi_repetido == 'par' else 'par'
        if sug_pi:
            sugestoes.append({
                'tipo_padrao': f'Quebra de {pi_len}x {pi_repetido.capitalize()}',
                'propriedade_alvo': {'par_impar': sug_pi},
                'numeros_base': set(),
                'confianca': 0.6 + (pi_len - 2) * 0.05
            })

    # NOVO: Dúzias Simples (min_consecutive 2)
    duzia_prev, duzia_sug, duzia_count = detectar_simples_duzia_coluna(historico_analise_longa, 'duzia', min_consecutive=2)
    if duzia_prev is not None:
        sugestoes.append({
            'tipo_padrao': f'Quebra Dúzia {duzia_prev} ({duzia_count}x) -> Dúzia {duzia_sug}',
            'propriedade_alvo': {'duzia': duzia_sug},
            'numeros_base': set(),
            'confianca': 0.55 + (duzia_count - 1) * 0.03 
        })

    # NOVO: Colunas Simples (min_consecutive 2)
    coluna_prev, coluna_sug, coluna_count = detectar_simples_duzia_coluna(historico_analise_longa, 'coluna', min_consecutive=2)
    if coluna_prev is not None:
        sugestoes.append({
            'tipo_padrao': f'Quebra Coluna {coluna_prev} ({coluna_count}x) -> Coluna {coluna_sug}',
            'propriedade_alvo': {'coluna': coluna_sug},
            'numeros_base': set(),
            'confianca': 0.55 + (coluna_count - 1) * 0.03
        })
    
    # NOVO: Alto/Baixo Simples (min_consecutive 2)
    ab_prev, ab_sug, ab_count = detectar_simples_duzia_coluna(historico_analise_longa, 'alto_baixo', min_consecutive=2)
    if ab_prev is not None:
        sugestoes.append({
            'tipo_padrao': f'Quebra Alto/Baixo {ab_prev.capitalize()} ({ab_count}x) -> {ab_sug.capitalize()}',
            'propriedade_alvo': {'alto_baixo': ab_sug},
            'numeros_base': set(),
            'confianca': 0.55 + (ab_count - 1) * 0.03
        })

    # Espelho (corrigido e com lógica de sugestão refinada)
    original_esp, espelho_saido = detectar_espelho_recente(historico_analise_longa, lookback=5)
    if original_esp and espelho_saido:
        num_alvo_espelho_sug = None
        if historico_analise_longa[0] == espelho_saido:
            num_alvo_espelho_sug = original_esp
        elif historico_analise_longa[0] == original_esp:
            num_alvo_espelho_sug = espelho_saido

        if num_alvo_espelho_sug is not None:
            sugestoes.append({
                'tipo_padrao': f'Espelho Ativo: {original_esp} <-> {espelho_saido} (Gatilho: {historico_analise_longa[0]})',
                'propriedade_alvo': None,
                'numeros_base': {num_alvo_espelho_sug},
                'confianca': 0.8 
            })
            if len(historico_analise_longa) > 1 and historico_analise_longa[1] == num_alvo_espelho_sug and original_esp != espelho_saido:
                 if get_espelho(historico_analise_longa[1]) is not None:
                     sugestoes.append({
                         'tipo_padrao': f'Espelho de Retorno: {original_esp} <-> {espelho_saido} (Recente: {historico_analise_longa[1]})',
                         'propriedade_alvo': None,
                         'numeros_base': {get_espelho(historico_analise_longa[1])},
                         'confianca': 0.8
                     })


    # Vizinhos Recorrentes (min_ocorrencias 1)
    regiao_vizinhos, gatilho_vizinhos, freq_vizinhos = detectar_vizinhos_recorrentes(
        historico_completo, 
        janela_observacao=len(historico_completo), 
        min_ocorrencias=1
    ) 
    if regiao_vizinhos and gatilho_vizinhos is not None:
        sugestoes.append({
            'tipo_padrao': f'Vizinhos Recorrentes (Gatilho: {gatilho_vizinhos}) - {freq_vizinhos}x',
            'propriedade_alvo': None,
            'numeros_base': regiao_vizinhos, 
            'confianca': 0.7 + (freq_vizinhos - 1) * 0.05 
        })

    # SINCRO (mantido com alta confiança pela sua descrição)
    sincro_target, sincro_neighbors_list, sincro_msg = detectar_sincro_avancado(historico_sincro_window)
    if sincro_target is not None and sincro_msg == "SINCRO_COMPLEXO":
        entrada_sincro_numeros = {sincro_target} | set(get_neighbors_from_wheel(sincro_target, 1)) 
        sugestoes.append({
            'tipo_padrao': f'SINCRO: Alvo {sincro_target} e vizinhos (Base: {", ".join(map(str, historico_sincro_window))})',
            'propriedade_alvo': None,
            'numeros_base': entrada_sincro_numeros,
            'confianca': 0.98
        })

    # Comportamento Antecedente (min_ocorrencias 1)
    gatilho_seq, alvo_seq, freq_seq = detectar_comportamento_antecedente(
        historico_completo, 
        janela_observacao=len(historico_completo), 
        min_ocorrencias=1
    ) 
    if gatilho_seq is not None and alvo_seq is not None:
        entrada_seq_numeros = {alvo_seq} | set(get_neighbors_from_wheel(alvo_seq, 1)) 
        sugestoes.append({
            'tipo_padrao': f'Comportamento Antecedente: {gatilho_seq} -> {alvo_seq} ({freq_seq}x)',
            'propriedade_alvo': None,
            'numeros_base': entrada_seq_numeros,
            'confianca': 0.85 + (freq_seq - 1) * 0.03
        })

    # --- Lógica de Cruzamento de Análises e Votação de Números (mantida aprimorada) ---
    if not sugestoes:
        return [] 

    numero_scores = defaultdict(float) 
    motivos_sugestao = defaultdict(set) 

    for sug in sugestoes:
        numeros_impactados_por_sugestao = set()
        
        if sug['numeros_base']:
            numeros_impactados_por_sugestao.update(sug['numeros_base'])
        elif sug['propriedade_alvo']:
            for num_roleta, props in NUMEROS_ROLETA.items():
                if num_roleta == 0: continue 
                
                match = True
                for prop_name, prop_val in sug['propriedade_alvo'].items():
                    if props.get(prop_name) != prop_val:
                        match = False
                        break
                if match:
                    numeros_impactados_por_sugestao.add(num_roleta)
        
        for num in numeros_impactados_por_sugestao:
            numero_scores[num] += sug['confianca']
            motivos_sugestao[num].add(sug['tipo_padrao'])
    
    if 0 not in numero_scores: 
        numero_scores[0] = 0.5 
    else: 
        numero_scores[0] += 0.5 
    motivos_sugestao[0].add("Zero Padrão")

    sorted_numbers_by_score = sorted(numero_scores.items(), key=lambda item: item[1], reverse=True)

    final_numeros_aposta = set()
    total_confianca_combinada = 0.0
    combined_pattern_types = set()
    
    min_numeros_alvo = 6 
    max_numeros_alvo = 12 

    temp_final_nums = []
    current_score_sum = 0.0
    current_combined_types = set()

    for num, score in sorted_numbers_by_score:
        if num == 0: continue 
        
        if len(temp_final_nums) < max_numeros_alvo:
            temp_final_nums.append(num)
            current_score_sum += score
            current_combined_types.update(motivos_sugestao[num])
        else:
            break 
            
    idx_sorted = 0
    while len(temp_final_nums) < min_numeros_alvo and idx_sorted < len(sorted_numbers_by_score):
        num, score = sorted_numbers_by_score[idx_sorted]
        if num == 0:
            idx_sorted += 1
            continue

        if num not in temp_final_nums:
            temp_final_nums.append(num)
            current_score_sum += score
            current_combined_types.update(motivos_sugestao[num])
        idx_sorted += 1

    final_numeros_aposta = set(temp_final_nums)
    total_confianca_combinada = current_score_sum
    combined_pattern_types = current_combined_types
    
    if 0 not in final_numeros_aposta:
        final_numeros_aposta.add(0)
        total_confianca_combinada += numero_scores[0]
        combined_pattern_types.update(motivos_sugestao[0])


    avg_conf = 0.0
    if final_numeros_aposta:
        avg_conf = total_confianca_combinada / len(final_numeros_aposta)
    else:
        return []

    final_suggestions_list = [] 
    final_suggestions_list.append({
        'numeros': sorted(list(final_numeros_aposta)),
        'tipo_padrao': "Cruzamento de Padrões: " + ", ".join(list(combined_pattern_types)),
        'confianca': min(1.0, avg_conf)
    })
        
    return final_suggestions_list

def process_roulette(roulette, numbers):
            historico_completo = numbers
            sugestoes_atuais = analisar_e_sugerir_apostas(historico_completo)

            if not sugestoes_atuais:
                print("[INFO] Nenhuma sugestão forte detectada. Continuo monitorando...")
                return None
            
            sugestao_selecionada = sugestoes_atuais[0]
            
            return {
            "roulette_id": roulette['slug'],
            "roulette_name" : roulette["name"],
            "roulette_url" : roulette["url"],
            "pattern" : "SEQUENCIA",
            "triggers":numbers[0],
            "targets":sugestao_selecionada['numeros'],
            "bets":sugestao_selecionada['numeros'],
            "passed_spins" : 0,
            "spins_required" : 16,
            "spins_count": 16,
            "snapshot":numbers[:150],
            "status":"processing",
            "message" : "Gatilho identificado 16 jogadas"
            }


            