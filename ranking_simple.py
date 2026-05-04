#!/usr/bin/env python3
"""
Ranking simples dos 37 números por frequência
Qual número saiu mais vezes nos 500 spins
"""

import json

# Carregar dados
with open("pragmatic_auto_roulette_500_numbers.json", "r") as f:
    data = json.load(f)

numbers = [item['value'] for item in data]

# Lista da mesa
MESA_LIST = [9, 25, 14, 15, 8]

print("="*80)
print("RANKING DOS 37 NÚMEROS POR FREQUÊNCIA (500 SPINS)")
print("="*80 + "\n")

# Contar frequência de cada número
frequency = {}
for num in range(37):
    frequency[num] = numbers.count(num)

# Ordenar por frequência (decrescente)
ranked = sorted(frequency.items(), key=lambda x: x[1], reverse=True)

print(f"{'Rank':<6} {'Número':<10} {'Ocorrências':<15} {'%':<10} {'Status':<15}")
print("-" * 80)

for rank, (num, count) in enumerate(ranked, 1):
    percentage = (count / len(numbers)) * 100
    in_mesa = "✅ MESA" if num in MESA_LIST else ""
    bar = "█" * int(count / 2)

    print(f"{rank:<6} {num:<10} {count:<15} {percentage:>6.2f}%  {in_mesa:<15} {bar}")

# Resumo dos números da mesa
print("\n" + "="*80)
print("RANKING DOS NÚMEROS DA MESA")
print("="*80 + "\n")

mesa_ranks = {}
for num in MESA_LIST:
    for rank, (n, count) in enumerate(ranked, 1):
        if n == num:
            mesa_ranks[num] = (rank, count)

for rank, num in enumerate(sorted(mesa_ranks.keys(), key=lambda x: mesa_ranks[x][0]), 1):
    pos, count = mesa_ranks[num]
    percentage = (count / len(numbers)) * 100
    print(f"{rank}. Número {num:2d}: #{pos:2d} no ranking geral | {count}x ({percentage:.2f}%)")

# Salvar ranking
with open("simple_ranking.json", "w") as f:
    ranking_data = {
        "total_spins": len(numbers),
        "mesa_list": MESA_LIST,
        "all_numbers": [
            {
                "rank": rank,
                "number": num,
                "frequency": count,
                "percentage": round((count / len(numbers)) * 100, 2),
                "in_mesa": num in MESA_LIST
            }
            for rank, (num, count) in enumerate(ranked, 1)
        ]
    }
    json.dump(ranking_data, f, indent=2)

print("\n✅ Ranking salvo em: simple_ranking.json")
