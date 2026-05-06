#!/usr/bin/env python3
"""
ESTRATÉGIA SEM ESPERA — APENAS COM FILTRO DE INVERSÃO

- Gatilho: número atual está no TOP 5 (janela 500)
- SEM fase de espera (aposta direto após o gatilho)
- Filtro: apenas inversão (lookback de 3 spins antes do gatilho)
- 3 tentativas (G1-G3)

Hipótese: tirando a espera aumenta a frequência. Será que a inversão
sozinha mantém o edge?
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
TOP_N = 5
LOOKBACK_SIZE = 3
# SEM HITS_TO_WAIT — aposta direto

print("=" * 100)
print("ESTRATÉGIA SEM ESPERA + FILTRO DE INVERSÃO")
print("=" * 100)
print(f"\nParâmetros:")
print(f"  Roleta: {ROULETTE_SLUG}")
print(f"  Janela: {WINDOW_SIZE} | Top N: {TOP_N} | Vizinhos: {NEIGHBOR_DISTANCE}")
print(f"  Tentativas: {OBSERVATION_ATTEMPTS} (G1-G{OBSERVATION_ATTEMPTS})")
print(f"  LOOKBACK: {LOOKBACK_SIZE} spins")
print(f"  ⚠️ SEM FASE DE ESPERA — aposta direto após gatilho\n")

# Stats globais (sem filtro)
total_triggers = 0
total_wins = 0
total_losses = 0
wins_per_gale = {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}
gale_hit_type = {i: {'hot': 0, 'neighbor': 0} for i in range(1, OBSERVATION_ATTEMPTS + 1)}
bet_hit_type = {'hot': 0, 'neighbor': 0}
bet_sizes = []

# Stats por inversão
inversion_segments = {
    'INVERSION_HOT': {'qualified': 0, 'wins': 0, 'losses': 0, 'bet_sizes': [],
                      'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}},
    'INVERSION_NEIGHBOR': {'qualified': 0, 'wins': 0, 'losses': 0, 'bet_sizes': [],
                           'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}},
    'INVERSION_BOTH': {'qualified': 0, 'wins': 0, 'losses': 0, 'bet_sizes': [],
                       'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}},
    'NO_INVERSION': {'qualified': 0, 'wins': 0, 'losses': 0, 'bet_sizes': [],
                     'wins_per_gale': {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}}
}

i = WINDOW_SIZE
while i < len(all_numbers) - OBSERVATION_ATTEMPTS:
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

    # Classificar inversão
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

    inversion_segments[inv_seg]['qualified'] += 1
    inversion_segments[inv_seg]['bet_sizes'].append(len(bet_numbers))
    bet_sizes.append(len(bet_numbers))

    # === APOSTA DIRETA (sem espera) ===
    won_at = None
    won_type = None
    for attempt_idx in range(1, OBSERVATION_ATTEMPTS + 1):
        spin_idx = i + attempt_idx
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
        inversion_segments[inv_seg]['wins'] += 1
        inversion_segments[inv_seg]['wins_per_gale'][won_at] += 1
    else:
        total_losses += 1
        inversion_segments[inv_seg]['losses'] += 1

    i += 1

# === RESULTADOS GERAIS ===
print("=" * 100)
print("RESULTADOS GERAIS (SEM FILTRO)")
print("=" * 100 + "\n")

print(f"Total de apostas: {total_triggers} (todos os gatilhos viram aposta — sem espera)\n")

win_rate = (total_wins / total_triggers * 100) if total_triggers > 0 else 0
loss_rate = (total_losses / total_triggers * 100) if total_triggers > 0 else 0

print(f"{'Tentativa':<15} {'Acertos':>10} {'%':>10} {'Quente':>10} {'Vizinho':>10}")
print("-" * 70)
for attempt in range(1, OBSERVATION_ATTEMPTS + 1):
    wins = wins_per_gale[attempt]
    rate = (wins / total_triggers * 100) if total_triggers > 0 else 0
    h = gale_hit_type[attempt]['hot']
    n = gale_hit_type[attempt]['neighbor']
    print(f"G{attempt:<14} {wins:>10} {rate:>9.2f}% {h:>10} {n:>10}")
print(f"{'LOSS':<15} {total_losses:>10} {loss_rate:>9.2f}%")
print("-" * 70)
print(f"{'TOTAL':<15} {total_wins:>10} {win_rate:>9.2f}%")

avg_bet = sum(bet_sizes) / len(bet_sizes) if bet_sizes else 0
theoretical = (1 - (1 - avg_bet / 37) ** OBSERVATION_ATTEMPTS) * 100 if avg_bet > 0 else 0
edge = win_rate - theoretical

print(f"\nMédia apostada: {avg_bet:.1f} ({avg_bet/37*100:.1f}% da mesa)")
print(f"Probabilidade teórica: {theoretical:.2f}%")
print(f"Edge: {'+' if edge >= 0 else ''}{edge:.2f}% {'✅' if edge > 0 else '⚠️'}")

print(f"\nTipo de batida:")
if total_wins > 0:
    print(f"  Quente:  {bet_hit_type['hot']:3d}x ({bet_hit_type['hot']/total_wins*100:.2f}%)")
    print(f"  Vizinho: {bet_hit_type['neighbor']:3d}x ({bet_hit_type['neighbor']/total_wins*100:.2f}%)")

# === SEGMENTOS POR INVERSÃO ===
print("\n" + "=" * 100)
print("SEGMENTAÇÃO POR PAGAMENTO NA INVERSÃO")
print("=" * 100 + "\n")

print(f"{'Inversão':<22} {'Apostas':>8} {'Wins':>6} {'Loss':>6} {'Win%':>9} {'Teor%':>9} {'Edge':>10}")
print("-" * 100)
seg_results = {}
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
    print(f"{seg_name:<22} {s['qualified']:>8} {s['wins']:>6} {s['losses']:>6} "
          f"{wr:>8.2f}% {theo:>8.2f}% {estr}{mk}")
    seg_results[seg_name] = {
        'qualified': s['qualified'], 'wins': s['wins'], 'losses': s['losses'],
        'win_rate': round(wr, 2), 'theoretical': round(theo, 2), 'edge': round(e, 2),
        'avg_bet_size': round(avg_b, 2),
        'wins_per_gale': s['wins_per_gale']
    }

# === DETALHE POR GALE ===
print("\n" + "=" * 100)
print("DETALHE POR GALE — CADA SEGMENTO")
print("=" * 100 + "\n")

for seg_name in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH', 'NO_INVERSION']:
    s = inversion_segments[seg_name]
    if s['qualified'] == 0:
        continue
    print(f"📌 {seg_name} ({s['qualified']} apostas):")
    for attempt in range(1, OBSERVATION_ATTEMPTS + 1):
        wins = s['wins_per_gale'][attempt]
        rate = wins / s['qualified'] * 100
        print(f"  G{attempt}: {wins:3d} ({rate:5.2f}%)")
    print(f"  LOSS: {s['losses']:3d} ({s['losses']/s['qualified']*100:5.2f}%)\n")

# === FILTRO: SEM NO_INVERSION ===
print("=" * 100)
print("CENÁRIOS DE FILTRO")
print("=" * 100 + "\n")

scenarios = [
    ("Sem filtro (todos)", ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH', 'NO_INVERSION']),
    ("Apenas INVERSION_HOT", ['INVERSION_HOT']),
    ("Apenas INVERSION_NEIGHBOR", ['INVERSION_NEIGHBOR']),
    ("Apenas INVERSION_BOTH", ['INVERSION_BOTH']),
    ("Sem NO_INVERSION", ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH']),
    ("Apenas NO_INVERSION", ['NO_INVERSION']),
]

print(f"{'Cenário':<35} {'Apostas':>10} {'Wins':>7} {'Win%':>9} {'Edge':>10}")
print("-" * 100)
for name, segs in scenarios:
    qual = sum(inversion_segments[s]['qualified'] for s in segs)
    wins = sum(inversion_segments[s]['wins'] for s in segs)
    if qual == 0:
        continue
    wr = wins / qual * 100
    bs = []
    for s in segs:
        bs.extend(inversion_segments[s]['bet_sizes'])
    avg_b = sum(bs) / len(bs) if bs else 0
    theo = (1 - (1 - avg_b / 37) ** OBSERVATION_ATTEMPTS) * 100 if avg_b > 0 else 0
    e = wr - theo
    estr = f"+{e:5.2f}%" if e >= 0 else f"{e:6.2f}%"
    mk = " ✅" if e > 0 else " ⚠️"
    print(f"{name:<35} {qual:>10} {wins:>7} {wr:>8.2f}% {estr}{mk}")

# === COMPARAÇÃO COM ESTRATÉGIA COM ESPERA ===
print("\n" + "=" * 100)
print("COMPARAÇÃO: COM ESPERA vs SEM ESPERA (mesma janela 500, top 5, 3 gales)")
print("=" * 100 + "\n")

print(f"{'Configuração':<50} {'Apostas':>10} {'Win%':>9} {'Edge':>10}")
print("-" * 100)
print(f"{'COM espera (1 batida) - sem filtro':<50} {'313':>10} {'76.68%':>9} {'+3.27%':>10}")
print(f"{'COM espera (1 batida) - sem NO_INVERSION':<50} {'246':>10} {'78.86%':>9} {'+4.84%':>10}")
print(f"{'SEM espera - sem filtro':<50} {total_triggers:>10} {win_rate:>8.2f}% "
      f"{'+' if edge >= 0 else ''}{edge:5.2f}%")

# Sem espera + sem NO_INVERSION
filtered_q = sum(inversion_segments[s]['qualified'] for s in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH'])
filtered_w = sum(inversion_segments[s]['wins'] for s in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH'])
filtered_bs = []
for s in ['INVERSION_HOT', 'INVERSION_NEIGHBOR', 'INVERSION_BOTH']:
    filtered_bs.extend(inversion_segments[s]['bet_sizes'])
f_wr = filtered_w / filtered_q * 100 if filtered_q > 0 else 0
f_avg = sum(filtered_bs) / len(filtered_bs) if filtered_bs else 0
f_theo = (1 - (1 - f_avg / 37) ** OBSERVATION_ATTEMPTS) * 100 if f_avg > 0 else 0
f_edge = f_wr - f_theo
print(f"{'SEM espera - sem NO_INVERSION':<50} {filtered_q:>10} {f_wr:>8.2f}% "
      f"{'+' if f_edge >= 0 else ''}{f_edge:5.2f}%")

# Salvar
with open("no_wait_inversion_analysis.json", "w") as f:
    json.dump({
        "parameters": {
            "roulette": ROULETTE_SLUG,
            "window_size": WINDOW_SIZE,
            "top_n": TOP_N,
            "neighbor_distance": NEIGHBOR_DISTANCE,
            "observation_attempts": OBSERVATION_ATTEMPTS,
            "lookback_size": LOOKBACK_SIZE,
            "hits_to_wait": 0
        },
        "totals": {
            "triggers": total_triggers,
            "wins": total_wins,
            "losses": total_losses,
            "win_rate": round(win_rate, 2),
            "edge": round(edge, 2),
            "avg_bet_size": round(avg_bet, 2)
        },
        "inversion_segments": seg_results,
        "filter_no_inversion_removed": {
            "qualified": filtered_q,
            "wins": filtered_w,
            "win_rate": round(f_wr, 2),
            "edge": round(f_edge, 2)
        }
    }, f, indent=2)

print(f"\n✅ Resultados salvos em no_wait_inversion_analysis.json")
