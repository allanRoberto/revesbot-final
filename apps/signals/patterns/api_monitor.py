"""
Padrao de monitoramento da API de sugestoes.
Recebe um numero, chama a API para obter sugestao simples e monta o sinal.

Inclui logica de deteccao de padroes comportamentais que podem:
- Atrasar a entrada (adiciona spins_required)
- Cancelar a jogada (retorna None)
"""
import os
import httpx
from datetime import datetime
from typing import Optional, List, Tuple, Set
from dotenv import load_dotenv

load_dotenv()

URL_API = os.environ.get("BASE_URL_API", "http://localhost:8000")

# Ordem da roleta europeia
ROULETTE_WHEEL = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
    24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]


# ══════════════════════════════════════════════════════════════════════════════
# FUNCOES AUXILIARES
# ══════════════════════════════════════════════════════════════════════════════

def get_neighbors(num: int, qty: int = 1) -> List[int]:
    """Retorna os vizinhos de um numero na roleta europeia."""
    if num > 36:
        return []
    try:
        i = ROULETTE_WHEEL.index(num)
        left = ROULETTE_WHEEL[(i - qty) % len(ROULETTE_WHEEL)]
        right = ROULETTE_WHEEL[(i + qty) % len(ROULETTE_WHEEL)]
        return [left, right]
    except ValueError:
        return []


def get_terminal(num: int) -> int:
    """Retorna o terminal (ultimo digito) de um numero."""
    return num % 10


def is_same_terminal(a: int, b: int) -> bool:
    """Verifica se dois numeros tem o mesmo terminal."""
    return get_terminal(a) == get_terminal(b)


def is_neighbor(a: int, b: int) -> bool:
    """Verifica se dois numeros sao vizinhos na roleta."""
    neighbors = get_neighbors(a)
    return b in neighbors


def is_consecutive(a: int, b: int) -> bool:
    """Verifica se dois numeros sao consecutivos (crescente/decrescente)."""
    return abs(a - b) == 1


def is_consecutive_two_steps(a: int, b: int) -> bool:
    """Verifica se dois numeros sao consecutivos de 2 casas (par/impar)."""
    return abs(a - b) == 2


def is_repetition(a: int, b: int) -> bool:
    """
    Verifica se b e uma repeticao de a.
    Considera: mesmo numero, mesmo terminal, ou vizinho.
    """
    if a == b:
        return True
    if is_same_terminal(a, b):
        return True
    if is_neighbor(a, b):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# DETECCAO DE PADROES QUE ATRASAM A ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

def detect_repetition_before_trigger(numbers: List[int]) -> int:
    """
    Detecta repeticao antes do gatilho (posicao 0).
    Exemplos:
    - 17 > 17 > 28 (repeticao exata)
    - 7 > 17 > 28 (repeticao de terminal)
    - 34 > 17 > 28 (repeticao de vizinho)

    Retorna: numero de rodadas de espera (2 se detectado, 0 se nao)
    """
    if len(numbers) < 3:
        return 0

    # numbers[0] = gatilho, numbers[1] e numbers[2] = anteriores
    num1 = numbers[1]  # numero imediatamente antes do gatilho
    num2 = numbers[2]  # numero antes de num1

    if is_repetition(num1, num2):
        return 2

    return 0


def detect_alternation_before_trigger(numbers: List[int]) -> int:
    """
    Detecta alternancia antes do gatilho.
    Exemplos:
    - 17 > 5 > 17 > 28 (alternancia exata)
    - 7 > 5 > 17 > 28 (alternancia de terminal)
    - 34 > 5 > 17 > 28 (alternancia de vizinho)

    Retorna: numero de rodadas de espera (2 se detectado, 0 se nao)
    """
    if len(numbers) < 4:
        return 0

    # numbers[0] = gatilho
    num1 = numbers[1]  # imediatamente antes
    num2 = numbers[2]  # 2 posicoes antes
    num3 = numbers[3]  # 3 posicoes antes

    # Alternancia: num1 repete num3 (com num2 no meio)
    if is_repetition(num1, num3):
        return 2

    return 0


