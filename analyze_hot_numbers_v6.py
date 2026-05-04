#!/usr/bin/env python3
"""
Análise com 6 vizinhos com ÊNFASE em vizinhos próximos
Usar curva exponencial de decaimento para favorecer vizinhos imediatos
"""

import json
from collections import defaultdict

# Sequência física da roleta europeia
ROULETTE_SEQUENCE = [
    0, 26, 3, 35, 12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16, 24, 5, 10,
    23, 8, 30, 11, 36, 13, 27, 6, 34, 17, 25, 2, 21, 4, 19, 15, 32
]

POSITION_MAP = {num: idx for idx, num in enumerate(ROULETTE_SEQUENCE)}

def calculate_heat_score_exponential(numbers, neighbor_distance=6):
    """
    Calcula pontuação com ênfase em vizinhos próximos
    Usa curva exponencial (0.9^distance) para dar mais peso aos vizinhos imediatos
    """
    heat_scores = defaultdict(float)
    occurrences = defaultdict(int)

    # Contar ocorrências
    for num in numbers:
        occurrences[num] += 1

    # Dar pontos para cada ocorrência do número em si
    for num, count in occurrences.items():
        heat_scores[num] += count * 1.0

    # Dar pontos para vizinhos baseado na distância (exponencial)
    for num, count in occurrences.items():
        pos = POSITION_MAP[num]

        for distance in range(1, neighbor_distance + 1):
            # Vizinhos à esquerda e direita
            left_pos = (pos - distance) % 37
            right_pos = (pos + distance) % 37

            left_neighbor = ROULETTE_SEQUENCE[left_pos]
            right_neighbor = ROULETTE_SEQUENCE[right_pos]

            # Score com decaimento exponencial (favorece vizinhos próximos)
            # 0.9^1 = 0.9, 0.9^2 = 0.81, 0.9^3 = 0.729, etc
            score_multiplier = 0.9 ** distance

            heat_scores[left_neighbor] += count * score_multiplier
            heat_scores[right_neighbor] += count * score_multiplier

    return heat_scores, occurrences

def calculate_heat_score_linear(numbers, neighbor_distance=6):
    """Versão linear para comparação"""
    heat_scores = defaultdict(float)
    occurrences = defaultdict(int)

    for num in numbers:
        occurrences[num] += 1

    for num, count in occurrences.items():
        heat_scores[num] += count * 1.0

    for num, count in occurrences.items():
        pos = POSITION_MAP[num]

        for distance in range(1, neighbor_distance + 1):
            left_pos = (pos - distance) % 37
            right_pos = (pos + distance) % 37

            left_neighbor = ROULETTE_SEQUENCE[left_pos]
            right_neighbor = ROULETTE_SEQUENCE[right_pos]

            score_multiplier = 1.0 - (distance * 0.2)

            heat_scores[left_neighbor] += count * score_multiplier
            heat_scores[right_neighbor] += count * score_multiplier

    return heat_scores, occurrences

# Carregar dados
with open("pragmatic_auto_roulette_500_numbers.json", "r") as f:
    data = json.load(f)

numbers = [item['value'] for item in data]

# Lista da mesa
MESA_LIST = [9, 25, 14, 15, 8]

print("="*90)
print("ANÁLISE COM 6 VIZINHOS: LINEAR vs EXPONENCIAL (com ênfase em próximos)")
print("="*90)

print(f"\n📋 Lista da Mesa: {MESA_LIST}\n")

# Calcular com 6 vizinhos - ambas as estratégias
heat_scores_linear, occurrences = calculate_heat_score_linear(numbers, neighbor_distance=6)
heat_scores_exp, _ = calculate_heat_score_exponential(numbers, neighbor_distance=6)

sorted_scores_linear = sorted(heat_scores_linear.items(), key=lambda x: x[1], reverse=True)
sorted_scores_exp = sorted(heat_scores_exp.items(), key=lambda x: x[1], reverse=True)

top_5_linear = [num for num, _ in sorted_scores_linear[:5]]
top_5_exp = [num for num, _ in sorted_scores_exp[:5]]

matches_linear = [num for num in MESA_LIST if num in top_5_linear]
matches_exp = [num for num in MESA_LIST if num in top_5_exp]

accuracy_linear = (len(matches_linear) / len(MESA_LIST)) * 100
accuracy_exp = (len(matches_exp) / len(MESA_LIST)) * 100

# Comparação visual
print("COMPARAÇÃO DE ESTRATÉGIAS:")
print("-" * 90)
print(f"\n📊 LINEAR (0.8, 0.6, 0.4, 0.2, 0.0, -0.2):")
print(f"   Top 5: {top_5_linear}")
print(f"   Matches: {matches_linear} ({accuracy_linear:.0f}%)")

