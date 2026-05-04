#!/usr/bin/env python3
"""
Estratégia: Gatilho -> Espera bater 1x -> Aposta novamente nos mesmos números
Medição: posição da batida + se foi quente ou vizinho
1 vizinho de cada lado
"""

import os
import json
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi

load_dotenv()

# Sequência física da roleta europeia
ROULETTE_SEQUENCE = [
    0, 26, 3, 35, 12, 28, 7, 29, 18, 22, 9, 31, 14, 20, 1, 33, 16, 24, 5, 10,
    23, 8, 30, 11, 36, 13, 27, 6, 34, 17, 25, 2, 21, 4, 19, 15, 32
]

POSITION_MAP = {num: idx for idx, num in enumerate(ROULETTE_SEQUENCE)}

def get_neighbors(number, distance=1):
    pos = POSITION_MAP[number]
    neighbors = []
    for d in range(1, distance + 1):
        left_pos = (pos - d) % 37
        right_pos = (pos + d) % 37
        neighbors.append(ROULETTE_SEQUENCE[left_pos])
        neighbors.append(ROULETTE_SEQUENCE[right_pos])
    return neighbors

def get_top_n(numbers_window, n=5):
    frequency = {}
    for num in range(37):
        frequency[num] = numbers_window.count(num)
    ranked = sorted(frequency.items(), key=lambda x: x[1], reverse=True)
    return [num for num, _ in ranked[:n]]

def get_bet_numbers(top_n, neighbor_distance=1):
    """Retorna lista com top N + vizinhos"""
    bet_set = set(top_n)
    for num in top_n:
        neighbors = get_neighbors(num, distance=neighbor_distance)
        bet_set.update(neighbors)
    return bet_set

# === MongoDB ===
MONGO_URL = os.getenv("MONGO_URL")
DB_NAME = os.getenv("MONGO_DB", "roleta_db")
ROULETTE_SLUG = "pragmatic-brazilian-roulette"

print("Conectando ao MongoDB...")
mongo_client = MongoClient(MONGO_URL, tls=True, tlsCAFile=certifi.where())
mongo_db = mongo_client[DB_NAME]
history_collection = mongo_db["history"]

TOTAL_FETCH = 2000
print(f"Buscando últimos {TOTAL_FETCH} números...")

raw_numbers = list(
    history_collection.find(
        {"roulette_id": ROULETTE_SLUG},
        {"value": 1, "timestamp": 1, "_id": 0}
    )
    .sort("timestamp", -1)
    .limit(TOTAL_FETCH)
)
raw_numbers.reverse()
all_numbers = [n['value'] for n in raw_numbers]
print(f"Total carregado: {len(all_numbers)} números\n")
mongo_client.close()

# === SIMULAÇÃO ===
WINDOW_SIZE = 500
OBSERVATION_ATTEMPTS = 6  # tentativas após as batidas de espera
NEIGHBOR_DISTANCE = 1
TOP_N = 5  # quantos números quentes considerar
HITS_TO_WAIT = 2  # quantas batidas precisamos antes de apostar
MAX_WAIT_PER_HIT = 6  # quantas tentativas esperar por cada batida

print("="*100)
print(f"ESTRATÉGIA: GATILHO -> ESPERA BATER {HITS_TO_WAIT}x -> APOSTA")
print("="*100)
print(f"\nParâmetros:")
print(f"  Roleta: {ROULETTE_SLUG}")
print(f"  Janela: {WINDOW_SIZE} spins")
print(f"  Top N (números quentes): {TOP_N}")
print(f"  Vizinhos: {NEIGHBOR_DISTANCE} cada lado")
print(f"  Batidas a esperar antes de apostar: {HITS_TO_WAIT}")
print(f"  Espera por cada batida: até {MAX_WAIT_PER_HIT} tentativas")
print(f"  Tentativas após confirmação: {OBSERVATION_ATTEMPTS}\n")

# Estatísticas
total_triggers = 0
abortados_na_espera = 0   # gatilho mas alguma das batidas não veio em tempo

