#!/usr/bin/env python3
import json
from collections import defaultdict
from statistics import mean

# Load data
with open('suggestion_hits_with_outcomes.json') as f:
    data = json.load(f)

items = data['items'] if isinstance(data, dict) and 'items' in data else data

print(f"Loaded {len(items)} items\n")

COLD_THRESHOLD = 12
APOSTA_THRESHOLD = 14
COLD_COUNT = 2
MIN_DISTANCE = 14
MAX_DISTANCE = 16

def get_pattern_type(nums):
    """Classify pattern: crescente, decrescente, or estável"""
    if len(nums) < 2:
        return "unknown"
    is_increasing = all(nums[i] < nums[i+1] for i in range(len(nums)-1))
    is_decreasing = all(nums[i] > nums[i+1] for i in range(len(nums)-1))
    if is_increasing:
        return "crescente"
    elif is_decreasing:
        return "decrescente"
    else:
        return "estável"

def find_cold_sequences(ranking_full, min_count=COLD_COUNT):
    """Find sequences of min_count+ consecutive frios (>12)"""
    sequences = []
    cold_sequence = []

    for rank in ranking_full:
        if rank > COLD_THRESHOLD:
            cold_sequence.append(rank)
        else:
            if len(cold_sequence) >= min_count:
                distance_mean = mean(p - COLD_THRESHOLD for p in cold_sequence)
                sequences.append({
                    'positions': cold_sequence[:],
                    'pattern': get_pattern_type(cold_sequence),
                    'distance_mean': distance_mean,
                    'distance_min': min(p - COLD_THRESHOLD for p in cold_sequence),
                    'distance_max': max(p - COLD_THRESHOLD for p in cold_sequence),
                })
            cold_sequence = []

    if len(cold_sequence) >= min_count:
        distance_mean = mean(p - COLD_THRESHOLD for p in cold_sequence)
        sequences.append({
            'positions': cold_sequence[:],
            'pattern': get_pattern_type(cold_sequence),
            'distance_mean': distance_mean,
            'distance_min': min(p - COLD_THRESHOLD for p in cold_sequence),
            'distance_max': max(p - COLD_THRESHOLD for p in cold_sequence),
        })

    return sequences

# Statistics
stats = {
    'total': {'hits': 0, 'count': 0, 'first': 0},
    'auto': {'hits': 0, 'count': 0, 'first': 0},
    'brazilian': {'hits': 0, 'count': 0, 'first': 0},
}

pattern_stats = {
    'crescente': {'hits': 0, 'count': 0, 'first': 0},
    'decrescente': {'hits': 0, 'count': 0, 'first': 0},
    'estável': {'hits': 0, 'count': 0, 'first': 0},
}

rejected_stats = {
    'distance_too_low': 0,
    'distance_too_high': 0,
    'no_sequences': 0,
}

detail_items = []

for item in items:
    try:
        ranking_full = item.get('ranking_full', [])
        hit_rank = item.get('hit_rank')
        roulette = item.get('roulette_id', 'unknown')
        snapshot_id = item.get('snapshot_id')

        if not ranking_full or hit_rank is None:
            continue

        sequences = find_cold_sequences(ranking_full, COLD_COUNT)
        if not sequences:
            rejected_stats['no_sequences'] += 1
            continue

        # Keep only sequences with distance 14-16
        filtered_seq = [s for s in sequences
                       if MIN_DISTANCE <= s['distance_mean'] <= MAX_DISTANCE]

        if not filtered_seq:
            # Count what was rejected
            for s in sequences:
                if s['distance_mean'] < MIN_DISTANCE:
                    rejected_stats['distance_too_low'] += 1
                else:
                    rejected_stats['distance_too_high'] += 1
            continue

        # Use best sequence (closest to aposta threshold)
        seq = min(filtered_seq, key=lambda x: abs(x['distance_mean'] - APOSTA_THRESHOLD))

        hit = hit_rank <= APOSTA_THRESHOLD
        first = hit_rank == 1
        pattern = seq['pattern']

        # Update stats
        stats['total']['hits'] += hit
        stats['total']['count'] += 1
        stats['total']['first'] += first

        if 'auto' in roulette:
            stats['auto']['hits'] += hit
            stats['auto']['count'] += 1
            stats['auto']['first'] += first
        else:
            stats['brazilian']['hits'] += hit
            stats['brazilian']['count'] += 1
            stats['brazilian']['first'] += first

        pattern_stats[pattern]['hits'] += hit
        pattern_stats[pattern]['count'] += 1
        pattern_stats[pattern]['first'] += first

        detail_items.append({
            'snapshot_id': snapshot_id,
            'roulette': roulette,
            'hit_rank': hit_rank,
            'hit': hit,
            'pattern': pattern,
            'distance_mean': seq['distance_mean'],
            'positions': seq['positions'],
        })

    except Exception as e:
        print(f"Error: {e}")
        continue

print("=" * 80)
print("ESTRATÉGIA: 2 FRIOS + THRESHOLD 14 + FILTRO DISTÂNCIA 14-16")
print("=" * 80)
print()

# Summary
total = stats['total']['count']
auto = stats['auto']['count']
brazilian = stats['brazilian']['count']

