#!/usr/bin/env python3
"""
Estratégia: Ativação rank < 7, conta 3 frios (>12), aposta em threshold 14.
Processa itens cronologicamente por roleta com máquina de estados.
"""
import json
from collections import defaultdict

with open('suggestion_hits_with_outcomes.json') as f:
    data = json.load(f)

items = data['items'] if isinstance(data, dict) and 'items' in data else data
print(f"Loaded {len(items)} items\n")

# Strategy parameters
ACTIVATION_RANK = 20     # Activate when hit_rank < 20
COLD_THRESHOLD = 12      # Frios = hit_rank > 12
COLD_COUNT = 3           # Need 3 frios after activation
BET_THRESHOLD = 14       # Bet succeeds if hit_rank <= 14
MAX_ATTEMPTS = 4         # Janela de aposta: até 4 tentativas consecutivas

# Group by roulette and sort chronologically
by_roulette = defaultdict(list)
for item in items:
    if item.get('hit_rank') is None:
        continue
    by_roulette[item.get('roulette_id', 'unknown')].append(item)

for roulette in by_roulette:
    by_roulette[roulette].sort(key=lambda x: x.get('anchor_timestamp_utc', ''))

print(f"Roletas: {list(by_roulette.keys())}")
for r, lst in by_roulette.items():
    print(f"  {r}: {len(lst)} itens")
print()

# Run state machine per roulette
def simulate(items_chrono):
    """Returns list of bets with their outcomes."""
    bets = []
    state = 'WAITING'
    frio_count = 0
    activation_item = None
    activation_idx = None
    frio_items = []

    for idx, item in enumerate(items_chrono):
        rank = item['hit_rank']

        if state == 'WAITING':
            if rank < ACTIVATION_RANK:
                state = 'COUNTING_FRIOS'
                frio_count = 0
                activation_item = item
                activation_idx = idx
                frio_items = []
        elif state == 'COUNTING_FRIOS':
            if rank > COLD_THRESHOLD:
                frio_count += 1
                frio_items.append(item)
                if frio_count >= COLD_COUNT:
                    state = 'READY_TO_BET'
            else:
                # Not a frio - reset, but check if it's a new activation
                if rank < ACTIVATION_RANK:
                    # Restart with this as new activation
                    state = 'COUNTING_FRIOS'
                    frio_count = 0
                    activation_item = item
                    activation_idx = idx
                    frio_items = []
                else:
                    state = 'WAITING'
                    frio_count = 0
                    activation_item = None
                    frio_items = []
        elif state == 'READY_TO_BET':
            # Window of up to MAX_ATTEMPTS - check this item as 1st attempt
            attempts = [item]
            attempt_ranks = [rank]
            won = rank <= BET_THRESHOLD
            won_on = 1 if won else None

            # If didn't win on 1st, try up to MAX_ATTEMPTS-1 more
            if not won:
                for j in range(1, MAX_ATTEMPTS):
                    if idx + j >= len(items_chrono):
                        break
                    next_item = items_chrono[idx + j]
                    next_rank = next_item['hit_rank']
                    attempts.append(next_item)
                    attempt_ranks.append(next_rank)
                    if next_rank <= BET_THRESHOLD:
                        won = True
                        won_on = j + 1
                        break

            bet_outcome = {
                'snapshot_id': item['snapshot_id'],
                'roulette_id': item['roulette_id'],
                'timestamp': item.get('anchor_timestamp_utc'),
                'hit_rank': rank,  # 1st attempt rank
                'attempt_ranks': attempt_ranks,
                'attempts_used': len(attempts),
                'win': won,
                'won_on': won_on,
                'first_attempt': won_on == 1,
                'activation_rank': activation_item['hit_rank'] if activation_item else None,
                'frio_ranks': [f['hit_rank'] for f in frio_items],
            }
            bets.append(bet_outcome)
            # Reset
            state = 'WAITING'
            frio_count = 0
            activation_item = None
            frio_items = []

    return bets

# Simulate per roulette
all_bets = []
by_roulette_results = {}

for roulette, items_chrono in by_roulette.items():
    bets = simulate(items_chrono)
    by_roulette_results[roulette] = bets
    all_bets.extend(bets)

