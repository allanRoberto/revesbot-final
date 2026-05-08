#!/usr/bin/env python3
"""Classifica sinais por qualidade baseado em features identificadas."""
import json
from pathlib import Path
from collections import defaultdict


def load_data():
    """Carrega os dados da análise."""
    filepath = Path("suggestion_hits_3000_analysis.json")
    if not filepath.exists():
        print(f"❌ Arquivo {filepath} não encontrado")
        return None

    with open(filepath, 'r') as f:
        return json.load(f)


def get_hour_from_timestamp(ts):
    """Extrai hora do timestamp."""
    if 'T' in ts:
        time_part = ts.split('T')[1]
        if ':' in time_part:
            return int(time_part.split(':')[0])
    return None


RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}


def score_signal(item):
    """Atribui score de qualidade para cada sinal."""
    score = 0
    reasons = []

    anchor_num = item.get('anchor_number', 0)
    next_num = item.get('next_number', 0)
    timestamp = item.get('next_timestamp_utc', '')
    hit_rank = item.get('hit_rank', 0)
    ranking_size = item.get('ranking_size', 37)

    # Feature 1: Números próximos (±2)
    if abs(anchor_num - next_num) <= 2:
        score += 2
        reasons.append("Número próximo do anterior")

    # Feature 2: Números baixos (1-3)
    if next_num in [1, 2, 3]:
        score += 3
        reasons.append("Número baixo (1-3)")

    # Feature 3: Preferência por vermelhos
    if next_num in RED_NUMBERS:
        score += 1
        reasons.append("Número vermelho")

    # Feature 4: Evita zero
    if next_num == 0:
        score -= 1
        reasons.insert(0, "⚠️ É o zero (penalidade)")

    # Feature 5: Evita números altos (35-36)
    if next_num in [35, 36]:
        score -= 1
        reasons.insert(0, "⚠️ Número muito alto (penalidade)")

    # Feature 6: Horários de pico
    hour = get_hour_from_timestamp(timestamp)
    if hour is not None:
        if hour in [2, 3, 12]:  # Horários bons identificados
            score += 1
            reasons.append(f"Horário bom ({hour:02d}:00)")
        elif hour in [1, 20, 16]:  # Horários ruins identificados
            score -= 1
            reasons.insert(0, f"⚠️ Horário ruim ({hour:02d}:00)")

    # Feature 7: Tamanho do ranking (quanto maior, melhor)
    if ranking_size >= 37:
        score += 1
        reasons.append("Ranking completo")

    return score, reasons


def classify_signal(score):
    """Classifica sinal baseado no score."""
    if score >= 5:
        return "🌟 EXCELENTE"
    elif score >= 3:
        return "✅ BOM"
    elif score >= 1:
        return "🟡 ACEITÁVEL"
    else:
        return "❌ FRACO"