print(f"📊 RESUMO GERAL")
print(f"  Total de apostas: {total}")
print(f"    → Auto-roulette: {auto}")
print(f"    → Brazilian: {brazilian}")
print()

# Acceptance rate
all_items = len([i for i in items if i.get('ranking_full') and i.get('hit_rank') is not None])
acceptance_rate = (total / all_items * 100) if all_items > 0 else 0
print(f"📈 Taxa de aceitação: {total}/{all_items} ({acceptance_rate:.1f}%)")
print(f"   Rejeitadas por distância: {rejected_stats['distance_too_low'] + rejected_stats['distance_too_high']}")
print()

# Results
if stats['total']['count'] > 0:
    total_win = (stats['total']['hits'] / stats['total']['count']) * 100
    total_first = (stats['total']['first'] / stats['total']['count']) * 100
    print("🎯 RESULTADOS GERAL")
    print(f"  Acertos: {stats['total']['hits']}/{stats['total']['count']}")
    print(f"  Taxa: {total_win:.1f}%")
    print(f"  1º tentativa: {total_first:.1f}%")
    print()

if stats['auto']['count'] > 0:
    auto_win = (stats['auto']['hits'] / stats['auto']['count']) * 100
    auto_first = (stats['auto']['first'] / stats['auto']['count']) * 100
    print("🎯 AUTO-ROULETTE")
    print(f"  Apostas: {stats['auto']['count']}")
    print(f"  Acertos: {stats['auto']['hits']}")
    print(f"  Taxa: {auto_win:.1f}%")
    print(f"  1º tentativa: {auto_first:.1f}%")
    print()

if stats['brazilian']['count'] > 0:
    brazilian_win = (stats['brazilian']['hits'] / stats['brazilian']['count']) * 100
    brazilian_first = (stats['brazilian']['first'] / stats['brazilian']['count']) * 100
    print("🎯 BRAZILIAN-ROULETTE")
    print(f"  Apostas: {stats['brazilian']['count']}")
    print(f"  Acertos: {stats['brazilian']['hits']}")
    print(f"  Taxa: {brazilian_win:.1f}%")
    print(f"  1º tentativa: {brazilian_first:.1f}%")
    print()

# By pattern
print("=" * 80)
print("POR TIPO DE PADRÃO")
print("=" * 80)
for pattern in ['crescente', 'decrescente', 'estável']:
    s = pattern_stats[pattern]
    if s['count'] > 0:
        win_rate = (s['hits'] / s['count']) * 100
        first_rate = (s['first'] / s['count']) * 100
        print(f"\n{pattern.upper()}:")
        print(f"  Apostas: {s['count']}")
        print(f"  Acertos: {s['hits']}")
        print(f"  Taxa: {win_rate:.1f}%")
        print(f"  1º tentativa: {first_rate:.1f}%")

# Save detailed results
output = {
    'strategy': '2 frios + 14 com filtro distância 14-16',
    'total_apostas': stats['total']['count'],
    'total_hits': stats['total']['hits'],
    'total_rate': (stats['total']['hits'] / stats['total']['count'] * 100) if stats['total']['count'] > 0 else 0,
    'total_first_attempt_rate': (stats['total']['first'] / stats['total']['count'] * 100) if stats['total']['count'] > 0 else 0,
    'auto_roulette': {
        'apostas': stats['auto']['count'],
        'hits': stats['auto']['hits'],
        'rate': (stats['auto']['hits'] / stats['auto']['count'] * 100) if stats['auto']['count'] > 0 else 0,
        'first_attempt_rate': (stats['auto']['first'] / stats['auto']['count'] * 100) if stats['auto']['count'] > 0 else 0,
    },
    'brazilian_roulette': {
        'apostas': stats['brazilian']['count'],
        'hits': stats['brazilian']['hits'],
        'rate': (stats['brazilian']['hits'] / stats['brazilian']['count'] * 100) if stats['brazilian']['count'] > 0 else 0,
        'first_attempt_rate': (stats['brazilian']['first'] / stats['brazilian']['count'] * 100) if stats['brazilian']['count'] > 0 else 0,
    },
    'by_pattern': {
        pattern: {
            'apostas': pattern_stats[pattern]['count'],
            'hits': pattern_stats[pattern]['hits'],
            'rate': (pattern_stats[pattern]['hits'] / pattern_stats[pattern]['count'] * 100) if pattern_stats[pattern]['count'] > 0 else 0,
            'first_attempt_rate': (pattern_stats[pattern]['first'] / pattern_stats[pattern]['count'] * 100) if pattern_stats[pattern]['count'] > 0 else 0,
        }
        for pattern in ['crescente', 'decrescente', 'estável']
    },
    'rejection_stats': {
        'distance_too_low': rejected_stats['distance_too_low'],
        'distance_too_high': rejected_stats['distance_too_high'],
        'no_sequences': rejected_stats['no_sequences'],
    },
    'items': detail_items[:20],  # First 20 items
}

with open('analise_2frios_14_distancia_14_16.json', 'w') as f:
    json.dump(output, f, indent=2)

print("\n✅ Resultados salvos em: analise_2frios_14_distancia_14_16.json")