def detect_consecutive_before_trigger(numbers: List[int]) -> int:
    """
    Detecta crescente/decrescente antes do gatilho.
    Exemplos:
    - 16 > 17 > 28 (crescente)
    - 17 > 16 > 28 (decrescente)

    Retorna: numero de rodadas de espera (2 se detectado, 0 se nao)
    """
    if len(numbers) < 3:
        return 0

    num1 = numbers[1]
    num2 = numbers[2]

    if is_consecutive(num1, num2):
        return 2

    return 0


def detect_number_return_before_trigger(numbers: List[int], search_window: int = 10) -> int:
    """
    Detecta retorno de numero antes do gatilho.
    Exemplo: 32 > 2 > 4 > 4 > 6 > 32 > 28
    O 32 retornou, conta-se os numeros entre as duas ocorrencias.

    Retorna: numero de rodadas de espera (quantidade de numeros entre as duas ocorrencias)
    """
    if len(numbers) < 3:
        return 0

    # Numero imediatamente antes do gatilho
    num_before = numbers[1]

    # Procura outra ocorrencia desse numero mais atras
    for i in range(2, min(len(numbers), search_window)):
        if numbers[i] == num_before:
            # Encontrou retorno! A distancia e a quantidade de numeros entre eles
            return i - 1  # Quantidade de numeros entre as duas ocorrencias

    return 0


def detect_zero_before_trigger(numbers: List[int]) -> int:
    """
    Detecta zero antes do gatilho.
    O zero pode atrasar os alvos em ate 7 rodadas.

    Retorna: 7 se zero detectado, 0 se nao
    """
    if len(numbers) < 2:
        return 0

    if numbers[1] == 0:
        return 7

    return 0


# ══════════════════════════════════════════════════════════════════════════════
# DETECCAO DE PADROES QUE CANCELAM A JOGADA
# ══════════════════════════════════════════════════════════════════════════════

def detect_inverse_payment(numbers: List[int], bets: List[int]) -> bool:
    """
    Detecta se a jogada foi paga de forma inversa (alvo veio antes do gatilho).
    Exemplos:
    - 32 > 28 (se 32 e alvo)
    - 19 > 33 > 28 (se 19 ou 33 sao alvos)

    Verifica ate 2 rodadas antes do gatilho.

    Retorna: True se deve cancelar, False se nao
    """
    if len(numbers) < 2 or not bets:
        return False

    bets_set = set(bets)

    # Verifica ate 2 numeros antes do gatilho
    window = numbers[1:3] if len(numbers) >= 3 else numbers[1:2]

    for num in window:
        if num in bets_set:
            return True

    return False


def detect_trigger_from_consecutive(numbers: List[int]) -> bool:
    """
    Detecta se o gatilho veio de uma crescente ou decrescente.
    Exemplos:
    - 29 > 28 (crescente para gatilho 28)
    - 27 > 28 (decrescente para gatilho 28)

    Retorna: True se deve cancelar, False se nao
    """
    if len(numbers) < 2:
        return False

    trigger = numbers[0]
    before = numbers[1]

    return is_consecutive(trigger, before)


def detect_trigger_trapped_in_pattern(numbers: List[int]) -> bool:
    """
    Detecta se o gatilho esta preso dentro de um padrao.
    Exemplos:
    - 15 > 28 > 15 (numero volta apos gatilho)
    - 34 > 28 > 6 (vizinhos envolvendo gatilho)
    - 28 > 29 (gatilho seguido de consecutivo) - obs: isso seria no futuro, entao ignora
    - 18 > 28 (vizinho antes do gatilho)
    - 8 > 5 > 28 (padrao especifico)

    Retorna: True se deve cancelar, False se nao
    """
    if len(numbers) < 2:
        return False

    trigger = numbers[0]
    before = numbers[1]

    # Vizinho imediato antes do gatilho (18 > 28)
    if is_neighbor(trigger, before):
        return True

    # Padrao 8 > 5 > 28 (dois numeros especificos antes)
    if len(numbers) >= 3:
        before2 = numbers[2]
        # Verifica se ha uma sequencia pulada antes
        if is_consecutive_two_steps(before, before2):
            return True

    return False


