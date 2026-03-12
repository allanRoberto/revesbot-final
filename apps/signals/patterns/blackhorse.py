"""
Padrao Black Horse (Math Absolu)

Detecta formacoes baseadas em gatilhos 10, 20 ou 30.

Logica:
- Gatilho: numeros 10, 20 ou 30 no spin mais recente
- Numero anterior ao gatilho e usado para calcular o grupo alvo
- Loop matematico: subtrai 36 ate encontrar terminal valido (1,4,7 ou 2,5,8)
- Cancelamento por ruido: abs(val) em {11, 22, 33, 10, 20, 30}

Alvos:
- Grupo 147: todos os numeros com terminal 1, 4 ou 7 + protecao 10 + zero
- Grupo 258: todos os numeros com terminal 2, 5 ou 8 + protecao 20 + zero
"""

from datetime import datetime
from typing import List, Dict, Optional

# ========================= CONFIGURACOES =====================================

# Gatilhos validos
GATILHOS = [10, 20, 30]

# Valores de ruido (cancelam a formacao)
RUIDO_VALORES = {11, 22, 33, 10, 20, 30}

# Numero de gales (tentativas)
GALES_DEFAULT = 4


# ========================= FUNCOES AUXILIARES ================================

def get_terminal(num: int) -> int:
    """Retorna o terminal (ultimo digito) de um numero."""
    return num % 10


def get_group_from_terminal(terminal: int) -> int:
    """
    Retorna o grupo baseado no terminal.

    Returns:
        1 para terminais {1, 4, 7}
        2 para terminais {2, 5, 8}
        0 para outros
    """
    if terminal in {1, 4, 7}:
        return 1
    if terminal in {2, 5, 8}:
        return 2
    return 0


def build_bet_set(target_group: int) -> List[int]:
    """
    Constroi o conjunto de numeros para apostar baseado no grupo alvo.

    Args:
        target_group: 1 para cavalo 147, 2 para cavalo 258

    Returns:
        Lista ordenada de numeros para apostar
    """
    if target_group == 1:
        targets = [1, 4, 7]
        protection = 10
    elif target_group == 2:
        targets = [2, 5, 8]
        protection = 20
    else:
        return []

    bet_set = {0, protection}
    for t in targets:
        for n in range(1, 37):
            if n % 10 == t:
                bet_set.add(n)

    return sorted(list(bet_set))


def analyze_blackhorse(numbers: List[int]) -> Optional[Dict]:
    """
    Analisa o historico em busca do padrao Black Horse.

    Args:
        numbers: Lista de inteiros (mais recente no indice 0)

    Returns:
        Dict com informacoes do padrao ou None se nao encontrar
    """
    if len(numbers) < 10:
        return None

    # Gatilho: numero mais recente deve ser 10, 20 ou 30
    trigger = numbers[0]
    if trigger not in GATILHOS:
        return None

    # Numero anterior ao gatilho
    n_prev = numbers[1]

    # Cancelamentos imediatos
    if n_prev == 0 or n_prev == trigger:
        return None

    # Logica matematica: Loop -36 mantendo sinal negativo ate reduzir
    val = n_prev
    target_group = 0
    math_steps = []

    while True:
        prev_val = val
        val = val - 36
        abs_val = abs(val)
        math_steps.append(f"{prev_val} - 36 = {val}")

        # Anulacao matematica (ruido de equacao)
        if abs_val in RUIDO_VALORES:
            return None

        terminal = abs_val % 10
        if terminal in {1, 4, 7}:
            target_group = 1
            break
        elif terminal in {2, 5, 8}:
            target_group = 2
            break
        elif terminal in {3, 6, 9}:
            continue
        else:
            return None

    # Construir conjunto de apostas
    bet_list = build_bet_set(target_group)

    if not bet_list:
        return None

    # Determinar nome do grupo e protecao
    if target_group == 1:
        group_name = "1-4-7"
        protection = 10
    else:
        group_name = "2-5-8"
        protection = 20

    math_str = " | ".join(math_steps)
    window_str = f"{n_prev} > {trigger}"

    return {
        "trigger": trigger,
        "n_prev": n_prev,
        "target_group": target_group,
        "group_name": group_name,
        "protection": protection,
        "bet_list": bet_list,
        "math_steps": math_steps,
        "math_str": math_str,
        "window_str": window_str,
    }


def _build_signal(
    *,
    roulette: dict,
    numbers: List[int],
    analysis: Dict,
) -> dict:
    """Monta o sinal no formato padrao."""
    created_at = int(datetime.now().timestamp())

    trigger = analysis["trigger"]
    n_prev = analysis["n_prev"]
    group_name = analysis["group_name"]
    protection = analysis["protection"]
    bet_list = analysis["bet_list"]
    math_str = analysis["math_str"]
    window_str = analysis["window_str"]

    message = (
        f"BLACK HORSE detectado | "
        f"Gatilho: {trigger} | Anterior: {n_prev} | "
        f"Cavalo {group_name} + Prot({protection}) + 0 | "
        f"Alvos: {len(bet_list)} numeros"
    )

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "BLACK_HORSE",
        "triggers": numbers[0],
        "targets": bet_list,
        "bets": bet_list,
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": GALES_DEFAULT,
        "score": 0,
        "snapshot": numbers[:500],
        "status": "processing",
        "message": message,
        "tags": ["black_horse", "cavalo", "math_pattern"],
        "temp_state": {
            "trigger": trigger,
            "n_prev": n_prev,
            "target_group": analysis["target_group"],
            "group_name": group_name,
            "protection": protection,
            "math_steps": analysis["math_steps"],
            "math_str": math_str,
            "window_str": window_str,
        },
        "created_at": created_at,
        "timestamp": created_at,
    }


# ========================= FUNCAO PRINCIPAL ==================================

def process_roulette(roulette: dict, numbers: List[int], full_results: List[Dict] = None) -> Optional[dict]:
    """
    Processa a roleta buscando o padrao Black Horse.

    Args:
        roulette: Objeto com slug, name e url da roleta
        numbers: Lista de inteiros com o historico (mais recente no indice 0)
        full_results: (Opcional) Lista de objetos completos - nao usado neste padrao

    Returns:
        Sinal formatado ou None se nao encontrar padrao
    """
    if not numbers or len(numbers) < 10:
        return None

    # Analisa o historico
    analysis = analyze_blackhorse(numbers)

    if not analysis:
        return None

    # Log da deteccao
    print(f"\n{'='*60}")
    print(f"  *** PADRAO BLACK HORSE DETECTADO ***")
    print(f"  Roleta: {roulette['slug']}")
    print(f"{'='*60}")
    print(f"  Gatilho: {analysis['trigger']}")
    print(f"  Numero anterior: {analysis['n_prev']}")
    print(f"  Decodificacao: {analysis['math_str']}")
    print(f"  Cavalo revelado: {analysis['group_name']}")
    print(f"  Protecao: {analysis['protection']}")
    print(f"{'─'*60}")
    print(f"  NUMEROS PARA APOSTAR: {analysis['bet_list']}")
    print(f"  Total: {len(analysis['bet_list'])} numeros")
    print(f"{'='*60}\n")

    # Monta e retorna o sinal
    return _build_signal(
        roulette=roulette,
        numbers=numbers,
        analysis=analysis,
    )
