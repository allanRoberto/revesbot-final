#!/usr/bin/env python3
"""
Ranking sem considerar vizinhos dos números que mais saíram
Identifica números realmente frequentes vs números que aparecem apenas
porque estão perto de frequentes
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
    """Retorna vizinhos de um número até a distância especificada"""
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

# Lista da mesa
MESA_LIST = [9, 25, 14, 15, 8]

print("="*100)
print("RANKING SEM CONSIDERAR VIZINHOS DOS NÚMEROS MAIS FREQUENTES")
print("="*100)

# Passo 1: Contar frequência de cada número
all_counts = {}
for num in range(37):
    all_counts[num] = numbers.count(num)

# Passo 2: Identificar números "puros" (frequentes por si mesmos)
# Vamos usar diferentes definições de "vizinho próximo"

for neighbor_distance in [1, 2, 3]:
    print(f"\n{'='*100}")
    print(f"ANÁLISE: Excluindo vizinhos até {neighbor_distance} posição(ões) de cada lado")
    print(f"{'='*100}\n")

    # Identificar os 10 números mais frequentes
    sorted_by_freq = sorted(all_counts.items(), key=lambda x: x[1], reverse=True)
    top_frequent = [num for num, _ in sorted_by_freq[:10]]

    # Coletar todos os vizinhos dos números frequentes
    excluded_numbers = set()
    for num in top_frequent:
        neighbors = get_neighbors(num, distance=neighbor_distance)
        excluded_numbers.update(neighbors)

    # Criar ranking apenas dos números que NÃO são vizinhos dos frequentes
    pure_numbers = {}
    for num in range(37):
        if num not in top_frequent and num not in excluded_numbers:
            pure_numbers[num] = all_counts[num]

    # Ordenar por frequência
    sorted_pure = sorted(pure_numbers.items(), key=lambda x: x[1], reverse=True)

    print(f"Top 10 mais frequentes (a excluir e seus vizinhos): {top_frequent}")
    print(f"Total de números excluídos (incluindo vizinhos): {len(excluded_numbers)}")
    print(f"Números restantes para análise (puros): {len(pure_numbers)}\n")

    print(f"TOP 10 'NÚMEROS PUROS' (sem vizinhos de frequentes):\n")
    for rank, (num, count) in enumerate(sorted_pure[:10], 1):
        frequency_percent = (count / len(numbers)) * 100
        in_mesa = "✅" if num in MESA_LIST else "  "
        print(f"{rank:2d}. Número {num:2d}: {count:2d}x ({frequency_percent:5.2f}%) {in_mesa}")

    # Ranking da mesa nessa análise
    print(f"\nPosição dos números da mesa:")
    mesa_in_pure = {}
    for num in MESA_LIST:
        if num in pure_numbers:
            count = pure_numbers[num]
            rank = next((i+1 for i, (n, _) in enumerate(sorted_pure) if n == num), None)
            mesa_in_pure[num] = (rank, count)

    if mesa_in_pure:
        for num in sorted(mesa_in_pure.keys()):
            rank, count = mesa_in_pure[num]
            print(f"  Número {num}: #{rank} ({count}x)")
    else:
        print(f"  Todos os números da mesa são frequentes ou vizinhos de frequentes!")

# Agora fazer análise INVERSA: mostrar quais números aparecem PORQUE são vizinhos de frequentes
print(f"\n{'='*100}")
print(f"ANÁLISE INVERSA: Números que aparecem PRINCIPALMENTE como vizinhos")
print(f"{'='*100}\n")

# Passo 3: Análise inversa
sorted_by_freq = sorted(all_counts.items(), key=lambda x: x[1], reverse=True)
top_frequent_core = [num for num, _ in sorted_by_freq[:5]]  # Top 5 reais

# Vizinhos dos top 5
neighbor_impact = {}
for num in range(37):
    if num not in top_frequent_core:
        # Contar quantas vezes esse número é vizinho de um frequente
        neighbor_count = 0
        for freq_num in top_frequent_core:
            if num in get_neighbors(freq_num, distance=2):
                neighbor_count += 1

        if neighbor_count > 0:
            direct_count = all_counts[num]
            neighbor_impact[num] = {
                'direct': direct_count,
                'neighbor_of_how_many': neighbor_count,
                'is_direct': direct_count > 0
            }

sorted_by_neighbor = sorted(neighbor_impact.items(), key=lambda x: x[1]['neighbor_of_how_many'], reverse=True)

print(f"Top 5 frequentes (core): {top_frequent_core}")
print(f"\nNúmeros que aparecem MAIS como vizinhos:\n")

for rank, (num, impact) in enumerate(sorted_by_neighbor[:10], 1):
    direct = impact['direct']
    neighbor_of = impact['neighbor_of_how_many']
    in_mesa = "✅" if num in MESA_LIST else "  "
    print(f"{rank:2d}. Número {num:2d}: {direct}x direto | Vizinho de {neighbor_of} número(s) frequente(s) {in_mesa}")

# Padrão especial: números da mesa
print(f"\n{'='*100}")
print(f"PADRÃO DOS NÚMEROS DA MESA")
print(f"{'='*100}\n")

for num in MESA_LIST:
    count = all_counts[num]
    rank_overall = next((i+1 for i, (n, _) in enumerate(sorted_by_freq) if n == num), None)

    # Verificar se é vizinho de algo mais frequente
    is_neighbor_of = []
    for freq_num in top_frequent_core:
        if num in get_neighbors(freq_num, distance=2) and num != freq_num:
            is_neighbor_of.append(freq_num)

    print(f"Número {num}:")
    print(f"  Frequência: {count}x")
    print(f"  Rank geral: #{rank_overall}")
    if is_neighbor_of:
        print(f"  É vizinho de: {is_neighbor_of}")
    else:
        print(f"  É independente (não é vizinho de frequentes)")
    print()

# Salvar análise
with open("pure_numbers_analysis.json", "w") as f:
    analysis = {
        "all_frequencies": all_counts,
        "top_5_frequent": top_frequent_core,
        "mesa_list": MESA_LIST,
        "mesa_details": {
            str(num): {
                "frequency": all_counts[num],
                "overall_rank": next(i+1 for i, (n, _) in enumerate(sorted_by_freq) if n == num)
            }
            for num in MESA_LIST
        }
    }
    json.dump(analysis, f, indent=2)

print("✅ Análise de números puros salva em: pure_numbers_analysis.json")
