#!/usr/bin/env python3
"""
Ranking dos últimos 500 números
"""

import json

# Carregar os dados dos últimos 500 números
with open("pragmatic_auto_roulette_next_500.json", "r") as f:
    data = json.load(f)

numbers = [item['value'] for item in data]

print("="*80)
print("RANKING DOS ÚLTIMOS 500 NÚMEROS")
print("="*80 + "\n")

# Contar frequência
frequency = {}
for num in range(37):
    frequency[num] = numbers.count(num)

# Ordenar
ranked = sorted(frequency.items(), key=lambda x: x[1], reverse=True)

print(f"{'Rank':<6} {'Número':<10} {'Saídas':<15} {'%':<10}")
print("-" * 80)

for rank, (num, count) in enumerate(ranked, 1):
    percentage = (count / len(numbers)) * 100
    bar = "█" * int(count / 1.5)
    print(f"{rank:<6} {num:<10} {count:<15} {percentage:>6.2f}%  {bar}")