# Estatísticas das batidas de espera (por batida 1, 2, ..., HITS_TO_WAIT)
wait_hit_stats = {h: {'hot': 0, 'neighbor': 0,
                      'attempts': {i: 0 for i in range(1, MAX_WAIT_PER_HIT + 1)}}
                  for h in range(1, HITS_TO_WAIT + 1)}

# Estatísticas da APOSTA (após N batidas)
bet_wins_per_attempt = {i: 0 for i in range(1, OBSERVATION_ATTEMPTS + 1)}
bet_losses = 0

# Detalhe: onde a aposta bateu
bet_hit_type = {'hot': 0, 'neighbor': 0}

# Detalhe: cada gale onde bateu
gale_hit_type = {i: {'hot': 0, 'neighbor': 0} for i in range(1, OBSERVATION_ATTEMPTS + 1)}

detailed_log = []

# Avanço máximo necessário para garantir dados disponíveis
MAX_SPAN = HITS_TO_WAIT * MAX_WAIT_PER_HIT + OBSERVATION_ATTEMPTS

i = WINDOW_SIZE
while i < len(all_numbers) - MAX_SPAN:
    window = all_numbers[i - WINDOW_SIZE:i]
    current_number = all_numbers[i]
    top_n = get_top_n(window, n=TOP_N)

    # Verifica se gatilho disparou
    if current_number not in top_n:
        i += 1
        continue

    total_triggers += 1
    bet_numbers = get_bet_numbers(top_n, neighbor_distance=NEIGHBOR_DISTANCE)
    hot_set = set(top_n)

    # === FASE 1: Esperar HITS_TO_WAIT batidas ===
    cursor = i  # ponteiro de onde estamos olhando
    hits_received = []  # cada item: (attempt_within_wait, value, type, absolute_index)
    aborted = False

    for hit_num in range(1, HITS_TO_WAIT + 1):
        hit_found = False
        for attempt_idx in range(1, MAX_WAIT_PER_HIT + 1):
            spin_idx = cursor + attempt_idx
            if spin_idx >= len(all_numbers):
                break
            next_num = all_numbers[spin_idx]
            if next_num in bet_numbers:
                # Bateu!
                hit_type = 'hot' if next_num in hot_set else 'neighbor'
                hits_received.append({
                    'hit_num': hit_num,
                    'attempt': attempt_idx,
                    'value': next_num,
                    'type': hit_type,
                    'abs_idx': spin_idx
                })
                # Registrar estatística
                wait_hit_stats[hit_num][hit_type] += 1
                wait_hit_stats[hit_num]['attempts'][attempt_idx] += 1
                cursor = spin_idx
                hit_found = True
                break

        if not hit_found:
            # Não conseguiu pegar essa batida
            aborted = True
            break

    if aborted:
        abortados_na_espera += 1
        detailed_log.append({
            'spin_index': i,
            'trigger': current_number,
            'top_n': top_n,
            'hits_received': hits_received,
            'aborted_at_hit': len(hits_received) + 1,
            'outcome': 'ABORTED_WAIT'
        })
        i += 1
        continue

    # === FASE 2: Aposta após N batidas ===
    bet_start_idx = cursor + 1  # próximo spin após a última batida

    bet_won_at = None
    bet_won_value = None
    bet_won_type = None

    for attempt_idx in range(1, OBSERVATION_ATTEMPTS + 1):
        spin_idx = bet_start_idx + attempt_idx - 1
        if spin_idx >= len(all_numbers):
            break
        next_num = all_numbers[spin_idx]
        if next_num in bet_numbers:
            bet_won_at = attempt_idx
            bet_won_value = next_num
            bet_won_type = 'hot' if next_num in hot_set else 'neighbor'
            break

    if bet_won_at is not None:
        bet_wins_per_attempt[bet_won_at] += 1
        bet_hit_type[bet_won_type] += 1
        gale_hit_type[bet_won_at][bet_won_type] += 1
        outcome = f"WIN G{bet_won_at} ({bet_won_type.upper()})"
    else:
        bet_losses += 1
        outcome = "LOSS"

    detailed_log.append({
        'spin_index': i,
        'trigger': current_number,
        'top_n': top_n,
        'hits_received': hits_received,
        'bet_won_at': bet_won_at,
        'bet_won_value': bet_won_value,
        'bet_won_type': bet_won_type,
        'outcome': outcome
    })

    i += 1

