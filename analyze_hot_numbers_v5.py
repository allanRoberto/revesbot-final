#!/usr/bin/env python3
"""
Análise com 5 vizinhos
Progressão completa: 1 → 2 → 3 → 4 → 5 vizinhos
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
            score_multiplier = 1.0 - (distance * 0.2)  # dist 1: 0.8, dist 2: 0.6, dist 3: 0.4, dist 4: 0.2, dist 5: 0.0

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
print("ANÁLISE PROGRESSIVA: 1 → 2 → 3 → 4 → 5 VIZINHOS")
print("="*80)

print(f"\n📋 Lista da Mesa: {MESA_LIST}\n")

# Calcular com diferentes distâncias
results_by_distance = {}

for distance in [1, 2, 3, 4, 5]:
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
        'occurrences': dict(occurrences),
        'sorted_scores': sorted_scores
    }

# Tabela de comparação
print("COMPARAÇÃO PROGRESSIVA POR NÚMERO DE VIZINHOS:")
print("-" * 100)
print(f"{'Vizinhos':<12} {'Top 5':<35} {'Matches':<20} {'Acurácia':<12}")
print("-" * 100)

for distance in [1, 2, 3, 4, 5]:
    result = results_by_distance[distance]
    top_5_str = str(result['top_5'])
    matches_str = str(result['matches'])
    accuracy_str = f"{result['accuracy']:.0f}%"

    print(f"{distance:<12} {top_5_str:<35} {matches_str:<20} {accuracy_str:<12}")

# Detalhe com 5 vizinhos
print("\n" + "="*80)
print("DETALHES COM 5 VIZINHOS")
print("="*80)

heat_scores_v5, occurrences = calculate_heat_score(numbers, neighbor_distance=5)
sorted_scores_v5 = results_by_distance[5]['sorted_scores']

print(f"\nTop 5 do Algoritmo (5 vizinhos): {[num for num, _ in sorted_scores_v5[:5]]}\n")

for rank, (number, score) in enumerate(sorted_scores_v5[:5], 1):
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

# Ranking da lista da mesa com 5 vizinhos
print("="*80)
print("POSIÇÃO DOS NÚMEROS DA MESA (com 5 vizinhos)")
print("="*80 + "\n")

mesa_rankings = []
for num in MESA_LIST:
    score = heat_scores_v5[num]
    rank = next((i+1 for i, (n, _) in enumerate(sorted_scores_v5) if n == num), None)
    occ = occurrences[num]
    mesa_rankings.append((num, rank, score, occ))

mesa_rankings.sort(key=lambda x: x[1])

for num, rank, score, occ in mesa_rankings:
    if rank <= 5:
        badge = "🔴"
    elif rank <= 10:
        badge = "🟡"
    elif rank <= 15:
        badge = "🟠"
    else:
        badge = "⚪"

    print(f"{badge} Número {num}: #{rank:2d} | Score: {score:6.2f} | Ocorrências: {occ}x")

# Análise final
print("\n" + "="*80)
print("ANÁLISE COMPARATIVA (1 a 5 vizinhos)")
print("="*80)

top_5_v5 = [num for num, _ in sorted_scores_v5[:5]]
matches_v5 = [num for num in MESA_LIST if num in top_5_v5]
accuracy_v5 = (len(matches_v5) / len(MESA_LIST)) * 100

print(f"\nAcurácia por número de vizinhos:")
for distance in [1, 2, 3, 4, 5]:
    acc = results_by_distance[distance]['accuracy']
    matches = results_by_distance[distance]['matches']
    marker = "←" if distance == 5 else ""
    print(f"  {distance} vizinho(s): {acc:.0f}% → {matches} {marker}")

# TOP 10 com 5 vizinhos
print("\n" + "="*80)
print("TOP 15 COMPLETO (com 5 vizinhos)")
print("="*80 + "\n")

for rank, (number, score) in enumerate(sorted_scores_v5[:15], 1):
    occ = occurrences[number]
    in_mesa = "✅" if number in MESA_LIST else "  "
    print(f"{rank:2d}. Número {number:2d} → Ocorrências: {occ:2d} | Score: {score:6.2f} {in_mesa}")

# Gráfico visual de progresso
print("\n" + "="*80)
print("VISUALIZAÇÃO DE PROGRESSO DOS NÚMEROS DA MESA")
print("="*80 + "\n")

print("Ranking por número de vizinhos:\n")

for num in MESA_LIST:
    positions = []
    for distance in [1, 2, 3, 4, 5]:
        rank = next((i+1 for i, (n, _) in enumerate(results_by_distance[distance]['sorted_scores']) if n == num), None)
        positions.append(rank)

    # Criar gráfico de linha
    print(f"Número {num:2d}: ", end="")
    for distance, rank in enumerate(positions, 1):
        if rank <= 5:
            print(f"🔴#{rank} ", end="")
        elif rank <= 10:
            print(f"🟡#{rank} ", end="")
        elif rank <= 15:
            print(f"🟠#{rank} ", end="")
        else:
            print(f"⚪#{rank} ", end="")
    print()

# Salvar comparação
with open("progressive_analysis_5neighbors.json", "w") as f:
    comparison = {
        "mesa_list": MESA_LIST,
        "analysis": {
            f"{i}_neighbors": {
                "top_5": results_by_distance[i]['top_5'],
                "matches": results_by_distance[i]['matches'],
                "accuracy": results_by_distance[i]['accuracy']
            }
            for i in [1, 2, 3, 4, 5]
        }
    }
    json.dump(comparison, f, indent=2)

print("\n✅ Análise progressiva (1-5 vizinhos) salva em: progressive_analysis_5neighbors.json")
