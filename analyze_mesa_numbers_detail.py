#!/usr/bin/env python3
"""
Análise detalhada número a número
Números da mesa: 9, 25, 14, 15, 8
"""

import json
from collections import defaultdict

# Carregar dados
with open("pragmatic_auto_roulette_500_numbers.json", "r") as f:
    data = json.load(f)

numbers = [item['value'] for item in data]

# Lista da mesa
MESA_LIST = [9, 25, 14, 15, 8]

print("="*90)
print("ANÁLISE DETALHADA DOS NÚMEROS DA MESA")
print("="*90)

print(f"\n📋 Números analisados: {MESA_LIST}")
print(f"📊 Total de spins: {len(numbers)}\n")

# Análise por número
for target_num in MESA_LIST:
    positions = []
    gaps = []

    # Encontrar todas as posições do número
    for idx, num in enumerate(numbers):
        if num == target_num:
            positions.append(idx)

    # Calcular gaps entre ocorrências
    for i in range(1, len(positions)):
        gap = positions[i] - positions[i-1]
        gaps.append(gap)

    count = len(positions)
    frequency_percent = (count / len(numbers)) * 100

    print("="*90)
    print(f"🎯 NÚMERO {target_num}")
    print("="*90)
    print(f"\nOcorrências: {count}x ({frequency_percent:.2f}%)")

    if count > 0:
        print(f"Primeiras 5 posições (spins): {positions[:5]}")
        print(f"Últimas 5 posições (spins): {positions[-5:]}")

        if gaps:
            avg_gap = sum(gaps) / len(gaps)
            min_gap = min(gaps)
            max_gap = max(gaps)

            print(f"\nDistribuição temporal:")
            print(f"  Gap médio entre ocorrências: {avg_gap:.1f} spins")
            print(f"  Gap mínimo (mais próximo): {min_gap} spins")
            print(f"  Gap máximo (mais distante): {max_gap} spins")

            # Analisar clusters
            clusters = []
            current_cluster = [positions[0]]

            for i in range(1, len(positions)):
                if positions[i] - positions[i-1] <= 5:  # cluster se está a 5 ou menos de distância
                    current_cluster.append(positions[i])
                else:
                    if len(current_cluster) > 1:
                        clusters.append(current_cluster)
                    current_cluster = [positions[i]]

            if len(current_cluster) > 1:
                clusters.append(current_cluster)

            if clusters:
                print(f"\n  Clusters (números saindo juntos a cada 5 spins):")
                for cluster_idx, cluster in enumerate(clusters, 1):
                    print(f"    Cluster {cluster_idx}: {len(cluster)} ocorrências em {cluster}")

    print()

# Comparação geral
print("="*90)
print("RANKING DOS NÚMEROS DA MESA")
print("="*90 + "\n")

mesa_counts = {}
for num in MESA_LIST:
    count = numbers.count(num)
    mesa_counts[num] = count

# Ordenar por frequência
sorted_mesa = sorted(mesa_counts.items(), key=lambda x: x[1], reverse=True)

for rank, (num, count) in enumerate(sorted_mesa, 1):
    frequency_percent = (count / len(numbers)) * 100
    bar_length = int(count / 2)
    bar = "█" * bar_length
    print(f"{rank}. Número {num:2d}: {count:2d}x ({frequency_percent:5.2f}%) {bar}")

# Análise comparativa com o resto
print("\n" + "="*90)
print("COMPARAÇÃO COM TODOS OS NÚMEROS")
print("="*90 + "\n")

all_counts = {}
for num in range(37):
    all_counts[num] = numbers.count(num)

sorted_all = sorted(all_counts.items(), key=lambda x: x[1], reverse=True)

print("TOP 10 NÚMEROS MAIS FREQUENTES (incluindo mesa):\n")
for rank, (num, count) in enumerate(sorted_all[:10], 1):
    frequency_percent = (count / len(numbers)) * 100
    in_mesa = "✅" if num in MESA_LIST else "  "
    print(f"{rank:2d}. Número {num:2d}: {count:2d}x ({frequency_percent:5.2f}%) {in_mesa}")

print("\nBOTTOM 10 NÚMEROS MENOS FREQUENTES:\n")
for rank, (num, count) in enumerate(sorted_all[-10:], len(sorted_all)-9):
    frequency_percent = (count / len(numbers)) * 100
    in_mesa = "✅" if num in MESA_LIST else "  "
    print(f"{rank:2d}. Número {num:2d}: {count:2d}x ({frequency_percent:5.2f}%) {in_mesa}")

# Estatísticas gerais
print("\n" + "="*90)
print("ESTATÍSTICAS GERAIS")
print("="*90 + "\n")

all_frequencies = list(all_counts.values())
avg_frequency = sum(all_frequencies) / len(all_frequencies)
mesa_avg_frequency = sum(mesa_counts.values()) / len(mesa_counts)

print(f"Frequência média de todos os números: {avg_frequency:.2f}x")
print(f"Frequência média dos números da mesa: {mesa_avg_frequency:.2f}x")
print(f"Diferença: {mesa_avg_frequency - avg_frequency:+.2f}x")

print(f"\nNúmeros da mesa vs Restante:")
mesa_total = sum(mesa_counts.values())
rest_total = len(numbers) - mesa_total
print(f"  Números da mesa: {mesa_total}x ({(mesa_total/len(numbers)*100):.2f}%)")
print(f"  Restante: {rest_total}x ({(rest_total/len(numbers)*100):.2f}%)")

# Salvar análise
analysis = {
    "mesa_list": MESA_LIST,
    "total_spins": len(numbers),
    "numbers_detail": {
        str(num): {
            "count": mesa_counts[num],
            "frequency_percent": (mesa_counts[num] / len(numbers)) * 100,
            "rank_overall": next(i+1 for i, (n, _) in enumerate(sorted_all) if n == num)
        }
        for num in MESA_LIST
    },
    "ranking": [
        {
            "rank": rank,
            "number": num,
            "count": count,
            "frequency_percent": (count / len(numbers)) * 100
        }
        for rank, (num, count) in enumerate(sorted_mesa, 1)
    ]
}

with open("mesa_numbers_analysis.json", "w") as f:
    json.dump(analysis, f, indent=2)

print("\n✅ Análise detalhada salva em: mesa_numbers_analysis.json")
