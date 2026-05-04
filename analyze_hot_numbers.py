#!/usr/bin/env python3
"""
Classificar números quentes com pontuação de vizinhos
Sequência física da roleta europeia
"""

import json
from collections import defaultdict

# Sequência física da roleta europeia
ROULETTE_SEQUENCE = [
    0, 26, 3, 35, 12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16, 24, 5, 10,
    23, 8, 30, 11, 36, 13, 27, 6, 34, 17, 25, 2, 21, 4, 19, 15, 32
]

# Criar índice para buscar posição rápida
POSITION_MAP = {num: idx for idx, num in enumerate(ROULETTE_SEQUENCE)}

def get_neighbors(number, distance=3):
    """Retorna os vizinhos de um número até a distância especificada"""
    pos = POSITION_MAP[number]
    neighbors = []

    # Vizinhos à esquerda e direita (circular)
    for d in range(1, distance + 1):
        left_pos = (pos - d) % len(ROULETTE_SEQUENCE)
        right_pos = (pos + d) % len(ROULETTE_SEQUENCE)
        neighbors.append(ROULETTE_SEQUENCE[left_pos])
        neighbors.append(ROULETTE_SEQUENCE[right_pos])

    return neighbors

def score_neighbors(distance):
    """Retorna a pontuação do vizinho baseado na distância (quanto mais longe, menor o score)"""
    # Distância 1 (imediato): 0.8
    # Distância 2: 0.6
    # Distância 3: 0.4
    scores = {1: 0.8, 2: 0.6, 3: 0.4}
    return scores.get(distance, 0)

def calculate_heat_score(numbers):
    """Calcula a pontuação de calor para cada número"""
    heat_scores = defaultdict(float)

    # Contar ocorrências
    occurrences = defaultdict(int)
    for num in numbers:
        occurrences[num] += 1

    # Dar pontos para cada ocorrência do número em si
    for num, count in occurrences.items():
        heat_scores[num] += count * 1.0  # 1 ponto por ocorrência

    # Dar pontos menores para vizinhos
    for num, count in occurrences.items():
        neighbors_at_1 = [ROULETTE_SEQUENCE[(POSITION_MAP[num] - 1) % 37],
                          ROULETTE_SEQUENCE[(POSITION_MAP[num] + 1) % 37]]
        neighbors_at_2 = [ROULETTE_SEQUENCE[(POSITION_MAP[num] - 2) % 37],
                          ROULETTE_SEQUENCE[(POSITION_MAP[num] + 2) % 37]]
        neighbors_at_3 = [ROULETTE_SEQUENCE[(POSITION_MAP[num] - 3) % 37],
                          ROULETTE_SEQUENCE[(POSITION_MAP[num] + 3) % 37]]

        # Distância 1: 0.8 pontos por ocorrência do número original
        for neighbor in neighbors_at_1:
            heat_scores[neighbor] += count * 0.8

        # Distância 2: 0.6 pontos
        for neighbor in neighbors_at_2:
            heat_scores[neighbor] += count * 0.6

        # Distância 3: 0.4 pontos
        for neighbor in neighbors_at_3:
            heat_scores[neighbor] += count * 0.4

    return heat_scores, occurrences

# Carregar dados
with open("pragmatic_auto_roulette_500_numbers.json", "r") as f:
    data = json.load(f)

numbers = [item['value'] for item in data]

print(f"Analisando {len(numbers)} números...")
print(f"Sequência física (37 números): {ROULETTE_SEQUENCE}\n")

# Calcular scores
heat_scores, occurrences = calculate_heat_score(numbers)

# Ordenar por score
sorted_scores = sorted(heat_scores.items(), key=lambda x: x[1], reverse=True)

print("="*80)
print("TOP 5 NÚMEROS MAIS QUENTES")
print("="*80)

for rank, (number, score) in enumerate(sorted_scores[:5], 1):
    pos = POSITION_MAP[number]
    occ = occurrences[number]
    left_neighbor = ROULETTE_SEQUENCE[(pos - 1) % 37]
    right_neighbor = ROULETTE_SEQUENCE[(pos + 1) % 37]

    print(f"\n🔥 #{rank} - Número: {number}")
    print(f"   Posição física na roleta: {pos} (entre {left_neighbor} e {right_neighbor})")
    print(f"   Ocorrências diretas: {occ}x")
    print(f"   Pontuação total (com vizinhos): {score:.2f}")

print("\n" + "="*80)
print("TOP 10 PARA REFERÊNCIA")
print("="*80)
for rank, (number, score) in enumerate(sorted_scores[:10], 1):
    occ = occurrences[number]
    print(f"{rank:2d}. Número {number:2d} → Ocorrências: {occ:2d} | Score: {score:6.2f}")

# Salvar resultados
results = {
    "top_5": [
        {
            "rank": rank,
            "number": number,
            "occurrences": occurrences[number],
            "heat_score": score,
            "position": POSITION_MAP[number]
        }
        for rank, (number, score) in enumerate(sorted_scores[:5], 1)
    ],
    "top_10": [
        {
            "rank": rank,
            "number": number,
            "occurrences": occurrences[number],
            "heat_score": score,
            "position": POSITION_MAP[number]
        }
        for rank, (number, score) in enumerate(sorted_scores[:10], 1)
    ],
    "all_scores": {str(k): v for k, v in sorted_scores}
}

with open("hot_numbers_analysis.json", "w") as f:
    json.dump(results, f, indent=2)

print("\n✅ Resultados salvos em: hot_numbers_analysis.json")
