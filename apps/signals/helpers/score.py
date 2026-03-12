from collections import defaultdict
import statistics
# Ordem física da roleta europeia
ROULETTE = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8,
    23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28,
    12, 35, 3, 26
]

# Mapa de vizinhos diretos
NEIGHBORS = {
    n: (
        ROULETTE[(i - 1) % len(ROULETTE)],
        ROULETTE[(i + 1) % len(ROULETTE)]
    )
    for i, n in enumerate(ROULETTE)
}



def extract_windows(history, base, window_size=5):
    """
    Lê o histórico de baixo para cima e
    retorna as janelas após cada ocorrência do base
    """
    history = history[::-1]  # inverte (mais antigo → mais recente)
    windows = []

    for i, n in enumerate(history):
        if n != base:
            continue

        start = i + 1
        end = start + window_size

        if end <= len(history):
            windows.append(history[start:end])

    return windows


def compute_score(windows, neighbor_weight=0.5):
    """
    Calcula o score considerando:
    - peso temporal crescente
    - peso de vizinhança
    """
    score = defaultdict(float)

    for idx, window in enumerate(windows):
        weight = idx + 1  # peso temporal

        for n in window:
            score[n] += weight

            # aplica peso aos vizinhos
            for neighbor in NEIGHBORS[n]:
                score[neighbor] += weight * neighbor_weight

    return score


def rank_scores(score, top_n=15):
    return sorted(score.items(), key=lambda x: x[1], reverse=True)[:top_n]



def nivel_confianca(scores):
    return round(sum(scores), 2)



def get_ranking(history, base_number, window_size, top_n) :

    windows = extract_windows(history, base_number, window_size)
    score = compute_score(windows)
    ranking = rank_scores(score, top_n)

    # coleta apenas os valores
    top_scores = [score for _, score in ranking]

    confianca = nivel_confianca(top_scores)

    return ranking, confianca