def detect_number_return_after_trigger(numbers: List[int], history_window: int = 5) -> bool:
    """
    Detecta retorno de numero apos o gatilho.
    Verifica se algum numero que estava antes do gatilho apareceu logo depois.
    Exemplo: 32 > 4 > 4 > 28 > 32

    Nota: Como estamos no momento do gatilho, verificamos o historico recente
    para identificar numeros que poderiam "retornar" nas proximas rodadas.

    Retorna: True se deve cancelar, False se nao
    """
    # Esta funcao e mais relevante apos o gatilho ser processado
    # Por enquanto, verificamos padroes suspeitos
    if len(numbers) < 4:
        return False

    # Verifica se ha um numero que apareceu duas vezes perto do gatilho
    recent = numbers[1:history_window] if len(numbers) >= history_window else numbers[1:]

    for i, num in enumerate(recent):
        for j in range(i + 1, len(recent)):
            if recent[j] == num:
                # Numero repetido na janela proxima ao gatilho
                # Isso pode indicar que ele vai "retornar"
                return True

    return False


# ══════════════════════════════════════════════════════════════════════════════
# DETECCAO DE COMPATIBILIDADE DE CENARIO
# ══════════════════════════════════════════════════════════════════════════════

def detect_scenario_compatibility(
    numbers: List[int],
    trigger: int,
    search_window: int = 100,
    context_size: int = 3
) -> Tuple[bool, float]:
    """
    Verifica se o cenario atual e compativel com cenarios historicos onde o gatilho apareceu.

    Exemplo:
    - Cenario atual: 25 > 15 > 16 > 28
    - Se no historico o 28 apareceu apos 25 > 15 > 28, cenario compativel

    Retorna: (is_compatible, similarity_score)
    """
    if len(numbers) < context_size + 1:
        return False, 0.0

    # Contexto atual (numeros antes do gatilho)
    current_context = numbers[1:context_size + 1]

    # Procura outras ocorrencias do gatilho no historico
    compatible_count = 0
    total_occurrences = 0

    for i in range(context_size + 1, min(len(numbers), search_window)):
        if numbers[i] == trigger:
            total_occurrences += 1

            # Contexto dessa ocorrencia historica
            if i + context_size < len(numbers):
                historical_context = numbers[i + 1:i + context_size + 1]

                # Verifica similaridade
                matches = 0
                for curr, hist in zip(current_context, historical_context):
                    if curr == hist:
                        matches += 2  # Match exato
                    elif is_same_terminal(curr, hist):
                        matches += 1  # Match de terminal
                    elif is_neighbor(curr, hist):
                        matches += 1  # Match de vizinho

                similarity = matches / (context_size * 2)
                if similarity >= 0.5:
                    compatible_count += 1

    if total_occurrences == 0:
        return False, 0.0

    compatibility_ratio = compatible_count / total_occurrences
    return compatibility_ratio >= 0.3, compatibility_ratio


# ══════════════════════════════════════════════════════════════════════════════
# FUNCAO PRINCIPAL DE ANALISE COMPORTAMENTAL
# ══════════════════════════════════════════════════════════════════════════════

