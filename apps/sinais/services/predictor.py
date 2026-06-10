"""Gerador de entrada — heurística de sucessores portada de previsao_roleta.py.

Adaptado para o produto: 12 palpites, janela de 3 tentativas, alimentado
pelos últimos 300 números.

Como funciona (resumo):
1. Constrói um mapa de "sucessores em janela": para cada número X, conta quem
   apareceu nas `JANELA` rodadas seguintes a X ao longo do histórico.
2. Pontua candidatos combinando os sucessores dos últimos 3 números sorteados,
   com pesos 3/2/1 (mais recente pesa mais), normalizados pela ocorrência do
   gatilho.
3. Soma um prior leve de frequência global (0.3) para desempate.
4. Retorna os `QTD_PALPITES` candidatos de maior score.
"""

from collections import Counter
from typing import Any

JANELA = 3                       # tentativas / janela de apuração
QTD_PALPITES = 12                # tamanho da entrada
PESOS_ULTIMOS = [3.0, 2.0, 1.0]  # peso do mais recente para trás
PRIOR_GLOBAL = 0.3               # peso do prior de frequência global
MIN_HISTORICO = 50               # mínimo de números para gerar


def mapa_sucessores(cronologico: list[int], janela: int) -> dict[int, Counter]:
    """Para cada número, conta quem apareceu nas `janela` rodadas seguintes."""
    succ: dict[int, Counter] = {i: Counter() for i in range(37)}
    n = len(cronologico)
    for idx in range(n - janela):
        gatilho = cronologico[idx]
        for j in range(1, janela + 1):
            succ[gatilho][cronologico[idx + j]] += 1
    return succ


def gerar_palpites(
    cronologico: list[int],
    janela: int = JANELA,
    qtd: int = QTD_PALPITES,
) -> dict[str, Any]:
    """Gera a entrada a partir do histórico em ordem CRONOLÓGICA (antigo→recente)."""
    if len(cronologico) < MIN_HISTORICO:
        raise ValueError(
            f"Histórico muito curto ({len(cronologico)}); mínimo {MIN_HISTORICO} números."
        )

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

    ranking = score.most_common()
    palpites = sorted(num for num, _ in ranking[:qtd])

    return {
        "numbers": palpites,
        "ranking_top": [(num, round(s, 4)) for num, s in ranking[:qtd]],
        "ultimos_3": cronologico[-3:],
        "total_numeros": n,
    }


def gerar_de_historico_desc(numeros_desc: list[int], **kwargs) -> dict[str, Any]:
    """Atalho: recebe o histórico como vem do banco (mais recente primeiro)."""
    cronologico = list(numeros_desc)[::-1]
    return gerar_palpites(cronologico, **kwargs)


if __name__ == "__main__":  # smoke test rápido com a lista do arquivo original
    historico_desc = [
        9, 22, 7, 6, 9, 22, 24, 12, 30, 22, 28, 22, 15, 28, 8, 27, 28,
        23, 13, 26, 19, 0, 17,
    ] * 3
    print(gerar_de_historico_desc(historico_desc))
