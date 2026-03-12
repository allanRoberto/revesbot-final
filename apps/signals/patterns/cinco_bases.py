"""
Padrao Cinco Bases (5 BASES)

Detecta formacoes de 5 bases com terminais validos (4, 5, 7, 8).

Logica:
- BASE3 -> conta pra tras -> BASE2
- BASE2 -> conta pra tras -> BASE1
- Proxima ocorrencia de BASE3 = BASE4
- BASE4 -> conta pra frente -> BASE5
- Entrada na ultima rodada da contagem de BASE5

Alvos:
- grupo1 = [0] + vizinhos de BASE1 na roleta
- grupo2 = [0] + vizinhos de BASE2 na roleta

Filtros:
- BASE5+4: deve aparecer numero de apenas 1 grupo (elimina esse, aposta no outro)
- BASE4+4: vizinhos de BASE1/BASE2 nao podem aparecer (cancela se aparecer)
"""

from datetime import datetime
from typing import List, Dict, Any, Optional

# ========================= CONFIGURACOES =====================================

# Quantas rodadas ANTES do fim da contagem de BASE5 para disparar o aviso
# Ex: BASE5=14, RODADAS_ANTES=4 -> aviso na jogada 11 (faltam 4: 11, 12, 13, 14)
RODADAS_ANTES_FIM_BASE5 = 4

# Numero de gales (tentativas)
GALES_DEFAULT = 6

# ========================= VIZINHOS DA ROLETA EUROPEIA ========================
# Ordem dos numeros na roleta europeia (sentido horario)
ROLETA_EUROPEIA = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5,
    24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]

def obter_vizinhos(numero: int, quantidade: int = 1) -> List[int]:
    """
    Retorna o numero e seus vizinhos na roleta europeia.

    Args:
        numero: Numero central
        quantidade: Quantos vizinhos de cada lado (default 1)

    Returns:
        Lista com [vizinho_esquerda, numero, vizinho_direita] para quantidade=1
    """
    if numero not in ROLETA_EUROPEIA:
        return [numero]

    idx = ROLETA_EUROPEIA.index(numero)
    tamanho = len(ROLETA_EUROPEIA)

    vizinhos = []
    for i in range(-quantidade, quantidade + 1):
        vizinho_idx = (idx + i) % tamanho
        vizinhos.append(ROLETA_EUROPEIA[vizinho_idx])

    return vizinhos

# ========================= FUNCOES AUXILIARES ================================

def is_terminal_valido(num) -> bool:
    """Terminal valido: 4, 5, 7 ou 8."""
    return isinstance(num, int) and num % 10 in {4, 5, 7, 8}


def _build_cancelled_signal(
    *,
    roulette: dict,
    numbers: List[int],
    formacao: Dict[str, Any],
) -> dict:
    """Monta o sinal cancelado no formato padrao."""
    created_at = int(datetime.now().timestamp())

    bases_info = formacao["bases_info"]
    base1_num = bases_info["BASE1"]["numero"]
    base2_num = bases_info["BASE2"]["numero"]
    base3_num = bases_info["BASE3"]["numero"]
    base5_num = bases_info["BASE5"]["numero"]

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "CINCO_BASES",
        "triggers": numbers[0],
        "targets": formacao["numeros_apostar"],
        "bets": formacao["numeros_apostar"],
        "passed_spins": 0,
        "spins_required": 0,
        "spins_count": 0,
        "gales": 0,
        "score": 0,
        "snapshot": numbers[:500],
        "status": "cancelled",
        "message": formacao["cancel_message"],
        "tags": ["cinco_bases", "5_bases", "terminal_pattern", "cancelled"],
        "temp_state": {
            "bases": bases_info,
            "concordancia": formacao["concordancia_info"],
            "trigger": formacao["trigger_info"],
            "numeros_encontrados_base4": formacao["numeros_encontrados"],
            "motivo_cancelamento": "Grupo alvo apareceu nas 4 jogadas apos BASE4",
        },
        "created_at": created_at,
        "timestamp": created_at,
    }