def analyze_behavior(numbers: List[int], bets: List[int]) -> Tuple[int, str]:
    """
    Analisa o comportamento do historico para determinar:
    1. Quantas rodadas de espera (spins_required)
    2. Mensagem explicativa

    Retorna: (spins_required, message)
    """
    if len(numbers) < 2:
        return 0, ""

    trigger = numbers[0]
    spins_required = 0
    reasons = []

    # ══════════════════════════════════════════════════════════════════
    # VERIFICACOES QUE ADICIONAM 1 TENTATIVA DE ESPERA
    # ══════════════════════════════════════════════════════════════════

    # 1. Pagamento inverso
    if detect_inverse_payment(numbers, bets):
        spins_required += 1
        reasons.append(f"alvo pago antes do gatilho (+1)")

    # 2. Gatilho vem de consecutivo
    if detect_trigger_from_consecutive(numbers):
        spins_required += 1
        reasons.append(f"gatilho veio de crescente/decrescente ({numbers[1]}) (+1)")

    # 3. Gatilho preso em padrao
    if detect_trigger_trapped_in_pattern(numbers):
        spins_required += 1
        reasons.append(f"gatilho preso em padrao com {numbers[1]} (+1)")

    # 4. Retorno de numero apos gatilho (padrao suspeito)
    if detect_number_return_after_trigger(numbers):
        spins_required += 1
        reasons.append(f"padrao de retorno proximo ao gatilho (+1)")

    # ══════════════════════════════════════════════════════════════════
    # VERIFICACOES QUE ATRASAM
    # ══════════════════════════════════════════════════════════════════

    # Verifica compatibilidade de cenario primeiro
    is_compatible, similarity = detect_scenario_compatibility(numbers, trigger)

    if is_compatible and similarity >= 0.5 and spins_required == 0:
        # Cenario muito compativel - provavelmente sem atraso
        return 0, f"Cenario compativel ({similarity:.0%}) - entrada imediata"

    # 1. Zero antes do gatilho
    zero_delay = detect_zero_before_trigger(numbers)
    if zero_delay > 0:
        spins_required += zero_delay
        reasons.append(f"zero antes do gatilho (+{zero_delay})")

    # 2. Retorno de numero antes do gatilho
    return_delay = detect_number_return_before_trigger(numbers)
    if return_delay > 0:
        spins_required += return_delay
        reasons.append(f"retorno de numero (+{return_delay})")

    # 3. Repeticao antes do gatilho
    rep_delay = detect_repetition_before_trigger(numbers)
    if rep_delay > 0:
        spins_required += rep_delay
        reasons.append(f"repeticao (+{rep_delay})")

    # 4. Alternancia antes do gatilho
    alt_delay = detect_alternation_before_trigger(numbers)
    if alt_delay > 0:
        spins_required += alt_delay
        reasons.append(f"alternancia (+{alt_delay})")

    # 5. Crescente/Decrescente antes do gatilho
    if len(numbers) >= 4:
        num2 = numbers[2]
        num3 = numbers[3]
        if is_consecutive(num2, num3):
            spins_required += 2
            reasons.append(f"crescente/decrescente ({num3}>{num2}) (+2)")

    # Monta mensagem
    if spins_required > 0:
        message = f"Atraso de {spins_required} rodadas: {', '.join(reasons)}"
    else:
        message = "Entrada imediata"

    return spins_required, message


# ══════════════════════════════════════════════════════════════════════════════
# FUNCOES DE CONSTRUCAO DO SINAL
# ══════════════════════════════════════════════════════════════════════════════

def _build_signal(
    *,
    roulette: dict,
    numbers: list[int],
    trigger: int,
    bet: list[int],
    score: int,
    support_label: str,
    pattern: str,
    spins_required: int = 0,
    behavior_message: str = "",
    simple_metrics: Optional[dict] = None,
) -> dict:
    created_at = int(datetime.now().timestamp())
    metrics = dict(simple_metrics or {})

    message = f"API Monitor - Sugestão simples: {support_label}"
    if behavior_message:
        message = f"{message} | {behavior_message}"

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": pattern,
        "triggers": trigger,
        "targets": [trigger],
        "bets": bet,
        "passed_spins": 0,
        "spins_required": spins_required,
        "spins_count": 0,
        "gales": 20,
        "score": score,
        "snapshot": numbers[:200],
        "status": "processing",
        "message": message,
        "tags": ["api_monitor"],
        "temp_state": {
            "behavior_analysis": behavior_message,
            "spins_required": spins_required,
            "pattern_count": int(metrics.get("pattern_count", 0) or 0),
            "top_support_count": int(metrics.get("top_support_count", 0) or 0),
            "min_support_count": int(metrics.get("min_support_count", 0) or 0),
            "avg_support_count": float(metrics.get("avg_support_count", 0.0) or 0.0),
        },
        "created_at": created_at,
        "timestamp": created_at,
    }


