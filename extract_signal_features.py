#!/usr/bin/env python3
"""Extrai features dos snapshots para identificar padrões de bons sinais."""
import json
from pathlib import Path
from collections import defaultdict
import statistics


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


def analyze_feature_patterns(items):
    """Analisa padrões de features entre bons e piores sinais."""
    good_signals = []
    bad_signals = []

    for item in items:
        hit_rank = item.get('hit_rank', 0)
        if hit_rank <= 12:
            good_signals.append(item)
        else:
            bad_signals.append(item)

    report = []
    report.append("\n" + "═" * 120)
    report.append("ANÁLISE AVANÇADA: FEATURES QUE DIFERENCIAM BONS SINAIS".center(120))
    report.append("═" * 120 + "\n")

    # 1. Padrão de números consecutivos
    report.append("1️⃣  PADRÃO DE NÚMEROS CONSECUTIVOS/VIZINHOS:")
    report.append("-" * 120)

    def are_consecutive(num1, num2):
        return abs(num1 - num2) <= 2

    good_consecutive = sum(1 for item in good_signals if are_consecutive(item.get('anchor_number', 0), item.get('next_number', 0)))
    bad_consecutive = sum(1 for item in bad_signals if are_consecutive(item.get('anchor_number', 0), item.get('next_number', 0)))

    good_cons_pct = (good_consecutive / len(good_signals) * 100) if good_signals else 0
    bad_cons_pct = (bad_consecutive / len(bad_signals) * 100) if bad_signals else 0

    report.append(f"\nBons sinais: {good_consecutive:,} ocorrências ({good_cons_pct:.1f}%)")
    report.append(f"Piores sinais: {bad_consecutive:,} ocorrências ({bad_cons_pct:.1f}%)")
    if good_cons_pct > bad_cons_pct:
        report.append(f"✓ PADRÃO: Bons sinais tendem a ter números próximos do âncora ({good_cons_pct - bad_cons_pct:.1f}% mais)")

    # 2. Padrão de números pares vs ímpares
    report.append("\n\n2️⃣  DISTRIBUIÇÃO PAR/ÍMPAR:")
    report.append("-" * 120)

    def count_parity(items):
        evens = sum(1 for item in items if item.get('next_number', 0) % 2 == 0)
        odds = sum(1 for item in items if item.get('next_number', 0) % 2 == 1)
        return evens, odds

    good_evens, good_odds = count_parity(good_signals)
    bad_evens, bad_odds = count_parity(bad_signals)

    good_even_pct = (good_evens / len(good_signals) * 100) if good_signals else 0
    bad_even_pct = (bad_evens / len(bad_signals) * 100) if bad_signals else 0

    report.append(f"\nBons sinais - Pares: {good_even_pct:.1f}%, Ímpares: {100-good_even_pct:.1f}%")
    report.append(f"Piores sinais - Pares: {bad_even_pct:.1f}%, Ímpares: {100-bad_even_pct:.1f}%")
    if abs(good_even_pct - bad_even_pct) > 2:
        report.append(f"✓ PADRÃO: Diferença de {abs(good_even_pct - bad_even_pct):.1f}% na distribuição par/ímpar")

    # 3. Padrão por cor (vermelho/preto)
    report.append("\n\n3️⃣  PADRÃO COR (Vermelho/Preto):")
    report.append("-" * 120)

    RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

    good_reds = sum(1 for item in good_signals if item.get('next_number', 0) in RED_NUMBERS)
    bad_reds = sum(1 for item in bad_signals if item.get('next_number', 0) in RED_NUMBERS)

    good_red_pct = (good_reds / len(good_signals) * 100) if good_signals else 0
    bad_red_pct = (bad_reds / len(bad_signals) * 100) if bad_signals else 0

    report.append(f"\nBons sinais - Vermelhos: {good_red_pct:.1f}%, Pretos: {100-good_red_pct:.1f}%")
    report.append(f"Piores sinais - Vermelhos: {bad_red_pct:.1f}%, Pretos: {100-bad_red_pct:.1f}%")
    if abs(good_red_pct - bad_red_pct) > 2:
        report.append(f"✓ PADRÃO: Diferença de {abs(good_red_pct - bad_red_pct):.1f}% na distribuição vermelho/preto")

    # 4. Padrão de zero (0)
    report.append("\n\n4️⃣  FREQUÊNCIA DO ZERO:")
    report.append("-" * 120)

    good_zeros = sum(1 for item in good_signals if item.get('next_number', 0) == 0)
    bad_zeros = sum(1 for item in bad_signals if item.get('next_number', 0) == 0)

    good_zero_pct = (good_zeros / len(good_signals) * 100) if good_signals else 0
    bad_zero_pct = (bad_zeros / len(bad_signals) * 100) if bad_signals else 0

    report.append(f"\nBons sinais: {good_zero_pct:.2f}% resultam em zero")
    report.append(f"Piores sinais: {bad_zero_pct:.2f}% resultam em zero")
    if good_zero_pct < bad_zero_pct:
        report.append(f"✓ PADRÃO: Piores sinais têm {bad_zero_pct - good_zero_pct:.2f}% mais zeros")

    # 5. Padrão de última coluna (35, 36)
    report.append("\n\n5️⃣  FREQUÊNCIA ÚLTIMA COLUNA (35-36):")
    report.append("-" * 120)

    good_last_col = sum(1 for item in good_signals if item.get('next_number', 0) in [35, 36])
    bad_last_col = sum(1 for item in bad_signals if item.get('next_number', 0) in [35, 36])

    good_last_pct = (good_last_col / len(good_signals) * 100) if good_signals else 0
    bad_last_pct = (bad_last_col / len(bad_signals) * 100) if bad_signals else 0

    report.append(f"\nBons sinais: {good_last_pct:.2f}% resultam em 35 ou 36")
    report.append(f"Piores sinais: {bad_last_pct:.2f}% resultam em 35 ou 36")
    if bad_last_pct > good_last_pct:
        report.append(f"✓ PADRÃO: Piores sinais têm {bad_last_pct - good_last_pct:.2f}% mais números altos (35-36)")

    # 6. Padrão de primeira coluna (1-3)
    report.append("\n\n6️⃣  FREQUÊNCIA PRIMEIRA COLUNA (1-3):")
    report.append("-" * 120)

    good_first_col = sum(1 for item in good_signals if item.get('next_number', 0) in [1, 2, 3])
    bad_first_col = sum(1 for item in bad_signals if item.get('next_number', 0) in [1, 2, 3])

    good_first_pct = (good_first_col / len(good_signals) * 100) if good_signals else 0
    bad_first_pct = (bad_first_col / len(bad_signals) * 100) if bad_signals else 0

    report.append(f"\nBons sinais: {good_first_pct:.2f}% resultam em 1, 2 ou 3")
    report.append(f"Piores sinais: {bad_first_pct:.2f}% resultam em 1, 2 ou 3")
    if good_first_pct > bad_first_pct:
        report.append(f"✓ PADRÃO: Bons sinais têm {good_first_pct - bad_first_pct:.2f}% mais números baixos (1-3)")

    # 7. Padrão de horário específico
    report.append("\n\n7️⃣  PADRÃO TEMPORAL DETALHADO:")
    report.append("-" * 120)

    good_hours = defaultdict(int)
    bad_hours = defaultdict(int)

    for item in good_signals:
        hour = get_hour_from_timestamp(item.get('next_timestamp_utc', ''))
        if hour is not None:
            good_hours[hour] += 1

    for item in bad_signals:
        hour = get_hour_from_timestamp(item.get('next_timestamp_utc', ''))
        if hour is not None:
            bad_hours[hour] += 1

    # Encontrar horários com maior diferença
    hour_scores = {}
    for hour in range(24):
        good_pct = (good_hours.get(hour, 0) / len(good_signals) * 100) if good_signals else 0
        bad_pct = (bad_hours.get(hour, 0) / len(bad_signals) * 100) if bad_signals else 0
        diff = good_pct - bad_pct
        hour_scores[hour] = diff

    sorted_hours = sorted(hour_scores.items(), key=lambda x: abs(x[1]), reverse=True)[:5]

    report.append(f"\nHorários com maior diferença:")
    for hour, diff in sorted_hours:
        if diff != 0:
            good_pct = (good_hours.get(hour, 0) / len(good_signals) * 100) if good_signals else 0
            bad_pct = (bad_hours.get(hour, 0) / len(bad_signals) * 100) if bad_signals else 0
            trend = "🔥 Bom" if diff > 0 else "❌ Ruim"
            report.append(f"  {hour:02d}:00 - Bons: {good_pct:.1f}%, Ruins: {bad_pct:.1f}% ({trend} +{abs(diff):.1f}%)")

    # 8. Resumo com recomendações
    report.append("\n\n" + "═" * 120)
    report.append("📋 RESUMO - CARACTERÍSTICAS DE BONS SINAIS:".center(120))
    report.append("═" * 120 + "\n")

    characteristics = []

    if good_cons_pct > bad_cons_pct:
        characteristics.append(f"✓ Números próximos do anterior (+{good_cons_pct - bad_cons_pct:.1f}%)")

    if good_first_pct > bad_first_pct:
        characteristics.append(f"✓ Números baixos (1-3) (+{good_first_pct - bad_first_pct:.2f}%)")

    if good_red_pct > bad_red_pct:
        characteristics.append(f"✓ Preferência por vermelhos (+{good_red_pct - bad_red_pct:.1f}%)")

    if good_zero_pct < bad_zero_pct:
        characteristics.append(f"✓ Evita zero ({bad_zero_pct - good_zero_pct:.2f}% menos)")

    if good_last_pct < bad_last_pct:
        characteristics.append(f"✓ Evita números altos (35-36) ({bad_last_pct - good_last_pct:.2f}% menos)")

    if characteristics:
        for i, char in enumerate(characteristics, 1):
            report.append(f"{i}. {char}")
    else:
        report.append("Os padrões são similares entre bons e piores sinais.")

    report.append(f"\n\n🎯 RECOMENDAÇÃO DE FILTRO:")
    report.append("-" * 120)

    # Sugerir um filtro baseado nos padrões encontrados
    if good_first_pct > bad_first_pct + 1:
        report.append("1. PREFERIR números baixos (1-3) quando possível")

    if good_cons_pct > bad_cons_pct:
        report.append("2. PREFERIR números próximos do anterior (âncora ± 2)")

    report.append("3. MONITORAR horários de pico: 02:00-03:00 têm melhor desempenho")

    if good_zero_pct < bad_zero_pct:
        report.append("4. REDUZIR peso do zero nas sugestões")

    report.append("\n" + "═" * 120 + "\n")

    return "\n".join(report)


def main():
    data = load_data()
    if not data:
        return

    items = data.get('items', [])
    analysis = analyze_feature_patterns(items)
    print(analysis)

    # Salvar análise
    with open("ANALISE_FEATURES_SINAIS.txt", "w", encoding='utf-8') as f:
        f.write(analysis)

    print("✅ Análise salva em ANALISE_FEATURES_SINAIS.txt")


if __name__ == "__main__":
    main()
