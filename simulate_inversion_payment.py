#!/usr/bin/env python3
"""
ANÁLISE DE PAGAMENTO NA INVERSÃO

Antes do número quente (gatilho) vir, verifica se nos LOOKBACK spins
anteriores houve um vizinho ou outro número quente.

Segmenta os triggers em:
  - INVERSION_HOT: antes do gatilho veio outro QUENTE
  - INVERSION_NEIGHBOR: antes do gatilho veio um VIZINHO
  - NO_INVERSION: nem quente nem vizinho antes do gatilho

Compara o win rate de cada segmento para ver se "pagamento na inversão"
ajuda ou atrapalha a estratégia.
"""

import os
import json
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi

load_dotenv()

ROULETTE_SEQUENCE = [
    0, 26, 3, 35, 12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16, 24, 5, 10,
    23, 8, 30, 11, 36, 13, 27, 6, 34, 17, 25, 2, 21, 4, 19, 15, 32
]
POSITION_MAP = {num: idx for idx, num in enumerate(ROULETTE_SEQUENCE)}

def get_neighbors(number, distance=1):
    pos = POSITION_MAP[number]
    neighbors = []
    for d in range(1, distance + 1):
        neighbors.append(ROULETTE_SEQUENCE[(pos - d) % 37])
        neighbors.append(ROULETTE_SEQUENCE[(pos + d) % 37])
    return neighbors

def get_top_n(numbers_window, n=5):
    frequency = {num: numbers_window.count(num) for num in range(37)}
    ranked = sorted(frequency.items(), key=lambda x: x[1], reverse=True)
    return [num for num, _ in ranked[:n]]

def get_bet_numbers(top_n, neighbor_distance=1):
    bet_set = set(top_n)
    for num in top_n:
        bet_set.update(get_neighbors(num, distance=neighbor_distance))
    return bet_set

# === MongoDB ===
MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("MONGO_DB", "roleta_db")
ROULETTE_SLUG = "pragmatic-brazilian-roulette"

print("Conectando ao MongoDB...")
mongo_client = MongoClient(MONGO_URL, tls=True, tlsCAFile=certifi.where())
mongo_db = mongo_client[DB_NAME]
history_collection = mongo_db["history"]

TOTAL_FETCH = 3000
print(f"Buscando últimos {TOTAL_FETCH} números...")
raw_numbers = list(
    history_collection.find(
        {"roulette_id": ROULETTE_SLUG},
        {"value": 1, "timestamp": 1, "_id": 0}
    ).sort("timestamp", -1).limit(TOTAL_FETCH)
)
raw_numbers.reverse()
all_numbers = [n['value'] for n in raw_numbers]
print(f"Total carregado: {len(all_numbers)} números\n")
mongo_client.close()

# === PARÂMETROS (estratégia campeã) ===
WINDOW_SIZE = 500
OBSERVATION_ATTEMPTS = 3
NEIGHBOR_DISTANCE = 1
TOP_N = 5
HITS_TO_WAIT = 1
MAX_WAIT_PER_HIT = 6
LOOKBACK_SIZE = 3  # quantos spins olhar para trás antes do gatilho

print("=" * 100)
print("ANÁLISE DE PAGAMENTO NA INVERSÃO")
print("=" * 100)
print(f"\nParâmetros:")
print(f"  Roleta: {ROULETTE_SLUG}")
print(f"  Janela: {WINDOW_SIZE} | Top N: {TOP_N} | Vizinhos: {NEIGHBOR_DISTANCE}")
print(f"  Espera: {HITS_TO_WAIT} batida (até {MAX_WAIT_PER_HIT}) | Tentativas: {OBSERVATION_ATTEMPTS}")
print(f"  LOOKBACK: {LOOKBACK_SIZE} spins antes do gatilho\n")

# Estatísticas globais
total_triggers = 0
abortados_na_espera = 0