# Print results
print("=" * 80)
print(f"ESTRATÉGIA: ATIVAÇÃO < {ACTIVATION_RANK}, {COLD_COUNT} FRIOS (>{COLD_THRESHOLD}), APOSTA ≤ {BET_THRESHOLD}, ATÉ {MAX_ATTEMPTS} TENTATIVAS")
print("=" * 80)
print()

# Overall
total_bets = len(all_bets)
total_wins = sum(1 for b in all_bets if b['win'])
total_first = sum(1 for b in all_bets if b['first_attempt'])
total_rate = (total_wins / total_bets * 100) if total_bets else 0
total_first_rate = (total_first / total_bets * 100) if total_bets else 0

print(f"📊 RESUMO GERAL")
print(f"  Total apostas: {total_bets}")
print(f"  Acertos: {total_wins}")
print(f"  Taxa: {total_rate:.1f}%")
print(f"  1ª tentativa: {total_first_rate:.1f}%")
print()

# Per roulette
for roulette, bets in by_roulette_results.items():
    n = len(bets)
    wins = sum(1 for b in bets if b['win'])
    firsts = sum(1 for b in bets if b['first_attempt'])
    rate = (wins / n * 100) if n else 0
    first_rate = (firsts / n * 100) if n else 0
    print(f"🎯 {roulette}")
    print(f"  Apostas: {n}")
    print(f"  Acertos: {wins}")
    print(f"  Taxa: {rate:.1f}%")
    print(f"  1ª tentativa: {first_rate:.1f}%")
    print()

# Distribution of attempt where win occurred
print("=" * 80)
print("EM QUAL TENTATIVA OCORREU A VITÓRIA")
print("=" * 80)
attempt_dist = defaultdict(int)
for b in all_bets:
    if b['win']:
        attempt_dist[b['won_on']] += 1
    else:
        attempt_dist['perdeu'] += 1

for k in [1, 2, 3, 4, 'perdeu']:
    cnt = attempt_dist[k]
    pct = cnt / total_bets * 100 if total_bets else 0
    label = f"{k}ª" if isinstance(k, int) else "PERDEU (4 tentativas)"
    bar = '█' * int(pct / 2)
    print(f"  {label:>22}: {cnt:>4} ({pct:.1f}%) {bar}")
print()

# Distribution of bet hit_ranks (1st attempt)
print("=" * 80)
print("DISTRIBUIÇÃO DOS HIT_RANKS DAS APOSTAS (1ª TENTATIVA)")
print("=" * 80)
rank_dist = defaultdict(int)
for b in all_bets:
    bucket = b['hit_rank'] if b['hit_rank'] <= 14 else (
        15 if b['hit_rank'] <= 20 else (
            21 if b['hit_rank'] <= 30 else 31))
    rank_dist[bucket] += 1

for r in sorted(rank_dist.keys()):
    label = str(r) if r <= 14 else (
        '15-20' if r == 15 else (
            '21-30' if r == 21 else '31+'))
    pct = rank_dist[r] / total_bets * 100 if total_bets else 0
    bar = '█' * int(pct)
    print(f"  Rank {label:>5}: {rank_dist[r]:>4} ({pct:.1f}%) {bar}")
print()

# Save
output = {
    'strategy': f'ativação < {ACTIVATION_RANK}, {COLD_COUNT} frios (>{COLD_THRESHOLD}), aposta ≤ {BET_THRESHOLD}',
    'total': {
        'apostas': total_bets,
        'acertos': total_wins,
        'taxa': total_rate,
        'taxa_primeira_tentativa': total_first_rate,
    },
    'by_roulette': {
        roulette: {
            'apostas': len(bets),
            'acertos': sum(1 for b in bets if b['win']),
            'taxa': (sum(1 for b in bets if b['win']) / len(bets) * 100) if bets else 0,
            'taxa_primeira_tentativa': (sum(1 for b in bets if b['first_attempt']) / len(bets) * 100) if bets else 0,
        }
        for roulette, bets in by_roulette_results.items()
    },
    'sample_bets': all_bets[:30],
}

with open('analise_ativ7_3frios_14.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f"✅ Salvo em: analise_ativ7_3frios_14.json")
