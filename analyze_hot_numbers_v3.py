#!/usr/bin/env python3
"""
Análise com apenas 1 vizinho (distância 1)
Comparação progressiva: 3 vizinhos → 2 vizinhos → 1 vizinho
"""

import json
from collections import defaultdict

# Sequência física da roleta europeia
ROULETTE_SEQUENCE = [
    0, 26, 3, 35, 12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16, 24, 5, 10,
    23, 8, 30, 11, 36, 13, 27, 6, 34, 17, 25, 2, 21, 4, 19, 15, 32
]

POSITION_MAP = {num: idx for idx, num in enumerate(ROULETTE_SEQUENCE)}

def calculate_heat_score(numbers, neighbor_distance=1):
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

# Lista da mesa
MESA_LIST = [9, 25, 14, 15, 8]

print("="*80)
print("ANÁLISE PROGRESSIVA: 3 vs 2 vs 1 VIZINHO")
print("="*80)

print(f"\n📋 Lista da Mesa: {MESA_LIST}\n")

# Calcular com diferentes distâncias
results_by_distance = {}

for distance in [3, 2, 1]:
    heat_scores, occurrences = calculate_heat_score(numbers, neighbor_distance=distance)
    sorted_scores = sorted(heat_scores.items(), key=lambda x: x[1], reverse=True)

    top_5 = [num for num, _ in sorted_scores[:5]]
    matches = [num for num in MESA_LIST if num in top_5]
    accuracy = (len(matches) / len(MESA_LIST)) * 100

    results_by_distance[distance] = {
        'top_5': top_5,
        'matches': matches,
        'accuracy': accuracy,
        'scores': dict(sorted_scores),
        'occurrences': dict(occurrences)
    }

# Comparação visual
print("COMPARAÇÃO POR DISTÂNCIA:")
print("-" * 80)

for distance in [3, 2, 1]:
    result = results_by_distance[distance]
    matches = result['matches']
    accuracy = result['accuracy']
    status = "✅" if accuracy >= 60 else "🟡" if accuracy >= 40 else "⚠️"

    print(f"\n{status} Com {distance} vizinho(s):")
    print(f"   Top 5: {result['top_5']}")
    print(f"   Combinações: {matches} ({accuracy:.0f}%)")

# Detalhe com 1 vizinho
print("\n" + "="*80)
print("DETALHES COM 1 VIZINHO (Proposta Final)")
print("="*80)

heat_scores_v1, occurrences = calculate_heat_score(numbers, neighbor_distance=1)
sorted_scores_v1 = sorted(heat_scores_v1.items(), key=lambda x: x[1], reverse=True)

print(f"\nTop 5 do Algoritmo (1 vizinho): {[num for num, _ in sorted_scores_v1[:5]]}\n")

for rank, (number, score) in enumerate(sorted_scores_v1[:5], 1):
    pos = POSITION_MAP[number]
    occ = occurrences[number]
    left_neighbor = ROULETTE_SEQUENCE[(pos - 1) % 37]
    right_neighbor = ROULETTE_SEQUENCE[(pos + 1) % 37]
    in_mesa = "✅ NA LISTA DA MESA" if number in MESA_LIST else "❌"

    print(f"#{rank} - Número: {number}")
    print(f"   Vizinhos diretos: {left_neighbor} ← {number} → {right_neighbor}")
    print(f"   Ocorrências: {occ}x")
    print(f"   Score: {score:.2f}")
    print(f"   {in_mesa}\n")

# Ranking da lista da mesa com 1 vizinho
print("="*80)
print("POSIÇÃO DOS NÚMEROS DA MESA (com 1 vizinho)")
print("="*80 + "\n")

mesa_rankings = []
for num in MESA_LIST:
    score = heat_scores_v1[num]
    rank = next((i+1 for i, (n, _) in enumerate(sorted_scores_v1) if n == num), None)
    occ = occurrences[num]
    mesa_rankings.append((num, rank, score, occ))

mesa_rankings.sort(key=lambda x: x[1])

for num, rank, score, occ in mesa_rankings:
    badge = "🔴" if rank <= 5 else "🟡" if rank <= 10 else "⚪"
    print(f"{badge} Número {num}: #{rank} | Score: {score:.2f} | Ocorrências: {occ}x")

# Análise final
print("\n" + "="*80)
print("ANÁLISE FINAL")
print("="*80)

top_5_v1 = [num for num, _ in sorted_scores_v1[:5]]
matches_v1 = [num for num in MESA_LIST if num in top_5_v1]
accuracy_v1 = (len(matches_v1) / len(MESA_LIST)) * 100

print(f"\nCom 1 vizinho: {accuracy_v1:.0f}% de alinhamento ({len(matches_v1)}/5)")
print(f"Números na lista que ENTRARAM no top 5: {matches_v1}")
print(f"Números na lista que saíram do top 5: {[n for n in MESA_LIST if n not in top_5_v1]}")

# Comparação com 2 vizinhos (anterior)
prev_result = results_by_distance[2]
print(f"\nComparação:")
print(f"  3 vizinhos: {prev_result['accuracy']:.0f}%")
print(f"  2 vizinhos: {results_by_distance[2]['accuracy']:.0f}%")
print(f"  1 vizinho:  {accuracy_v1:.0f}%")

if accuracy_v1 > results_by_distance[2]['accuracy']:
    print(f"\n✅ 1 vizinho melhorou em {accuracy_v1 - results_by_distance[2]['accuracy']:.0f}%")
elif accuracy_v1 < results_by_distance[2]['accuracy']:
    print(f"\n⚠️ 1 vizinho piorou em {results_by_distance[2]['accuracy'] - accuracy_v1:.0f}%")
else:
    print(f"\n🔄 Sem diferença")

# Salvar comparação
with open("progressive_analysis.json", "w") as f:
    comparison = {
        "mesa_list": MESA_LIST,
        "analysis": {
            "3_neighbors": {
                "top_5": results_by_distance[3]['top_5'],
                "matches": results_by_distance[3]['matches'],
                "accuracy": results_by_distance[3]['accuracy']
            },
            "2_neighbors": {
                "top_5": results_by_distance[2]['top_5'],
                "matches": results_by_distance[2]['matches'],
                "accuracy": results_by_distance[2]['accuracy']
            },
            "1_neighbor": {
                "top_5": top_5_v1,
                "matches": matches_v1,
                "accuracy": accuracy_v1
            }
        }
    }
    json.dump(comparison, f, indent=2)

print("\n✅ Análise progressiva salva em: progressive_analysis.json")