# === RESULTADOS ===
print("="*100)
print("RESULTADOS")
print("="*100 + "\n")

print(f"Gatilhos disparados: {total_triggers}")
print(f"Gatilhos abortados (não conseguiram {HITS_TO_WAIT} batidas): {abortados_na_espera} ({abortados_na_espera/total_triggers*100:.2f}%)")
total_qualified = total_triggers - abortados_na_espera
print(f"Gatilhos qualificados (bateram {HITS_TO_WAIT}x e entram na aposta): {total_qualified} ({total_qualified/total_triggers*100:.2f}%)\n")

# === FASE 1 - Cada batida da espera ===
print("-" * 100)
print(f"FASE 1 - DETALHE DAS {HITS_TO_WAIT} BATIDAS DE ESPERA")
print("-" * 100 + "\n")

for hit_num in range(1, HITS_TO_WAIT + 1):
    stats = wait_hit_stats[hit_num]
    total_for_this_hit = stats['hot'] + stats['neighbor']
    print(f"BATIDA #{hit_num} (total: {total_for_this_hit}x):")

    print(f"  Em qual tentativa veio:")
    for attempt, count in stats['attempts'].items():
        if count > 0:
            pct = count / total_for_this_hit * 100 if total_for_this_hit > 0 else 0
            print(f"    Tentativa {attempt}: {count:3d}x ({pct:5.2f}%)")

    if total_for_this_hit > 0:
        hot_pct = stats['hot'] / total_for_this_hit * 100
        neighbor_pct = stats['neighbor'] / total_for_this_hit * 100
        print(f"  Tipo:")
        print(f"    QUENTE:  {stats['hot']:3d}x ({hot_pct:5.2f}%)")
        print(f"    VIZINHO: {stats['neighbor']:3d}x ({neighbor_pct:5.2f}%)")
    print()

# === FASE 2 - Aposta após N batidas ===
print("-" * 100)
print(f"FASE 2 - APOSTA APÓS {HITS_TO_WAIT} BATIDAS")
print("-" * 100 + "\n")

total_bets = total_qualified
total_bet_wins = sum(bet_wins_per_attempt.values())
bet_win_rate = (total_bet_wins / total_bets * 100) if total_bets > 0 else 0
bet_loss_rate = (bet_losses / total_bets * 100) if total_bets > 0 else 0

print(f"Total de apostas realizadas: {total_bets}\n")
print(f"{'Tentativa':<25} {'Acertos':<12} {'%':<10} {'Quente':<10} {'Vizinho':<10}")
print("-" * 80)

for attempt in range(1, OBSERVATION_ATTEMPTS + 1):
    wins = bet_wins_per_attempt[attempt]
    rate = (wins / total_bets * 100) if total_bets > 0 else 0
    hot_in_gale = gale_hit_type[attempt]['hot']
    neighbor_in_gale = gale_hit_type[attempt]['neighbor']
    print(f"{'G' + str(attempt):<25} {wins:<12} {rate:>6.2f}%   {hot_in_gale:<10} {neighbor_in_gale:<10}")

print(f"{'LOSS':<25} {bet_losses:<12} {bet_loss_rate:>6.2f}%")
print("-" * 80)
print(f"{'TOTAL VITÓRIAS':<25} {total_bet_wins:<12} {bet_win_rate:>6.2f}%")

print(f"\n{'='*100}")
print(f"ASSERTIVIDADE DA APOSTA: {bet_win_rate:.2f}% ({total_bet_wins}/{total_bets})")
print(f"{'='*100}\n")