def main():
    data = load_data()
    if not data:
        return

    items = data.get('items', [])

    # Classificar todos os sinais
    classified_items = []
    quality_dist = defaultdict(int)
    score_dist = defaultdict(int)

    for item in items:
        score, reasons = score_signal(item)
        quality = classify_signal(score)
        hit_rank = item.get('hit_rank', 0)

        classified_items.append({
            'item': item,
            'score': score,
            'quality': quality,
            'reasons': reasons,
            'hit_rank': hit_rank
        })

        quality_dist[quality] += 1
        score_dist[score] += 1

    # Gerar relatório
    report = []
    report.append("\n" + "═" * 120)
    report.append("CLASSIFICAÇÃO DE SINAIS POR QUALIDADE".center(120))
    report.append("═" * 120 + "\n")

    # Distribuição de qualidade
    report.append("📊 DISTRIBUIÇÃO DE QUALIDADE:")
    report.append("-" * 120)

    total = len(classified_items)
    for quality in ["🌟 EXCELENTE", "✅ BOM", "🟡 ACEITÁVEL", "❌ FRACO"]:
        count = quality_dist.get(quality, 0)
        pct = (count / total * 100) if total > 0 else 0
        bar = "█" * int(pct / 2)
        report.append(f"\n{quality:20s}: {count:4d} ({pct:5.1f}%) {bar}")

    # Análise por score
    report.append(f"\n\n\n📈 DISTRIBUIÇÃO POR SCORE:")
    report.append("-" * 120)

    for score in sorted(score_dist.keys()):
        count = score_dist[score]
        pct = (count / total * 100) if total > 0 else 0
        report.append(f"Score {score:2d}: {count:4d} sinais ({pct:5.1f}%)")

    # Comparação: qualidade vs hit_rank
    report.append(f"\n\n\n🎯 ANÁLISE: QUALIDADE vs RANKING REAL (HIT RANK):")
    report.append("-" * 120)

    quality_ranks = defaultdict(list)
    for item in classified_items:
        quality = item['quality']
        hit_rank = item['hit_rank']
        quality_ranks[quality].append(hit_rank)

    for quality in ["🌟 EXCELENTE", "✅ BOM", "🟡 ACEITÁVEL", "❌ FRACO"]:
        ranks = quality_ranks.get(quality, [])
        if ranks:
            avg_rank = sum(ranks) / len(ranks)
            min_rank = min(ranks)
            max_rank = max(ranks)
            report.append(f"\n{quality}:")
            report.append(f"  Ranking médio real: {avg_rank:.2f}")
            report.append(f"  Range: {min_rank} - {max_rank}")
            report.append(f"  Quantidade: {len(ranks)}")

    # Exemplos de cada categoria
    report.append(f"\n\n\n📋 EXEMPLOS POR CATEGORIA:")
    report.append("-" * 120)

    for quality in ["🌟 EXCELENTE", "✅ BOM", "🟡 ACEITÁVEL", "❌ FRACO"]:
        examples = [item for item in classified_items if item['quality'] == quality][:3]

        if examples:
            report.append(f"\n{quality} (mostrando 3 exemplos):")
            for i, example in enumerate(examples, 1):
                item = example['item']
                report.append(f"\n  Exemplo {i}:")
                report.append(f"    Âncora: {item.get('anchor_number')} → Resultado: {item.get('next_number')}")
                report.append(f"    Hit Rank (real): {example['hit_rank']}")
                report.append(f"    Score (predito): {example['score']}")
                report.append(f"    Razões: {'; '.join(example['reasons']) if example['reasons'] else 'Nenhum fator especial'}")

    # Recomendações finais
    report.append(f"\n\n\n" + "═" * 120)
    report.append("💡 RECOMENDAÇÕES PRÁTICAS".center(120))
    report.append("═" * 120 + "\n")

    excellent_count = quality_dist.get("🌟 EXCELENTE", 0)
    good_count = quality_dist.get("✅ BOM", 0)
    excellent_pct = (excellent_count / total * 100) if total > 0 else 0
    good_pct = (good_count / total * 100) if total > 0 else 0

    report.append(f"1. ESTRATÉGIA CONSERVADORA:")
    report.append(f"   └─ Usar apenas sinais EXCELENTES ({excellent_count:,} / {total:,})")
    report.append(f"   └─ Representa {excellent_pct:.1f}% das sugestões")
    report.append(f"   └─ Espera-se melhor taxa de acerto nos top 5")

    report.append(f"\n2. ESTRATÉGIA BALANCEADA:")
    report.append(f"   └─ Usar EXCELENTES + BONS ({excellent_count + good_count:,} / {total:,})")
    report.append(f"   └─ Representa {excellent_pct + good_pct:.1f}% das sugestões")
    report.append(f"   └─ Bom equilíbrio entre quantidade e qualidade")

    report.append(f"\n3. ANÁLISE POR HORÁRIO:")
    report.append(f"   └─ Filtrar por horários: 02:00-03:00 e 12:00 têm sinais melhores")
    report.append(f"   └─ Evitar: 01:00, 16:00, 20:00")

    report.append(f"\n4. ANÁLISE POR NÚMERO:")
    report.append(f"   └─ Preferir baixos (1-3): +3.36% de melhoria")
    report.append(f"   └─ Evitar zero e números altos (35-36)")
    report.append(f"   └─ Preferir vermelhos: +1.7% de melhoria")

    report.append(f"\n5. COMBINAÇÃO IDEAL:")
    report.append(f"   └─ Score >= 3 (BOM)")
    report.append(f"   └─ Horário: 02:00-03:00 ou 12:00")
    report.append(f"   └─ Número: 1-3 E vermelho")
    report.append(f"   └─ Evitar: zero, 35-36")

    report.append("\n" + "═" * 120 + "\n")

    return "\n".join(report), classified_items


if __name__ == "__main__":
    report, classified_items = main()
    print(report)

    # Salvar relatório
    with open("CLASSIFICACAO_SINAIS_QUALIDADE.txt", "w", encoding='utf-8') as f:
        f.write(report)

    # Salvar dados classificados em JSON
    output_data = {
        'total_signals': len(classified_items),
        'classified_signals': [
            {
                'snapshot_id': item['item'].get('snapshot_id'),
                'roulette_id': item['item'].get('roulette_id'),
                'score': item['score'],
                'quality': item['quality'],
                'reasons': item['reasons'],
                'actual_hit_rank': item['hit_rank'],
                'anchor_number': item['item'].get('anchor_number'),
                'next_number': item['item'].get('next_number'),
            }
            for item in classified_items
        ]
    }

    with open("signals_classified.json", "w") as f:
        json.dump(output_data, f, indent=2, default=str)

    print("\n✅ Relatório salvo em CLASSIFICACAO_SINAIS_QUALIDADE.txt")
    print("✅ Dados classificados salvos em signals_classified.json")