def _build_signal(
    *,
    roulette: dict,
    numbers: List[int],
    numeros_apostar: List[int],
    bases_info: Dict[str, Any],
    concordancia_info: Dict[str, Any],
    trigger_info: Dict[str, Any],
) -> dict:
    """Monta o sinal no formato padrao."""
    created_at = int(datetime.now().timestamp())

    base1_num = bases_info["BASE1"]["numero"]
    base2_num = bases_info["BASE2"]["numero"]
    base3_num = bases_info["BASE3"]["numero"]
    base5_num = bases_info["BASE5"]["numero"]

    message = (
        f"5 BASES detectado | "
        f"B1:{base1_num} B2:{base2_num} B3:{base3_num} B5:{base5_num} | "
        f"Alvos: {numeros_apostar}"
    )

    return {
        "roulette_id": roulette["slug"],
        "roulette_name": roulette["name"],
        "roulette_url": roulette["url"],
        "pattern": "CINCO_BASES",
        "triggers": numbers[0],
        "targets": numeros_apostar,
        "bets": numeros_apostar,
        "passed_spins": 0,
        "spins_required": RODADAS_ANTES_FIM_BASE5,
        "spins_count": 0,
        "gales": GALES_DEFAULT,
        "score": 0,  # Score alto por ser padrao complexo
        "snapshot": numbers[:500],
        "status": "processing",
        "message": message,
        "tags": ["cinco_bases", "5_bases", "terminal_pattern"],
        "temp_state": {
            "bases": bases_info,
            "concordancia": concordancia_info,
            "trigger": trigger_info,
            "rodadas_restantes": RODADAS_ANTES_FIM_BASE5,
        },
        "created_at": created_at,
        "timestamp": created_at,
    }


# ========================= LOGICA PRINCIPAL DE DETECCAO ======================