# Tipo de batida na aposta
print("TIPO DE BATIDA NA APOSTA (todas as tentativas combinadas):")
if total_bet_wins > 0:
    hot_in_bet = bet_hit_type['hot']
    neighbor_in_bet = bet_hit_type['neighbor']
    hot_pct_bet = hot_in_bet / total_bet_wins * 100
    neighbor_pct_bet = neighbor_in_bet / total_bet_wins * 100
    print(f"  Bateu em QUENTE:  {hot_in_bet:3d}x ({hot_pct_bet:5.2f}% dos wins)")
    print(f"  Bateu em VIZINHO: {neighbor_in_bet:3d}x ({neighbor_pct_bet:5.2f}% dos wins)")

# Probabilidade teórica - calculada a partir do tamanho médio real das apostas
bet_sizes = []
for d in detailed_log:
    if d.get('outcome') not in ['ABORTED_WAIT']:
        top_n_log = d['top_n']
        bet_set_log = get_bet_numbers(top_n_log, neighbor_distance=NEIGHBOR_DISTANCE)
        bet_sizes.append(len(bet_set_log))

avg_bet_size = sum(bet_sizes) / len(bet_sizes) if bet_sizes else 0
theoretical_per_attempt = avg_bet_size / 37
theoretical_n = 1 - ((1 - theoretical_per_attempt) ** OBSERVATION_ATTEMPTS)
print(f"\nMédia de números apostados: {avg_bet_size:.1f} ({avg_bet_size/37*100:.1f}% da mesa)")
print(f"Probabilidade teórica em {OBSERVATION_ATTEMPTS} tentativas: {theoretical_n*100:.2f}%")
if bet_win_rate > theoretical_n * 100:
    edge = bet_win_rate - theoretical_n * 100
    print(f"✅ Estratégia tem EDGE de +{edge:.2f}% sobre o acaso")
else:
    deficit = theoretical_n * 100 - bet_win_rate
    print(f"⚠️  Estratégia está {deficit:.2f}% ABAIXO do acaso")

# Últimas 10 jogadas
print(f"\n" + "="*100)
print("ÚLTIMAS 10 JOGADAS (que tiveram aposta)")
print("="*100 + "\n")

logs_with_bet = [d for d in detailed_log if d.get('outcome') not in ['ABORTED_WAIT']]
for log in logs_with_bet[-10:]:
    hits_str = " | ".join([f"H{h['hit_num']}@G{h['attempt']}={h['value']}({h['type']})" for h in log['hits_received']])
    print(f"Spin #{log['spin_index']:4d} | Gatilho: {log['trigger']:2d} | "
          f"Batidas: {hits_str} | "
          f"Aposta: {log['outcome']}")

# Salvar resultados
results = {
    "parameters": {
        "roulette": ROULETTE_SLUG,
        "window_size": WINDOW_SIZE,
        "top_n": TOP_N,
        "neighbor_distance": NEIGHBOR_DISTANCE,
        "hits_to_wait": HITS_TO_WAIT,
        "max_wait_per_hit": MAX_WAIT_PER_HIT,
        "observation_attempts": OBSERVATION_ATTEMPTS,
    },
    "phase_1_wait_hits": {
        "total_triggers": total_triggers,
        "aborted": abortados_na_espera,
        "qualified": total_qualified,
        "per_hit_stats": wait_hit_stats
    },
    "phase_2_bet": {
        "total_bets": total_bets,
        "wins_per_gale": bet_wins_per_attempt,
        "losses": bet_losses,
        "total_wins": total_bet_wins,
        "win_rate": round(bet_win_rate, 2),
        "loss_rate": round(bet_loss_rate, 2),
        "hit_in_hot": bet_hit_type['hot'],
        "hit_in_neighbor": bet_hit_type['neighbor'],
        "gale_breakdown": gale_hit_type
    }
}

with open("simulate_hot_strategy.json", "w") as f:
    json.dump(results, f, indent=2)

print(f"\n✅ Resultados salvos em simulate_hot_strategy.json")
