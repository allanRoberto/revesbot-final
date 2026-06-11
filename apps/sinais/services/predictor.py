"""Gerador de entrada — modo SETORES (arcos contíguos na roda física).

Mesmo score de sucessores do previsao_roleta.py, mas a seleção dos números é
feita como 1 a 3 arcos CONTÍGUOS na roda física (sem "buracos"): o score de
cada número "vaza" para os vizinhos físicos (kernel 0.5/1.0/0.5) e escolhemos a
combinação de arcos que maximiza o score suavizado.

A busca ótima é feita por programação dinâmica (corte do ciclo num buraco +
DP linear), equivalente à força-bruta do arquivo original mas em ~200ms mesmo
para 26 números (a força-bruta levava ~30s).
"""

from collections import Counter
from typing import Any

JANELA = 3                       # tentativas / janela de apuração
QTD_PALPITES = 12                # tamanho padrão da entrada
PESOS_ULTIMOS = [3.0, 2.0, 1.0]  # peso do mais recente para trás
PRIOR_GLOBAL = 0.3               # peso do prior de frequência global
MIN_HISTORICO = 50               # mínimo de números para gerar
KERNEL = (0.5, 1.0, 0.5)         # espalhamento do score p/ vizinhos físicos
MIN_ARCO = 3                     # tamanho mínimo de cada arco

# Ordem física da roda europeia (single-zero).
WHEEL = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
         5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]


def mapa_sucessores(cronologico: list[int], janela: int) -> dict[int, Counter]:
    """Para cada número, conta quem apareceu nas `janela` rodadas seguintes."""
    succ: dict[int, Counter] = {i: Counter() for i in range(37)}
    n = len(cronologico)
    for idx in range(n - janela):
        gatilho = cronologico[idx]
        for j in range(1, janela + 1):
            succ[gatilho][cronologico[idx + j]] += 1
    return succ


def _score_map(cronologico: list[int], janela: int) -> Counter:
    """Score base: sucessores ponderados dos últimos 3 + prior de frequência."""
    n = len(cronologico)
    succ = mapa_sucessores(cronologico, janela)
    score: Counter = Counter()
    ultimos = cronologico[-len(PESOS_ULTIMOS):][::-1]  # [mais_recente, ...]
    for num, peso in zip(ultimos, PESOS_ULTIMOS):
        total = sum(succ[num].values())
        if total:
            for cand, c in succ[num].items():
                score[cand] += peso * c / total
    freq = Counter(cronologico)
    for cand in range(37):
        score[cand] += PRIOR_GLOBAL * freq[cand] / n
    return score


def gerar_palpites(cronologico: list[int], janela: int = JANELA,
                   qtd: int = QTD_PALPITES) -> dict[str, Any]:
    """Modo clássico: top-N números soltos (mantido para referência/backtests)."""
    if len(cronologico) < MIN_HISTORICO:
        raise ValueError(
            f"Histórico muito curto ({len(cronologico)}); mínimo {MIN_HISTORICO} números."
        )
    score = _score_map(cronologico, janela)
    ranking = score.most_common()
    return {
        "numbers": sorted(num for num, _ in ranking[:qtd]),
        "ranking_top": [(num, round(s, 4)) for num, s in ranking[:qtd]],
        "total_numeros": len(cronologico),
    }


def _pos_scores(score: Counter, kernel: tuple = KERNEL) -> list[float]:
    """Espalha o score de cada número para suas posições vizinhas na roda."""
    pos = [0.0] * 37
    for i, num in enumerate(WHEEL):
        s = score[num]
        pos[(i - 1) % 37] += kernel[0] * s
        pos[i] += kernel[1] * s
        pos[(i + 1) % 37] += kernel[2] * s
    return pos