def detectar_formacao(bruto: List[int]) -> Optional[Dict[str, Any]]:
    """
    Varre o bruto (newest-first) em busca de formacoes onde o spin atual
    e exatamente o momento de trigger.

    Estrutura do bruto (newest-first):
      bruto[0..4]          extras (mais recentes)
      bruto[5..idx_base5-1] contagem_base5
      bruto[idx_base5]     BASE5
      bruto[idx_base5+1..idx_base4-1] contagem_base4
      bruto[idx_base4]     BASE4
      ...
      bruto[idx_base3]     BASE3
      ...
      bruto[idx_base2]     BASE2
      ...
      bruto[idx_base1]     BASE1

    Retorna dict com informacoes da formacao ou None se nao encontrar.
    """
    n = len(bruto)

    for i in range(n):
        # ── 1. Candidato BASE3 ──────────────────────────────────────────────
        base3_num = bruto[i]
        if not is_terminal_valido(base3_num):
            continue

        # ── 2. BASE2 ─────────────────────────────────────────────────────────
        idx_base2 = i + (base3_num - 1)
        if idx_base2 >= n:
            continue
        base2_num = bruto[idx_base2]
        if not is_terminal_valido(base2_num):
            continue

        # ── 3. BASE1 ─────────────────────────────────────────────────────────
        idx_base1 = idx_base2 + (base2_num - 1)
        if idx_base1 >= n:
            continue
        base1_num = bruto[idx_base1]
        if not is_terminal_valido(base1_num):
            continue

        # ── 4. BASE4: primeira re-ocorrencia de base3_num MAIS RECENTE que BASE3 ─
        idx_base4 = None
        for j in range(i - 1, -1, -1):
            if bruto[j] == base3_num:
                idx_base4 = j
                break
        if idx_base4 is None:
            continue

        base4_num = base3_num  # BASE4 repete o numero de BASE3

        # ── 5. BASE5 ─────────────────────────────────────────────────────────
        idx_base5 = idx_base4 - (base4_num - 1)
        if idx_base5 < 0:
            continue
        base5_num = bruto[idx_base5]
        if not is_terminal_valido(base5_num):
            continue

        # ── 6. Calcular indice do trigger ─────────────────────────────────────
        # Contamos base5_num jogadas a partir de BASE5 (contando BASE5 como jogada 1)
        # A jogada base5_num é a última da contagem (entrada principal)
        # Aviso dispara RODADAS_ANTES_FIM_BASE5 jogadas antes do fim
        # Ex: BASE5=27, RODADAS_ANTES=4 -> trigger na jogada 24 (faltam 4: 24,25,26,27)
        trigger_idx = idx_base5 - (base5_num - RODADAS_ANTES_FIM_BASE5 - 2)
        if trigger_idx < 0 or trigger_idx >= n:
            continue

        # ══════════════════ VERIFICAR SE E O MOMENTO DO TRIGGER ═══════════════
        # O trigger deve ser o numero mais recente (indice 0)
        if trigger_idx != 0:
            continue

        trigger_num = bruto[trigger_idx]

        # ══════════════════ TRIGGER CONFIRMADO ═══════════════════════════════

        # ── Montar grupos de alvos: vizinhos + 0 ──────────────────────────────
        # grupo1 = [0] + vizinhos de BASE1 (ex: BASE1=34 -> [0, 17, 34, 6])
        # grupo2 = [0] + vizinhos de BASE2 (ex: BASE2=24 -> [0, 16, 24, 5])
        vizinhos_base1 = obter_vizinhos(base1_num, 1)  # [17, 34, 6]
        vizinhos_base2 = obter_vizinhos(base2_num, 1)  # [16, 24, 5]

        grupo1 = [0] + vizinhos_base1  # [0, 17, 34, 6]
        grupo2 = [0] + vizinhos_base2  # [0, 16, 24, 5]

        # Verificar se grupos compartilham numeros (exceto 0)
        compartilhados = set(grupo1) & set(grupo2) - {0}
        if compartilhados:
            continue  # Grupos compartilham numeros — formacao invalida

        # BASE5 + 4 posteriores (mais recentes = indice menor no bruto newest-first)
        base5_rodadas = [
            bruto[idx_base5 - k]
            for k in range(0, 5)
            if 0 <= idx_base5 - k < n
        ]

        grupo1_na_base5 = any(num in grupo1 and num != 0 for num in base5_rodadas)
        grupo2_na_base5 = any(num in grupo2 and num != 0 for num in base5_rodadas)

        if not grupo1_na_base5 and not grupo2_na_base5:
            continue  # Nenhum grupo em BASE5 — formacao invalida
        if grupo1_na_base5 and grupo2_na_base5:
            continue  # Ambos os grupos em BASE5 — formacao invalida

        # Grupo eliminado em BASE5; o grupo restante e o alvo
        if grupo1_na_base5:
            grupo_eliminado = 'grupo1'
            alvos_eliminados = grupo1
            numeros_apostar = grupo2
        else:
            grupo_eliminado = 'grupo2'
            alvos_eliminados = grupo2
            numeros_apostar = grupo1

        # ── 7. Verificar BASE4 + 4 jogadas ─────────────────────────────────────
        # Numeros proibidos = vizinhos de BASE1 e BASE2 (inclui os proprios BASE1 e BASE2)
        numeros_proibidos = set(vizinhos_base1 + vizinhos_base2)

        # 4 jogadas APÓS BASE4 (não inclui BASE4)
        base4_rodadas = [
            bruto[idx_base4 - k]
            for k in range(1, 5)
            if 0 <= idx_base4 - k < n
        ]

        # Se qualquer numero proibido apareceu nas 4 jogadas apos BASE4, cancela
        numeros_encontrados = [num for num in base4_rodadas if num in numeros_proibidos]
        if numeros_encontrados:
            cancel_message = (
                f"5 BASES CANCELADO | "
                f"BASE4+4: {base4_rodadas} | "
                f"Vizinhos BASE1 ({base1_num}): {vizinhos_base1} | "
                f"Vizinhos BASE2 ({base2_num}): {vizinhos_base2} | "
                f"Encontrado(s): {numeros_encontrados} | "
                f"Motivo: Vizinhos de BASE1/BASE2 apareceram nas 4 jogadas apos BASE4"
            )
            print(f"\n{'='*60}")
            print(f"  *** 5 BASES CANCELADO ***")
            print(f"  BASE4+4 jogadas: {base4_rodadas}")
            print(f"  Vizinhos BASE1 ({base1_num}): {vizinhos_base1}")
            print(f"  Vizinhos BASE2 ({base2_num}): {vizinhos_base2}")
            print(f"  Numero(s) encontrado(s): {numeros_encontrados}")
            print(f"  Motivo: Vizinhos de BASE1/BASE2 apareceram nas 4 jogadas apos BASE4")
            print(f"{'='*60}\n")

            # Retorna formação cancelada
            return {
                "cancelled": True,
                "cancel_message": cancel_message,
                "numeros_apostar": numeros_apostar,
                "numeros_encontrados": numeros_encontrados,
                "bases_info": {
                    "BASE1": {"numero": base1_num, "terminal": base1_num % 10, "indice": idx_base1},
                    "BASE2": {"numero": base2_num, "terminal": base2_num % 10, "indice": idx_base2},
                    "BASE3": {"numero": base3_num, "terminal": base3_num % 10, "indice": i},
                    "BASE4": {"numero": base4_num, "terminal": base4_num % 10, "indice": idx_base4},
                    "BASE5": {"numero": base5_num, "terminal": base5_num % 10, "indice": idx_base5},
                },
                "concordancia_info": {
                    "base1_num": base1_num,
                    "grupo1": grupo1,
                    "base2_num": base2_num,
                    "grupo2": grupo2,
                    "grupo_eliminado": grupo_eliminado,
                    "alvos_eliminados": alvos_eliminados,
                    "base5_rodadas": base5_rodadas,
                    "base4_rodadas": base4_rodadas,
                    "vizinhos_base1": vizinhos_base1,
                    "vizinhos_base2": vizinhos_base2,
                    "alvos_finais": numeros_apostar,
                },
                "trigger_info": {
                    "numero": trigger_num,
                    "indice": trigger_idx,
                },
            }

        # ══════════════════ FORMACAO VALIDA ═══════════════════════════════════

        return {
            "numeros_apostar": numeros_apostar,
            "bases_info": {
                "BASE1": {
                    "numero": base1_num,
                    "terminal": base1_num % 10,
                    "indice": idx_base1,
                },
                "BASE2": {
                    "numero": base2_num,
                    "terminal": base2_num % 10,
                    "indice": idx_base2,
                },
                "BASE3": {
                    "numero": base3_num,
                    "terminal": base3_num % 10,
                    "indice": i,
                },
                "BASE4": {
                    "numero": base4_num,
                    "terminal": base4_num % 10,
                    "indice": idx_base4,
                },
                "BASE5": {
                    "numero": base5_num,
                    "terminal": base5_num % 10,
                    "indice": idx_base5,
                },
            },
            "concordancia_info": {
                "base1_num": base1_num,
                "grupo1": grupo1,
                "base2_num": base2_num,
                "grupo2": grupo2,
                "grupo_eliminado": grupo_eliminado,
                "alvos_eliminados": alvos_eliminados,
                "base5_rodadas": base5_rodadas,
                "base4_rodadas": base4_rodadas,
                "vizinhos_base1": vizinhos_base1,
                "vizinhos_base2": vizinhos_base2,
                "alvos_finais": numeros_apostar,
            },
            "trigger_info": {
                "numero": trigger_num,
                "indice": trigger_idx,
            },
        }

    return None


