#!/usr/bin/env python3
"""
ESTRATÉGIA: GATILHO AMPLIADO + APOSTA CONCENTRADA

- TRIGGER_TOP_N = 10: gatilho dispara se o número estiver no top 10 (frequência maior)
- BET_TOP_N = 5: aposta cobre apenas os top 5 + vizinhos (tamanho controlado)
- HITS_TO_WAIT = 1: espera 1 batida em (top 5 + vizinhos)
- OBSERVATION_ATTEMPTS = 3: 3 tentativas de aposta após confirmação

Também segmenta por pagamento na inversão.
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

def get_top_n(numbers_window, n):
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

# === PARÂMETROS ===
WINDOW_SIZE = 500
OBSERVATION_ATTEMPTS = 3
NEIGHBOR_DISTANCE = 1
TRIGGER_TOP_N = 7         # gatilho dispara em top 7
BET_TOP_N = 5             # aposta na base do top 5 + vizinhos
HITS_TO_WAIT = 1
MAX_WAIT_PER_HIT = 6
LOOKBACK_SIZE = 3

print("=" * 100)
print("ESTRATÉGIA: GATILHO TOP 10 + APOSTA NA BASE TOP 5 + VIZINHOS")
print("=" * 100)
print(f"\nParâmetros:")
print(f"  Roleta: {ROULETTE_SLUG}")
print(f"  Janela: {WINDOW_SIZE}")
print(f"  TRIGGER_TOP_N: {TRIGGER_TOP_N} (gatilho dispara em top {TRIGGER_TOP_N})")
print(f"  BET_TOP_N: {BET_TOP_N} (aposta cobre apenas top {BET_TOP_N})")
print(f"  Vizinhos: {NEIGHBOR_DISTANCE} cada lado")
print(f"  Espera: {HITS_TO_WAIT} batida (até {MAX_WAIT_PER_HIT}) | Tentativas: {OBSERVATION_ATTEMPTS}")
print(f"  LOOKBACK: {LOOKBACK_SIZE} spins\n")

# Stats globais
total_triggers = 0
abortados = 0
total_qualified = 0
total_wins = 0
total_losses = 0
wins_per_gale = {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}
gale_hit_type = {i: {'hot': 0, 'neighbor': 0} for i in range(1, OBSERVATION_ATTEMPTS + 1)}
bet_hit_type = {'hot': 0, 'neighbor': 0}
bet_sizes = []

# Stats por trigger ser bet-base ou expandido (top 5 vs 6-10)
trigger_segment_stats = {
    'TRIGGER_IN_BET_BASE': {'qualified': 0, 'wins': 0, 'losses': 0,
                            'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)},
                            'bet_sizes': []},
    'TRIGGER_OUT_OF_BET_BASE': {'qualified': 0, 'wins': 0, 'losses': 0,
                                'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)},
                                'bet_sizes': []}
}

# Stats por inversão (em cima da aposta — top 5 + vizinhos)
inversion_segments = {
    'INVERSION_HOT': {'qualified': 0, 'wins': 0, 'losses': 0, 'bet_sizes': []},
    'INVERSION_NEIGHBOR': {'qualified': 0, 'wins': 0, 'losses': 0, 'bet_sizes': []},
    'INVERSION_BOTH': {'qualified': 0, 'wins': 0, 'losses': 0, 'bet_sizes': []},
    'NO_INVERSION': {'qualified': 0, 'wins': 0, 'losses': 0, 'bet_sizes': []}
}

MAX_SPAN = HITS_TO_WAIT * MAX_WAIT_PER_HIT + OBSERVATION_ATTEMPTS

i = WINDOW_SIZE
while i < len(all_numbers) - MAX_SPAN:
    window = all_numbers[i - WINDOW_SIZE:i]
    current_number = all_numbers[i]
    trigger_top_n = get_top_n(window, n=TRIGGER_TOP_N)

    if current_number not in trigger_top_n:
        i += 1
        continue

    total_triggers += 1
    bet_top_n = trigger_top_n[:BET_TOP_N]
    bet_numbers = get_bet_numbers(bet_top_n, neighbor_distance=NEIGHBOR_DISTANCE)
    hot_set = set(bet_top_n)
    neighbor_set = bet_numbers - hot_set

    # Classificar trigger: está dentro da bet base (top 5) ou expandido (6-10)?
    if current_number in hot_set:
        trigger_seg = 'TRIGGER_IN_BET_BASE'
    else:
        trigger_seg = 'TRIGGER_OUT_OF_BET_BASE'

    # Classificar inversão (em cima da bet base)
    lookback_start = max(0, i - LOOKBACK_SIZE)
    lookback_spins = all_numbers[lookback_start:i]
    had_hot_before = any(s in hot_set for s in lookback_spins)
    had_neighbor_before = any(s in neighbor_set for s in lookback_spins)

    if had_hot_before and had_neighbor_before:
        inv_seg = 'INVERSION_BOTH'
    elif had_hot_before:
        inv_seg = 'INVERSION_HOT'
    elif had_neighbor_before:
        inv_seg = 'INVERSION_NEIGHBOR'
    else:
        inv_seg = 'NO_INVERSION'

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
        abortados += 1
        i += 1
        continue

    total_qualified += 1
    bet_sizes.append(len(bet_numbers))
    trigger_segment_stats[trigger_seg]['qualified'] += 1
    trigger_segment_stats[trigger_seg]['bet_sizes'].append(len(bet_numbers))
    inversion_segments[inv_seg]['qualified'] += 1
    inversion_segments[inv_seg]['bet_sizes'].append(len(bet_numbers))

    # === FASE 2: Aposta ===
    bet_start_idx = cursor + 1
    won_at = None
    won_type = None
    for attempt_idx in range(1, OBSERVATION_ATTEMPTS + 1):
        spin_idx = bet_start_idx + attempt_idx - 1
        if spin_idx >= len(all_numbers):
            break
        next_num = all_numbers[spin_idx]
        if next_num in bet_numbers:
            won_at = attempt_idx
            won_type = 'hot' if next_num in hot_set else 'neighbor'
            break

    if won_at is not None:
        total_wins += 1
        wins_per_gale[won_at] += 1
        gale_hit_type[won_at][won_type] += 1
        bet_hit_type[won_type] += 1
        trigger_segment_stats[trigger_seg]['wins'] += 1
        trigger_segment_stats[trigger_seg]['wins_per_gale'][won_at] += 1
        inversion_segments[inv_seg]['wins'] += 1
    else:
        total_losses += 1
        trigger_segment_stats[trigger_seg]['losses'] += 1
        inversion_segments[inv_seg]['losses'] += 1

    i += 1

# === RESULTADOS GERAIS ===
print("=" * 100)
print("RESULTADOS GERAIS")
print("=" * 100 + "\n")

print(f"Gatilhos disparados: {total_triggers}")
print(f"Abortados na espera: {abortados} ({abortados/total_triggers*100:.2f}%)")
print(f"Qualificados (entraram na aposta): {total_qualified} ({total_qualified/total_triggers*100:.2f}%)\n")

win_rate = (total_wins / total_qualified * 100) if total_qualified > 0 else 0
loss_rate = (total_losses / total_qualified * 100) if total_qualified > 0 else 0
avg_bet = sum(bet_sizes) / len(bet_sizes) if bet_sizes else 0
theoretical = (1 - (1 - avg_bet / 37) ** OBSERVATION_ATTEMPTS) * 100 if avg_bet > 0 else 0
edge = win_rate - theoretical

print(f"{'Tentativa':<15} {'Acertos':>10} {'%':>10} {'Quente':>10} {'Vizinho':>10}")
print("-" * 70)
for attempt in range(1, OBSERVATION_ATTEMPTS + 1):
    wins = wins_per_gale[attempt]
    rate = (wins / total_qualified * 100) if total_qualified > 0 else 0
    h = gale_hit_type[attempt]['hot']
    n = gale_hit_type[attempt]['neighbor']
    print(f"G{attempt:<14} {wins:>10} {rate:>9.2f}% {h:>10} {n:>10}")
print(f"{'LOSS':<15} {total_losses:>10} {loss_rate:>9.2f}%")
print("-" * 70)
print(f"{'TOTAL':<15} {total_wins:>10} {win_rate:>9.2f}%")

print(f"\nMédia apostada: {avg_bet:.1f} ({avg_bet/37*100:.1f}% da mesa)")
print(f"Probabilidade teórica: {theoretical:.2f}%")
print(f"Edge: {'+' if edge >= 0 else ''}{edge:.2f}% {'✅' if edge > 0 else '⚠️'}")

print(f"\nTipo de batida:")
if total_wins > 0:
    print(f"  Quente:  {bet_hit_type['hot']:3d}x ({bet_hit_type['hot']/total_wins*100:.2f}%)")
    print(f"  Vizinho: {bet_hit_type['neighbor']:3d}x ({bet_hit_type['neighbor']/total_wins*100:.2f}%)")

# === SEGMENTO POR TRIGGER (dentro/fora da bet base) ===
print("\n" + "=" * 100)
print("SEGMENTAÇÃO POR ORIGEM DO GATILHO")
print("=" * 100 + "\n")

print(f"{'Origem do Gatilho':<30} {'Qual.':>7} {'Wins':>6} {'Loss':>6} {'Win%':>9} {'Teor%':>9} {'Edge':>10}")
print("-" * 100)
for seg_name in ['TRIGGER_IN_BET_BASE', 'TRIGGER_OUT_OF_BET_BASE']:
    s = trigger_segment_stats[seg_name]
    if s['qualified'] == 0:
        continue
    wr = s['wins'] / s['qualified'] * 100
    avg_b = sum(s['bet_sizes']) / len(s['bet_sizes']) if s['bet_sizes'] else 0
    theo = (1 - (1 - avg_b / 37) ** OBSERVATION_ATTEMPTS) * 100 if avg_b > 0 else 0
    e = wr - theo
    estr = f"+{e:5.2f}%" if e >= 0 else f"{e:6.2f}%"
    mk = " ✅" if e > 0 else " ⚠️"
    label = "Top 1-5 (na base)" if seg_name == 'TRIGGER_IN_BET_BASE' else "Top 6-10 (expandido)"
    print(f"{label:<30} {s['qualified']:>7} {s['wins']:>6} {s['losses']:>6} {wr:>8.2f}% {theo:>8.2f}% {estr}{mk}")

# === SEGMENTO POR INVERSÃO ===
print("\n" + "=" * 100)
print("SEGMENTAÇÃO POR PAGAMENTO NA INVERSÃO (lookback={})".format(LOOKBACK_SIZE))
print("=" * 100 + "\n")

print(f"{'Inversão':<22} {'Qual.':>7} {'Wins':>6} {'Loss':>6} {'Win%':>9} {'Teor%':>9} {'Edge':>10}")
print("-" * 100)
for seg_name in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH', 'NO_INVERSION']:
    s = inversion_segments[seg_name]
    if s['qualified'] == 0:
        continue
    wr = s['wins'] / s['qualified'] * 100
    avg_b = sum(s['bet_sizes']) / len(s['bet_sizes']) if s['bet_sizes'] else 0
    theo = (1 - (1 - avg_b / 37) ** OBSERVATION_ATTEMPTS) * 100 if avg_b > 0 else 0
    e = wr - theo
    estr = f"+{e:5.2f}%" if e >= 0 else f"{e:6.2f}%"
    mk = " ✅" if e > 0 else " ⚠️"
    print(f"{seg_name:<22} {s['qualified']:>7} {s['wins']:>6} {s['losses']:>6} {wr:>8.2f}% {theo:>8.2f}% {estr}{mk}")

# Filtro: sem NO_INVERSION
filtered_qual = sum(inversion_segments[k]['qualified']
                    for k in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH'])
filtered_wins = sum(inversion_segments[k]['wins']
                    for k in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH'])
filtered_bets = []
for k in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH']:
    filtered_bets.extend(inversion_segments[k]['bet_sizes'])

if filtered_qual > 0:
    f_wr = filtered_wins / filtered_qual * 100
    f_avg = sum(filtered_bets) / len(filtered_bets)
    f_theo = (1 - (1 - f_avg / 37) ** OBSERVATION_ATTEMPTS) * 100
    f_edge = f_wr - f_theo
    print()
    print(f"{'Sem NO_INVERSION (filtro)':<22} {filtered_qual:>7} {filtered_wins:>6} "
          f"{filtered_qual-filtered_wins:>6} {f_wr:>8.2f}% {f_theo:>8.2f}% "
          f"{'+' if f_edge >= 0 else ''}{f_edge:5.2f}% {'✅' if f_edge > 0 else '⚠️'}")

# === COMPARAÇÃO COM BASELINE (top 5 disparando E apostando) ===
print("\n" + "=" * 100)
print("COMPARAÇÃO: GATILHO TOP 10 vs GATILHO TOP 5 (mesma base de aposta)")
print("=" * 100 + "\n")

print(f"{'Configuração':<45} {'Apostas':>10} {'Win%':>9} {'Edge':>10}")
print("-" * 100)
print(f"{'Baseline: gatilho TOP 5, aposta TOP 5+viz':<45} {'313':>10} {'76.68%':>9} {'+3.27%':>10}")
print(f"{'NOVO: gatilho TOP 10, aposta TOP 5+viz':<45} {total_qualified:>10} "
      f"{win_rate:>8.2f}% "
      f"{'+' if edge >= 0 else ''}{edge:5.2f}%")

# Salvar
with open("split_trigger_bet_analysis.json", "w") as f:
    json.dump({
        "parameters": {
            "roulette": ROULETTE_SLUG,
            "window_size": WINDOW_SIZE,
            "trigger_top_n": TRIGGER_TOP_N,
            "bet_top_n": BET_TOP_N,
            "neighbor_distance": NEIGHBOR_DISTANCE,
            "hits_to_wait": HITS_TO_WAIT,
            "observation_attempts": OBSERVATION_ATTEMPTS,
            "lookback_size": LOOKBACK_SIZE
        },
        "totals": {
            "triggers": total_triggers,
            "aborted": abortados,
            "qualified": total_qualified,
            "wins": total_wins,
            "losses": total_losses,
            "win_rate": round(win_rate, 2),
            "edge": round(edge, 2),
            "avg_bet_size": round(avg_bet, 2),
            "theoretical_pct": round(theoretical, 2)
        },
        "trigger_segments": {
            seg: {
                "qualified": s['qualified'],
                "wins": s['wins'],
                "losses": s['losses'],
                "win_rate": round(s['wins']/s['qualified']*100, 2) if s['qualified'] > 0 else 0,
                "wins_per_gale": s['wins_per_gale']
            } for seg, s in trigger_segment_stats.items()
        },
        "inversion_segments": {
            seg: {
                "qualified": s['qualified'],
                "wins": s['wins'],
                "losses": s['losses'],
                "win_rate": round(s['wins']/s['qualified']*100, 2) if s['qualified'] > 0 else 0
            } for seg, s in inversion_segments.items()
        }
    }, f, indent=2)

print(f"\n✅ Resultados salvos em split_trigger_bet_analysis.json")
