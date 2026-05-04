#!/usr/bin/env python3
"""
Análise de assertividade: quando sai número quente (top 5),
qual é a probabilidade do próximo ser outro quente ou vizinho de algum quente?
"""

import json
from collections import defaultdict

# Sequência física da roleta europeia
ROULETTE_SEQUENCE = [
    0, 26, 3, 35, 12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16, 24, 5, 10,
    23, 8, 30, 11, 36, 13, 27, 6, 34, 17, 25, 2, 21, 4, 19, 15, 32
]

POSITION_MAP = {num: idx for idx, num in enumerate(ROULETTE_SEQUENCE)}

def get_neighbors(number, distance=1):
    """Retorna vizinhos de um número"""
    pos = POSITION_MAP[number]
    neighbors = set()
    for d in range(1, distance + 1):
        left_pos = (pos - d) % 37
        right_pos = (pos + d) % 37
        neighbors.add(ROULETTE_SEQUENCE[left_pos])
        neighbors.add(ROULETTE_SEQUENCE[right_pos])
    return neighbors

# Carregar dados
with open("pragmatic_auto_roulette_500_numbers.json", "r") as f:
    data = json.load(f)

numbers = [item['value'] for item in data]

# Encontrar top 5
frequency = {}
for num in range(37):
    frequency[num] = numbers.count(num)

ranked = sorted(frequency.items(), key=lambda x: x[1], reverse=True)
TOP_5 = [num for num, _ in ranked[:5]]

print("="*100)
print("ANÁLISE DE ASSERTIVIDADE - NÚMEROS QUENTES PUXAM OUTROS QUENTES")
print("="*100)

print(f"\n📊 TOP 5 Números (Quentes): {TOP_5}")
print(f"Total de spins: {len(numbers)}\n")

# Análise: quando sai número quente, qual é o próximo?
results = {
    'next_is_hot': 0,           # próximo é outro quente (top 5)
    'next_is_neighbor': 0,       # próximo é vizinho de algum quente
    'next_is_hot_and_neighbor': 0, # é quente E vizinho
    'next_is_neither': 0,        # nem quente nem vizinho
    'total_hot_occurrences': 0   # total de vezes que um quente saiu
}

# Coletar todos os vizinhos dos quentes
all_hot_neighbors = set()
for hot_num in TOP_5:
    neighbors = get_neighbors(hot_num, distance=1)
    all_hot_neighbors.update(neighbors)

# Remover os próprios quentes dos vizinhos
all_hot_neighbors = all_hot_neighbors - set(TOP_5)

print(f"Vizinhos diretos dos números quentes (distância 1): {sorted(all_hot_neighbors)}")
print(f"Total de vizinhos: {len(all_hot_neighbors)}\n")

# Analisar sequências
detailed_results = []

for i in range(len(numbers) - 1):
    current = numbers[i]
    next_num = numbers[i + 1]

    # Se o número atual é quente
    if current in TOP_5:
        results['total_hot_occurrences'] += 1

        is_hot = next_num in TOP_5
        is_neighbor = next_num in all_hot_neighbors
        is_both = is_hot and is_neighbor

        if is_both:
            results['next_is_hot_and_neighbor'] += 1
        elif is_hot:
            results['next_is_hot'] += 1
        elif is_neighbor:
            results['next_is_neighbor'] += 1
        else:
            results['next_is_neither'] += 1

        detailed_results.append({
            'current': current,
            'next': next_num,
            'next_is_hot': is_hot,
            'next_is_neighbor': is_neighbor,
            'next_is_both': is_both
        })

# Calcular assertividade
total = results['total_hot_occurrences']
hot_count = results['next_is_hot'] + results['next_is_hot_and_neighbor']
neighbor_count = results['next_is_neighbor']
both_count = results['next_is_hot_and_neighbor']
neither_count = results['next_is_neither']

# Assertividade 1: próximo é quente OU vizinho
assertiveness_1 = ((hot_count + neighbor_count - both_count) / total * 100) if total > 0 else 0

# Assertividade 2: próximo é quente
assertiveness_2 = (hot_count / total * 100) if total > 0 else 0

# Assertividade 3: próximo é vizinho
assertiveness_3 = (neighbor_count / total * 100) if total > 0 else 0

print("="*100)
print("RESULTADOS")
print("="*100 + "\n")

print(f"Total de vezes que um número quente (top 5) saiu: {total}\n")

print(f"Próximo é OUTRO QUENTE (top 5):        {hot_count}x ({hot_count/total*100:5.2f}%)")
print(f"Próximo é VIZINHO de algum quente:    {neighbor_count}x ({neighbor_count/total*100:5.2f}%)")
print(f"Próximo é QUENTE E VIZINHO:            {both_count}x ({both_count/total*100:5.2f}%)")
print(f"Próximo é NENHUM dos dois:             {neither_count}x ({neither_count/total*100:5.2f}%)")

print(f"\n{'='*100}")
print(f"ASSERTIVIDADE (% de chances do próximo ser quente OU vizinho): {assertiveness_1:.2f}%")
print(f"{'='*100}\n")

# Breakdown por número quente
print("="*100)
print("DETALHAMENTO POR NÚMERO QUENTE")
print("="*100 + "\n")

for hot_num in TOP_5:
    hot_occurrences = 0
    next_hot = 0
    next_neighbor = 0
    next_neither = 0

    for i in range(len(numbers) - 1):
        if numbers[i] == hot_num:
            hot_occurrences += 1
            next_num = numbers[i + 1]

            if next_num in TOP_5:
                next_hot += 1
            elif next_num in all_hot_neighbors:
                next_neighbor += 1
            else:
                next_neither += 1

    if hot_occurrences > 0:
        pct_hot = (next_hot / hot_occurrences) * 100
        pct_neighbor = (next_neighbor / hot_occurrences) * 100
        pct_neither = (next_neither / hot_occurrences) * 100
        pct_total = pct_hot + pct_neighbor

        print(f"Número {hot_num}: saiu {hot_occurrences}x")
        print(f"  Próximo foi quente:   {next_hot:2d}x ({pct_hot:5.2f}%)")
        print(f"  Próximo foi vizinho:  {next_neighbor:2d}x ({pct_neighbor:5.2f}%)")
        print(f"  Próximo foi nenhum:   {next_neither:2d}x ({pct_neither:5.2f}%)")
        print(f"  Assertividade (quente OU vizinho): {pct_total:5.2f}%")
        print()

# Salvar análise
analysis = {
    "top_5_hot_numbers": TOP_5,
    "hot_neighbors": sorted(all_hot_neighbors),
    "total_spins": len(numbers),
    "total_hot_occurrences": total,
    "next_is_hot": hot_count,
    "next_is_neighbor": neighbor_count,
    "next_is_both": both_count,
    "next_is_neither": neither_count,
    "assertiveness_hot_or_neighbor": round(assertiveness_1, 2),
    "assertiveness_hot_only": round(assertiveness_2, 2),
    "assertiveness_neighbor_only": round(assertiveness_3, 2)
}

with open("hot_sequence_analysis.json", "w") as f:
    json.dump(analysis, f, indent=2)

print("✅ Análise salva em: hot_sequence_analysis.json")