def _call_api_simple_suggestion(history: list[int], focus_number: int, max_numbers: int = 12) -> dict | None:
    """
    Chama o endpoint /api/patterns/simple-suggestion para obter a sugestao simples.
    Cada pattern positivo que citar um numero soma 1 apoio para esse numero.
    """
    url = f"{URL_API.rstrip('/')}/api/patterns/simple-suggestion"

    payload = {
        "history": history,
        "focus_number": focus_number,
        "from_index": 0,
        "max_numbers": max_numbers,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        print(f"[api_monitor] Erro ao chamar API: {e}")
        return None


def _extract_simple_metrics(payload: dict) -> dict:
    selected_details = payload.get("selected_number_details")
    if not isinstance(selected_details, list):
        selected_details = []

    top_support_count = int(payload.get("top_support_count", 0) or 0)
    min_support_count = int(payload.get("min_support_count", 0) or 0)
    avg_support_count = float(payload.get("avg_support_count", 0.0) or 0.0)

    if not top_support_count and selected_details:
        top_support_count = int(selected_details[0].get("support_score", 0) or 0)
    if not min_support_count and selected_details:
        min_support_count = int(selected_details[-1].get("support_score", 0) or 0)
    if avg_support_count <= 0 and selected_details:
        avg_support_count = round(
            sum(int(item.get("support_score", 0) or 0) for item in selected_details) / len(selected_details),
            2,
        )

    return {
        "pattern_count": int(payload.get("pattern_count", 0) or 0),
        "top_support_count": top_support_count,
        "min_support_count": min_support_count,
        "avg_support_count": avg_support_count,
        "selected_number_details": selected_details,
    }


# ══════════════════════════════════════════════════════════════════════════════
# FUNCAO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def process_roulette(roulette, numbers):
    """
    Processa a roleta chamando a API de sugestoes e montando o sinal.

    - Recebe o numero mais recente
    - Analisa comportamentos que podem atrasar ou cancelar a jogada
    - Chama a API para obter sugestao simples (limitada a 12 numeros)
    - Usa a contagem de apoio dos patterns como metrica operacional
    """
    if not numbers or len(numbers) < 10:
        return None

    # Numero mais recente como trigger/focus
    focus_number = numbers[0]

    # Chama a API com max_numbers = 12 usando a sugestao simples por apoio.
    result = _call_api_simple_suggestion(
        history=numbers,
        focus_number=focus_number,
        max_numbers=12
    )

    if not result:
        return None

    # Verifica se a API retornou sugestao valida
    if not result.get("available", False):
        return None

    suggestion = result.get("suggestion", [])
    if not suggestion:
        return None

    # Se a sugestao nao tiver exatamente 12 numeros, pula
    if len(suggestion) < 12:
        print(f"[api_monitor] {roulette['slug']}: Sugestao com apenas {len(suggestion)} numeros, pulando...")
        return None

    # Usa exatamente 12 numeros
    bet = suggestion[:12]
    simple_metrics = _extract_simple_metrics(result)

    # Debug: mostra sugestao apenas para pragmatic-brazilian-roulette
    if roulette.get("slug") == "pragmatic-brazilian-roulette":
        support_details = simple_metrics.get("selected_number_details", [])
        print(f"\n{'='*60}")
        print(f"[api_monitor DEBUG] Roleta: {roulette['slug']}")
        print(f"[api_monitor DEBUG] Gatilho: {focus_number}")
        print(f"{'='*60}")
        print(f"[api_monitor DEBUG] Sugestao Simples: {suggestion}")
        print(f"[api_monitor DEBUG] Bet (12 nums): {bet}")
        print(f"{'='*60}")
        print(f"[api_monitor DEBUG] - Patterns positivos: {simple_metrics['pattern_count']}")
        print(f"[api_monitor DEBUG] - Top support: {simple_metrics['top_support_count']}")
        print(f"[api_monitor DEBUG] - Min support: {simple_metrics['min_support_count']}")
        print(f"[api_monitor DEBUG] - Avg support: {simple_metrics['avg_support_count']:.2f}")
        if support_details:
            top_votes = ", ".join(
                f"{item.get('number')}({item.get('support_score')}x)"
                for item in support_details[:6]
                if isinstance(item, dict)
            )
            print(f"[api_monitor DEBUG] - Top votos: {top_votes}")
        print(f"{'='*60}\n")

    # ══════════════════════════════════════════════════════════════════
    # ANALISE COMPORTAMENTAL
    # ══════════════════════════════════════════════════════════════════
    spins_required, behavior_message = analyze_behavior(numbers, bet)

    support_score = int(simple_metrics.get("top_support_count", 0) or 0)
    support_label = (
        f"{int(simple_metrics.get('pattern_count', 0) or 0)} pattern(s) | "
        f"topo {support_score} apoio(s) | "
        f"média {float(simple_metrics.get('avg_support_count', 0.0) or 0.0):.2f}"
    )

    # Monta e retorna o sinal
    return _build_signal(
        roulette=roulette,
        numbers=numbers,
        trigger=focus_number,
        bet=bet,
        score=support_score,
        support_label=support_label,
        pattern="API_MONITOR_SIMPLE",
        spins_required=spins_required,
        behavior_message=behavior_message,
        simple_metrics=simple_metrics,
    )