# Segmentos por tipo de inversão
segments = {
    'INVERSION_HOT': {'triggers': 0, 'qualified': 0, 'wins': 0, 'losses': 0,
                      'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}},
    'INVERSION_NEIGHBOR': {'triggers': 0, 'qualified': 0, 'wins': 0, 'losses': 0,
                           'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}},
    'INVERSION_BOTH': {'triggers': 0, 'qualified': 0, 'wins': 0, 'losses': 0,
                       'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}},
    'NO_INVERSION': {'triggers': 0, 'qualified': 0, 'wins': 0, 'losses': 0,
                     'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}}
}

bet_sizes_by_segment = {k: [] for k in segments}

MAX_SPAN = HITS_TO_WAIT * MAX_WAIT_PER_HIT + OBSERVATION_ATTEMPTS

i = WINDOW_SIZE
while i < len(all_numbers) - MAX_SPAN:
    window = all_numbers[i - WINDOW_SIZE:i]
    current_number = all_numbers[i]
    top_n = get_top_n(window, n=TOP_N)

    if current_number not in top_n:
        i += 1
        continue

    total_triggers += 1
    bet_numbers = get_bet_numbers(top_n, neighbor_distance=NEIGHBOR_DISTANCE)
    hot_set = set(top_n)
    neighbor_set = bet_numbers - hot_set

    # === CLASSIFICAÇÃO DA INVERSÃO ===
    # Olha LOOKBACK_SIZE spins antes do gatilho
    lookback_start = max(0, i - LOOKBACK_SIZE)
    lookback_spins = all_numbers[lookback_start:i]

    had_hot_before = any(s in hot_set for s in lookback_spins)
    had_neighbor_before = any(s in neighbor_set for s in lookback_spins)

    if had_hot_before and had_neighbor_before:
        segment = 'INVERSION_BOTH'
    elif had_hot_before:
        segment = 'INVERSION_HOT'
    elif had_neighbor_before:
        segment = 'INVERSION_NEIGHBOR'
    else:
        segment = 'NO_INVERSION'

    segments[segment]['triggers'] += 1

    # === FASE 1: Esperar 1 batida ===
    cursor = i
    aborted = False
    for hit_num in range(1, HITS_TO_WAIT + 1):
        hit_found = False
        for attempt_idx in range(1, MAX_WAIT_PER_HIT + 1):
            spin_idx = cursor + attempt_idx
            if spin_idx >= len(all_numbers):
                break
            if all_numbers[spin_idx] in bet_numbers:
                cursor = spin_idx
                hit_found = True
                break
        if not hit_found:
            aborted = True
            break

    if aborted:
        abortados_na_espera += 1
        i += 1
        continue

    segments[segment]['qualified'] += 1
    bet_sizes_by_segment[segment].append(len(bet_numbers))

    # === FASE 2: Aposta ===
    bet_start_idx = cursor + 1
    won_at = None
    for attempt_idx in range(1, OBSERVATION_ATTEMPTS + 1):
        spin_idx = bet_start_idx + attempt_idx - 1
        if spin_idx >= len(all_numbers):
            break
        if all_numbers[spin_idx] in bet_numbers:
            won_at = attempt_idx
            break

    if won_at is not None:
        segments[segment]['wins'] += 1
        segments[segment]['wins_per_gale'][won_at] += 1
    else:
        segments[segment]['losses'] += 1

    i += 1

# === RESULTADOS ===
total_qualified = sum(s['qualified'] for s in segments.values())

print("=" * 100)
print("RESULTADOS POR SEGMENTO")
print("=" * 100 + "\n")

print(f"Total de gatilhos: {total_triggers}")
print(f"Abortados na espera: {abortados_na_espera} ({abortados_na_espera/total_triggers*100:.2f}%)")
print(f"Total qualificados: {total_qualified} ({total_qualified/total_triggers*100:.2f}%)\n")

# Cabeçalho
print(f"{'SEGMENTO':<22} {'Trigs':>7} {'Qual.':>7} {'Wins':>6} {'Loss':>6} {'Win%':>8} {'Teor%':>8} {'Edge':>9}")
print("-" * 100)

results = {}
for seg_name in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH', 'NO_INVERSION']:
    s = segments[seg_name]
    qualified = s['qualified']
    wins = s['wins']
    losses = s['losses']

    win_rate = (wins / qualified * 100) if qualified > 0 else 0

    avg_bet = (sum(bet_sizes_by_segment[seg_name]) / len(bet_sizes_by_segment[seg_name])
               if bet_sizes_by_segment[seg_name] else 0)
    theoretical = (1 - (1 - avg_bet / 37) ** OBSERVATION_ATTEMPTS) * 100 if avg_bet > 0 else 0
    edge = win_rate - theoretical

    edge_str = f"+{edge:5.2f}%" if edge >= 0 else f"{edge:6.2f}%"
    edge_marker = " ✅" if edge > 0 else " ⚠️"

    print(f"{seg_name:<22} {s['triggers']:>7} {qualified:>7} {wins:>6} {losses:>6} "
          f"{win_rate:>7.2f}% {theoretical:>7.2f}% {edge_str}{edge_marker}")

    results[seg_name] = {
        'triggers': s['triggers'],
        'qualified': qualified,
        'wins': wins,
        'losses': losses,
        'win_rate': round(win_rate, 2),
        'theoretical_pct': round(theoretical, 2),
        'edge': round(edge, 2),
        'avg_bet_size': round(avg_bet, 2),
        'wins_per_gale': s['wins_per_gale']
    }

print()

# === Detalhamento por segmento ===
print("=" * 100)
print("DETALHAMENTO POR GALE (cada segmento)")
print("=" * 100 + "\n")

for seg_name in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH', 'NO_INVERSION']:
    s = segments[seg_name]
    if s['qualified'] == 0:
        continue

    print(f"📌 {seg_name} ({s['qualified']} apostas):")
    for attempt in range(1, OBSERVATION_ATTEMPTS + 1):
        wins = s['wins_per_gale'][attempt]
        rate = (wins / s['qualified'] * 100) if s['qualified'] > 0 else 0
        print(f"  G{attempt}: {wins:3d} ({rate:5.2f}%)")
    print(f"  LOSS: {s['losses']:3d} ({s['losses']/s['qualified']*100:5.2f}%)\n")

# === Análise agregada (todos juntos = baseline atual) ===
total_wins = sum(s['wins'] for s in segments.values())
total_losses = sum(s['losses'] for s in segments.values())
overall_rate = (total_wins / total_qualified * 100) if total_qualified > 0 else 0

print("=" * 100)
print("BASELINE (todos os triggers juntos)")
print("=" * 100 + "\n")
print(f"Total apostas: {total_qualified}")
print(f"Wins: {total_wins} ({overall_rate:.2f}%)")
print(f"Losses: {total_losses} ({total_losses/total_qualified*100:.2f}%)")

all_bet_sizes = [bs for sizes in bet_sizes_by_segment.values() for bs in sizes]
overall_avg_bet = sum(all_bet_sizes) / len(all_bet_sizes) if all_bet_sizes else 0
overall_theoretical = (1 - (1 - overall_avg_bet / 37) ** OBSERVATION_ATTEMPTS) * 100
overall_edge = overall_rate - overall_theoretical
print(f"Média apostada: {overall_avg_bet:.1f}")
print(f"Probabilidade teórica: {overall_theoretical:.2f}%")
print(f"Edge: {'+' if overall_edge >= 0 else ''}{overall_edge:.2f}%\n")

# === COMPARAÇÃO: filtrar por melhor segmento ===
print("=" * 100)
print("CONCLUSÃO: PAGAMENTO NA INVERSÃO AJUDA OU ATRAPALHA?")
print("=" * 100 + "\n")

# Ordenar segmentos por edge
ranked_segments = sorted(
    [(name, results[name]) for name in results if results[name]['qualified'] > 0],
    key=lambda x: x[1]['edge'],
    reverse=True
)

print("Ranking por EDGE:")
for rank, (name, r) in enumerate(ranked_segments, 1):
    edge = r['edge']
    marker = "✅" if edge > 0 else "⚠️"
    print(f"  #{rank} {name:<22} edge: {'+' if edge >= 0 else ''}{edge:.2f}% {marker} "
          f"(win_rate: {r['win_rate']:.2f}%, n={r['qualified']})")

print()

# Combinações filtradas (apostar só em segmentos positivos)
print("Cenários de filtro:")
print()

scenarios = [
    ("Sem filtro (todos)", list(results.keys())),
    ("Apenas INVERSION_HOT", ['INVERSION_HOT']),
    ("Apenas INVERSION_NEIGHBOR", ['INVERSION_NEIGHBOR']),
    ("Apenas INVERSION_BOTH", ['INVERSION_BOTH']),
    ("Apenas NO_INVERSION", ['NO_INVERSION']),
    ("Sem INVERSION_HOT", ['INVERSION_NEIGHBOR', 'INVERSION_BOTH', 'NO_INVERSION']),
    ("Sem NO_INVERSION", ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH']),
    ("Apenas com inversão (qualquer)", ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH']),
]

print(f"{'Cenário':<35} {'Apostas':>10} {'Wins':>7} {'Win%':>9} {'Edge':>10}")
print("-" * 100)
for name, segs in scenarios:
    qual = sum(results[s]['qualified'] for s in segs if s in results)
    wins = sum(results[s]['wins'] for s in segs if s in results)
    if qual == 0:
        continue
    win_rate = wins / qual * 100
    avg_bet = sum(sum(bet_sizes_by_segment[s]) for s in segs) / qual if qual > 0 else 0
    theo = (1 - (1 - avg_bet / 37) ** OBSERVATION_ATTEMPTS) * 100 if avg_bet > 0 else 0
    edge = win_rate - theo
    edge_str = f"+{edge:5.2f}%" if edge >= 0 else f"{edge:6.2f}%"
    marker = " ✅" if edge > 0 else " ⚠️"
    print(f"{name:<35} {qual:>10} {wins:>7} {win_rate:>8.2f}% {edge_str}{marker}")

# Salvar
with open("inversion_payment_analysis.json", "w") as f:
    json.dump({
        "parameters": {
            "roulette": ROULETTE_SLUG,
            "window_size": WINDOW_SIZE,
            "top_n": TOP_N,
            "neighbor_distance": NEIGHBOR_DISTANCE,
            "hits_to_wait": HITS_TO_WAIT,
            "observation_attempts": OBSERVATION_ATTEMPTS,
            "lookback_size": LOOKBACK_SIZE
        },
        "totals": {
            "triggers": total_triggers,
            "aborted": abortados_na_espera,
            "qualified": total_qualified,
            "overall_win_rate": round(overall_rate, 2),
            "overall_edge": round(overall_edge, 2)
        },
        "segments": results
    }, f, indent=2)

print(f"\n✅ Análise salva em inversion_payment_analysis.json")
