#!/usr/bin/env python3
"""
Comparação entre os dois períodos de 500 números
"""

import json

# Carregar os dados
with open("pragmatic_auto_roulette_first_500.json", "r") as f:
    first_500_data = json.load(f)

with open("pragmatic_auto_roulette_next_500.json", "r") as f:
    next_500_data = json.load(f)

first_500_values = [item['value'] for item in first_500_data]
next_500_values = [item['value'] for item in next_500_data]

# Lista da mesa
MESA_LIST = [9, 25, 14, 15, 8]

print("="*100)
print("COMPARAÇÃO: PERÍODO 1 vs PERÍODO 2 (500 números cada)")
print("="*100 + "\n")

# Calcular frequências
freq_p1 = {}
freq_p2 = {}
for num in range(37):
    freq_p1[num] = first_500_values.count(num)
    freq_p2[num] = next_500_values.count(num)

# Ordenar
ranked_p1 = sorted(freq_p1.items(), key=lambda x: x[1], reverse=True)
ranked_p2 = sorted(freq_p2.items(), key=lambda x: x[1], reverse=True)

# Mostrar TOP 10 de cada período
print("PERÍODO 1 (Primeiros 500 spins):")
print("-" * 100)
print(f"{'Rank':<6} {'Número':<10} {'Saídas':<15} {'%':<10} {'Status':<15}")
print("-" * 100)

for rank, (num, count) in enumerate(ranked_p1[:10], 1):
    percentage = (count / len(first_500_values)) * 100
    in_mesa = "✅ MESA" if num in MESA_LIST else ""
    bar = "█" * int(count / 2)
    print(f"{rank:<6} {num:<10} {count:<15} {percentage:>6.2f}%  {in_mesa:<15} {bar}")

print("\n\nPERÍODO 2 (Próximos 500 spins):")
print("-" * 100)
print(f"{'Rank':<6} {'Número':<10} {'Saídas':<15} {'%':<10} {'Status':<15}")
print("-" * 100)

for rank, (num, count) in enumerate(ranked_p2[:10], 1):
    percentage = (count / len(next_500_values)) * 100
    in_mesa = "✅ MESA" if num in MESA_LIST else ""
    bar = "█" * int(count / 2)
    print(f"{rank:<6} {num:<10} {count:<15} {percentage:>6.2f}%  {in_mesa:<15} {bar}")

# Comparação da mesa
print("\n\n" + "="*100)
print("RANKING DOS NÚMEROS DA MESA (Comparação entre períodos)")
print("="*100 + "\n")

print(f"{'Número':<10} {'Período 1':<20} {'Período 2':<20} {'Variação':<15}")
print("-" * 100)

mesa_comparison = []
for num in MESA_LIST:
    rank_p1 = next((i+1 for i, (n, _) in enumerate(ranked_p1) if n == num), None)
    rank_p2 = next((i+1 for i, (n, _) in enumerate(ranked_p2) if n == num), None)
    count_p1 = freq_p1[num]
    count_p2 = freq_p2[num]
    variation = count_p2 - count_p1

    mesa_comparison.append({
        'number': num,
        'rank_p1': rank_p1,
        'rank_p2': rank_p2,
        'count_p1': count_p1,
        'count_p2': count_p2,
        'variation': variation
    })

# Ordenar por aparições no período 2
mesa_comparison.sort(key=lambda x: x['count_p2'], reverse=True)

for item in mesa_comparison:
    num = item['number']
    rank_p1 = item['rank_p1']
    rank_p2 = item['rank_p2']
    count_p1 = item['count_p1']
    count_p2 = item['count_p2']
    variation = item['variation']

    var_symbol = "📈" if variation > 0 else "📉" if variation < 0 else "➡️"

    print(f"{num:<10} #{rank_p1:2d} ({count_p1}x)        #{rank_p2:2d} ({count_p2}x)        {var_symbol} {variation:+d}x")

# Análise de tendência
print("\n\n" + "="*100)
print("ANÁLISE DE TENDÊNCIA")
print("="*100 + "\n")

print("Números que SUBIRAM de popularidade (Período 1 → Período 2):")
gainers = sorted(mesa_comparison, key=lambda x: x['variation'], reverse=True)
for item in gainers:
    if item['variation'] > 0:
        print(f"  • Número {item['number']}: +{item['variation']}x ({item['count_p1']}x → {item['count_p2']}x)")

print("\nNúmeros que CAÍRAM de popularidade (Período 1 → Período 2):")
losers = sorted(mesa_comparison, key=lambda x: x['variation'])
for item in losers:
    if item['variation'] < 0:
        print(f"  • Número {item['number']}: {item['variation']}x ({item['count_p1']}x → {item['count_p2']}x)")

# TOP 5 de cada período
print("\n\n" + "="*100)
print("TOP 5 COMPARADO")
print("="*100 + "\n")

top_5_p1 = [num for num, _ in ranked_p1[:5]]
top_5_p2 = [num for num, _ in ranked_p2[:5]]

print(f"Período 1: {top_5_p1}")
print(f"Período 2: {top_5_p2}")

matches = set(top_5_p1) & set(top_5_p2)
print(f"\nNúmeros que se repetem no top 5: {sorted(matches)} ({len(matches)}/5)")

only_p1 = set(top_5_p1) - set(top_5_p2)
only_p2 = set(top_5_p2) - set(top_5_p1)

if only_p1:
    print(f"Saíram do top 5: {sorted(only_p1)}")
if only_p2:
    print(f"Entraram no top 5: {sorted(only_p2)}")

# Salvar comparação
with open("comparison_two_periods.json", "w") as f:
    comparison = {
        "period_1": {
            "timestamp_start": first_500_data[0]['timestamp'],
            "timestamp_end": first_500_data[-1]['timestamp'],
            "total_spins": len(first_500_values),
            "top_5": top_5_p1,
            "mesa_numbers": {
                str(item['number']): {
                    "rank": item['rank_p1'],
                    "frequency": item['count_p1']
                }
                for item in mesa_comparison
            }
        },
        "period_2": {
            "timestamp_start": next_500_data[0]['timestamp'],
            "timestamp_end": next_500_data[-1]['timestamp'],
            "total_spins": len(next_500_values),
            "top_5": top_5_p2,
            "mesa_numbers": {
                str(item['number']): {
                    "rank": item['rank_p2'],
                    "frequency": item['count_p2']
                }
                for item in mesa_comparison
            }
        }
    }
    json.dump(comparison, f, indent=2, default=str)

print("\n\n✅ Comparação salva em: comparison_two_periods.json")
