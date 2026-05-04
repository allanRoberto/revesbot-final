#!/usr/bin/env python3
"""
Análise com 2 vizinhos (ao invés de 3)
Comparação: Algoritmo vs Lista da Mesa
"""

import json
from collections import defaultdict

# Sequência física da roleta europeia
ROULETTE_SEQUENCE = [
    0, 26, 3, 35, 12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16, 24, 5, 10,
    23, 8, 30, 11, 36, 13, 27, 6, 34, 17, 25, 2, 21, 4, 19, 15, 32
]

POSITION_MAP = {num: idx for idx, num in enumerate(ROULETTE_SEQUENCE)}

def calculate_heat_score_v2(numbers, neighbor_distance=2):
    """Calcula pontuação com distância configurável"""
    heat_scores = defaultdict(float)
    occurrences = defaultdict(int)

    # Contar ocorrências
    for num in numbers:
        occurrences[num] += 1

    # Dar pontos para cada ocorrência do número em si
    for num, count in occurrences.items():
        heat_scores[num] += count * 1.0

    # Dar pontos para vizinhos baseado na distância
    for num, count in occurrences.items():
        pos = POSITION_MAP[num]

        for distance in range(1, neighbor_distance + 1):
            # Vizinhos à esquerda e direita
            left_pos = (pos - distance) % 37
            right_pos = (pos + distance) % 37

            left_neighbor = ROULETTE_SEQUENCE[left_pos]
            right_neighbor = ROULETTE_SEQUENCE[right_pos]

            # Score diminui conforme distância aumenta
            score_multiplier = 1.0 - (distance * 0.2)  # dist 1: 0.8, dist 2: 0.6, dist 3: 0.4

            heat_scores[left_neighbor] += count * score_multiplier
            heat_scores[right_neighbor] += count * score_multiplier

    return heat_scores, occurrences

# Carregar dados
with open("pragmatic_auto_roulette_500_numbers.json", "r") as f:
    data = json.load(f)

numbers = [item['value'] for item in data]

# Lista da mesa (do usuário)
MESA_LIST = [9, 25, 14, 15, 8]

print("="*80)
print("COMPARAÇÃO: ALGORITMO vs LISTA DA MESA")
print("="*80)

print(f"\n📋 Lista da Mesa (extraída diretamente): {MESA_LIST}")

# Calcular com 2 vizinhos
heat_scores_v2, occurrences = calculate_heat_score_v2(numbers, neighbor_distance=2)
sorted_scores_v2 = sorted(heat_scores_v2.items(), key=lambda x: x[1], reverse=True)

print(f"\n🔬 Análise com 2 Vizinhos (ao invés de 3):\n")

top_5_algo = [num for num, _ in sorted_scores_v2[:5]]
print(f"Top 5 do Algoritmo: {top_5_algo}")

print("\nDETALHES DO TOP 5 (com 2 vizinhos):")
print("-" * 80)
for rank, (number, score) in enumerate(sorted_scores_v2[:5], 1):
    pos = POSITION_MAP[number]
    occ = occurrences[number]
    left_neighbor = ROULETTE_SEQUENCE[(pos - 1) % 37]
    right_neighbor = ROULETTE_SEQUENCE[(pos + 1) % 37]
    in_mesa = "✅ NA LISTA DA MESA" if number in MESA_LIST else "❌ Não está na lista"

    print(f"\n#{rank} - Número: {number}")
    print(f"   Vizinhos: {left_neighbor} ← {number} → {right_neighbor}")
    print(f"   Ocorrências diretas: {occ}x")
    print(f"   Pontuação total: {score:.2f}")
    print(f"   Status: {in_mesa}")

# Análise da lista da mesa
print("\n" + "="*80)
print("ANÁLISE DA LISTA DA MESA")
print("="*80)

for num in MESA_LIST:
    score = heat_scores_v2[num]
    occ = occurrences[num]
    pos = POSITION_MAP[num]
    rank = next((i+1 for i, (n, _) in enumerate(sorted_scores_v2) if n == num), None)
    left_neighbor = ROULETTE_SEQUENCE[(pos - 1) % 37]
    right_neighbor = ROULETTE_SEQUENCE[(pos + 1) % 37]

    print(f"\nNúmero {num}:")
    print(f"   Posição no ranking: #{rank}")
    print(f"   Vizinhos: {left_neighbor} ← {num} → {right_neighbor}")
    print(f"   Ocorrências: {occ}x")
    print(f"   Score: {score:.2f}")

# Comparação
print("\n" + "="*80)
print("COMPARAÇÃO FINAL")
print("="*80)

matches = [num for num in MESA_LIST if num in top_5_algo]
accuracy = (len(matches) / len(MESA_LIST)) * 100

print(f"\nNúmeros que combinaram: {len(matches)}/5 ({accuracy:.1f}%)")
print(f"Números que combinaram: {matches if matches else 'Nenhum'}")
print(f"Números da mesa não no top 5: {[n for n in MESA_LIST if n not in top_5_algo]}")

# Ranking da lista da mesa
mesa_rankings = []
for num in MESA_LIST:
    score = heat_scores_v2[num]
    rank = next((i+1 for i, (n, _) in enumerate(sorted_scores_v2) if n == num), None)
    mesa_rankings.append((num, rank, score))

mesa_rankings.sort(key=lambda x: x[1])

print(f"\nRanking dos números da mesa (do melhor ao pior):")
for num, rank, score in mesa_rankings:
    print(f"  • Número {num}: Posição {rank} (Score: {score:.2f})")

print("\n" + "="*80)
print("CONCLUSÃO")
print("="*80)
if accuracy >= 80:
    print(f"✅ Excelente alinhamento! {accuracy:.1f}% dos números da mesa estão no top 5")
elif accuracy >= 60:
    print(f"🟡 Bom alinhamento! {accuracy:.1f}% dos números da mesa estão no top 5")
else:
    print(f"⚠️  Alinhamento parcial. {accuracy:.1f}% dos números da mesa estão no top 5")
    print("   Isso sugere que a mesa pode ter critérios diferentes ou vieses locais")

# Salvar comparação
comparison = {
    "mesa_list": MESA_LIST,
    "algo_top_5": top_5_algo,
    "matches": matches,
    "accuracy_percent": accuracy,
    "mesa_rankings": [
        {"number": num, "rank": rank, "score": score}
        for num, rank, score in mesa_rankings
    ],
    "full_ranking": [
        {"rank": i+1, "number": num, "occurrences": occurrences[num], "score": score}
        for i, (num, score) in enumerate(sorted_scores_v2[:20])
    ]
}

with open("comparison_mesa_vs_algo.json", "w") as f:
    json.dump(comparison, f, indent=2)

print("\n✅ Comparação salva em: comparison_mesa_vs_algo.json")