print(f"\n📈 EXPONENCIAL (0.9^distance - ÊNFASE EM PRÓXIMOS):")
print(f"   Top 5: {top_5_exp}")
print(f"   Matches: {matches_exp} ({accuracy_exp:.0f}%)")

# Detalhe com exponencial (6 vizinhos)
print("\n" + "="*90)
print("DETALHES COM 6 VIZINHOS (EXPONENCIAL - COM ÊNFASE EM PRÓXIMOS)")
print("="*90)

print(f"\nMultiplicadores de score exponencial:")
for d in range(1, 7):
    print(f"  Distância {d}: {0.9**d:.4f}")

print(f"\nTop 5 do Algoritmo (6 vizinhos exponencial): {top_5_exp}\n")

for rank, (number, score) in enumerate(sorted_scores_exp[:5], 1):
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

# Ranking da lista da mesa
print("="*90)
print("POSIÇÃO DOS NÚMEROS DA MESA (com 6 vizinhos exponencial)")
print("="*90 + "\n")

mesa_rankings_exp = []
mesa_rankings_linear = []

for num in MESA_LIST:
    score_exp = heat_scores_exp[num]
    score_linear = heat_scores_linear[num]

    rank_exp = next((i+1 for i, (n, _) in enumerate(sorted_scores_exp) if n == num), None)
    rank_linear = next((i+1 for i, (n, _) in enumerate(sorted_scores_linear) if n == num), None)

    occ = occurrences[num]
    mesa_rankings_exp.append((num, rank_exp, score_exp, occ))
    mesa_rankings_linear.append((num, rank_linear, score_linear, occ))

mesa_rankings_exp.sort(key=lambda x: x[1])
mesa_rankings_linear.sort(key=lambda x: x[1])

print("EXPONENCIAL (com ênfase em próximos):\n")
for num, rank, score, occ in mesa_rankings_exp:
    if rank <= 5:
        badge = "🔴"
    elif rank <= 10:
        badge = "🟡"
    elif rank <= 15:
        badge = "🟠"
    else:
        badge = "⚪"
    print(f"{badge} Número {num}: #{rank:2d} | Score: {score:6.2f} | Ocorrências: {occ}x")

print("\n" + "-"*90)
print("LINEAR (para comparação):\n")
for num, rank, score, occ in mesa_rankings_linear:
    if rank <= 5:
        badge = "🔴"
    elif rank <= 10:
        badge = "🟡"
    elif rank <= 15:
        badge = "🟠"
    else:
        badge = "⚪"
    print(f"{badge} Número {num}: #{rank:2d} | Score: {score:6.2f} | Ocorrências: {occ}x")

# TOP 15 com exponencial
print("\n" + "="*90)
print("TOP 15 COMPLETO (6 vizinhos exponencial)")
print("="*90 + "\n")

for rank, (number, score) in enumerate(sorted_scores_exp[:15], 1):
    occ = occurrences[number]
    in_mesa = "✅" if number in MESA_LIST else "  "
    print(f"{rank:2d}. Número {number:2d} → Ocorrências: {occ:2d} | Score: {score:6.2f} {in_mesa}")

# Análise final
print("\n" + "="*90)
print("ANÁLISE FINAL")
print("="*90)

if accuracy_exp > accuracy_linear:
    print(f"\n✅ EXPONENCIAL É MELHOR! {accuracy_exp:.0f}% vs {accuracy_linear:.0f}%")
    improvement = accuracy_exp - accuracy_linear
    print(f"   Melhoria: +{improvement:.0f}% ({len(matches_exp)}/{len(MESA_LIST)} números)")
elif accuracy_exp < accuracy_linear:
    print(f"\n⚠️ LINEAR É MELHOR. {accuracy_linear:.0f}% vs {accuracy_exp:.0f}%")
    diff = accuracy_linear - accuracy_exp
    print(f"   Diferença: -{diff:.0f}%")
else:
    print(f"\n🔄 EMPATE! Ambos com {accuracy_exp:.0f}%")

# Salvar comparação
with open("analysis_6neighbors_exponential.json", "w") as f:
    comparison = {
        "mesa_list": MESA_LIST,
        "strategies": {
            "linear_6neighbors": {
                "top_5": top_5_linear,
                "matches": matches_linear,
                "accuracy": accuracy_linear
            },
            "exponential_6neighbors": {
                "top_5": top_5_exp,
                "matches": matches_exp,
                "accuracy": accuracy_exp
            }
        }
    }
    json.dump(comparison, f, indent=2)

print("\n✅ Análise salva em: analysis_6neighbors_exponential.json")