def _dp_line(v: list[float], qtd: int, m: int, minlen: int = MIN_ARCO):
    """DP: escolhe `qtd` posições numa LINHA formando exatamente `m` arcos
    (cada um >= minlen), maximizando a soma. Retorna (score, mask) ou None."""
    n = len(v)
    NEG = float("-inf")
    cur: dict = {(0, 0, 0): 0.0}     # estado (selecionados, arcos, comprimento_atual)
    par: list = [None] * n
    for t in range(n):
        nxt: dict = {}
        pt: dict = {}
        for (j, r, c), sc in cur.items():
            # pular a posição t
            if c == 0 or c == minlen:
                st = (j, r, 0)
                if sc > nxt.get(st, NEG):
                    nxt[st] = sc
                    pt[st] = ((j, r, c), "skip")
            # selecionar a posição t
            if c == 0:
                if r + 1 <= m:
                    st = (j + 1, r + 1, 1)
                    val = sc + v[t]
                    if val > nxt.get(st, NEG):
                        nxt[st] = val
                        pt[st] = ((j, r, c), "sel")
            else:
                st = (j + 1, r, min(c + 1, minlen))
                val = sc + v[t]
                if val > nxt.get(st, NEG):
                    nxt[st] = val
                    pt[st] = ((j, r, c), "sel")
        cur = nxt
        par[t] = pt

    best = None
    for (j, r, c), sc in cur.items():
        if j == qtd and r == m and c in (0, minlen):
            if best is None or sc > best[1]:
                best = ((j, r, c), sc)
    if best is None:
        return None

    state = best[0]
    mask = [False] * n
    for t in range(n - 1, -1, -1):
        prev, act = par[t][state]
        if act == "sel":
            mask[t] = True
        state = prev
    return best[1], mask


def gerar_setores(cronologico: list[int], qtd: int, janela: int = JANELA,
                  kernel: tuple = KERNEL, minlen: int = MIN_ARCO) -> dict[str, Any]:
    """Seleciona `qtd` números como 1 a 3 arcos contíguos na roda física."""
    if len(cronologico) < MIN_HISTORICO:
        raise ValueError(
            f"Histórico muito curto ({len(cronologico)}); mínimo {MIN_HISTORICO} números."
        )

    score = _score_map(cronologico, janela)
    pos = _pos_scores(score, kernel)
    L = 37

    best = None  # (score, cut, mask)
    for m in (1, 2, 3):
        if qtd < m * minlen:
            continue
        for cut in range(L):
            v = [pos[(cut + 1 + t) % L] for t in range(L - 1)]
            res = _dp_line(v, qtd, m, minlen)
            if res is None:
                continue
            sc, mask = res
            if best is None or sc > best[0]:
                best = (sc, cut, mask)

    if best is None:
        raise ValueError(f"não foi possível formar {qtd} números em setores")

    sc, cut, mask = best
    arcos: list[list[int]] = []
    atual: list[int] = []
    for t in range(L - 1):
        if mask[t]:
            atual.append(WHEEL[(cut + 1 + t) % L])
        elif atual:
            arcos.append(atual)
            atual = []
    if atual:
        arcos.append(atual)

    numbers = sorted(n for arco in arcos for n in arco)
    return {
        "numbers": numbers,
        "arcos": arcos,
        "score": round(sc, 4),
        "total_numeros": len(cronologico),
    }


def gerar_de_historico_desc(numeros_desc: list[int], qtd: int = QTD_PALPITES,
                            janela: int = JANELA) -> dict[str, Any]:
    """Atalho: recebe o histórico como vem do banco (mais recente primeiro)."""
    cronologico = list(numeros_desc)[::-1]
    return gerar_setores(cronologico, qtd=qtd, janela=janela)


if __name__ == "__main__":  # smoke test rápido
    historico_desc = [
        9, 22, 7, 6, 9, 22, 24, 12, 30, 22, 28, 22, 15, 28, 8, 27, 28,
        23, 13, 26, 19, 0, 17,
    ] * 5
    for q in (8, 12, 18, 26):
        r = gerar_de_historico_desc(historico_desc, qtd=q)
        print(f"qtd={q}: {r['numbers']}  arcos={r['arcos']}")