# ========================= FUNCAO PRINCIPAL ==================================

def process_roulette(roulette: dict, numbers: List[int], full_results: List[Dict] = None) -> Optional[dict]:
    """
    Processa a roleta buscando o padrao das 5 BASES.

    Args:
        roulette: Objeto com slug, name e url da roleta
        numbers: Lista de inteiros com o historico (mais recente no indice 0)
        full_results: (Opcional) Lista de objetos completos - nao usado neste padrao

    Returns:
        Sinal formatado ou None se nao encontrar padrao
    """
    if not numbers or len(numbers) < 50:
        return None

    print(f"Detectando padrao 5 BASES na roleta [{roulette['slug']}] ...")

    # Detecta formacao
    formacao = detectar_formacao(numbers)

    if not formacao:
        return None

    # Verifica se a formacao foi cancelada (filtro BASE4+4)
    if formacao.get("cancelled"):
        return _build_cancelled_signal(
            roulette=roulette,
            numbers=numbers,
            formacao=formacao,
        )

    # Log da deteccao
    bases = formacao["bases_info"]
    concordancia = formacao["concordancia_info"]
    numeros_apostar = formacao["numeros_apostar"]

    print(f"\n{'='*60}")
    print(f"  *** PADRAO 5 BASES DETECTADO ***")
    print(f"  Roleta: {roulette['slug']}")
    print(f"{'='*60}")
    print(f"  BASE1: {bases['BASE1']['numero']:>2} | terminal {bases['BASE1']['terminal']}")
    print(f"  BASE2: {bases['BASE2']['numero']:>2} | terminal {bases['BASE2']['terminal']}")
    print(f"  BASE3: {bases['BASE3']['numero']:>2} | terminal {bases['BASE3']['terminal']}")
    print(f"  BASE4: {bases['BASE4']['numero']:>2} | terminal {bases['BASE4']['terminal']}")
    print(f"  BASE5: {bases['BASE5']['numero']:>2} | terminal {bases['BASE5']['terminal']}")
    print(f"{'─'*60}")
    print(f"  Concordancia:")
    print(f"    BASE1 ({concordancia['base1_num']}) -> grupo1 {concordancia['grupo1']}")
    print(f"    BASE2 ({concordancia['base2_num']}) -> grupo2 {concordancia['grupo2']}")
    print(f"    Eliminado: {concordancia['grupo_eliminado']} {concordancia['alvos_eliminados']}")
    print(f"    BASE5+4: {concordancia['base5_rodadas']}")
    print(f"    BASE4+4: {concordancia['base4_rodadas']}")
    print(f"    Vizinhos BASE1: {concordancia.get('vizinhos_base1', 'N/A')}")
    print(f"    Vizinhos BASE2: {concordancia.get('vizinhos_base2', 'N/A')}")
    print(f"{'─'*60}")
    print(f"  NUMEROS PARA APOSTAR: {numeros_apostar}")
    print(f"  Faltam {RODADAS_ANTES_FIM_BASE5} rodadas para entrada (jogada {bases['BASE5']['numero']})")
    print(f"{'='*60}\n")

    # Monta e retorna o sinal
    return _build_signal(
        roulette=roulette,
        numbers=numbers,
        numeros_apostar=numeros_apostar,
        bases_info=formacao["bases_info"],
        concordancia_info=formacao["concordancia_info"],
        trigger_info=formacao["trigger_info"],
    )
