#!/usr/bin/env python3
"""Gera todos os relatórios da análise de sugestões."""
import json
from pathlib import Path
from datetime import datetime
import sys


def load_data():
    """Carrega os dados do arquivo de análise."""
    filepath = Path("suggestion_hits_3000_analysis.json")
    if not filepath.exists():
        print(f"❌ Arquivo {filepath} não encontrado")
        return None

    with open(filepath, 'r') as f:
        return json.load(f)


def generate_executive_summary(data: dict) -> str:
    """Gera resumo executivo."""
    summary = data.get('summary', {})
    overall = summary.get('overall_analysis', {})

    lines = []
    lines.append("\n" + "═" * 80)
    lines.append("RESUMO EXECUTIVO - ANÁLISE DE SUGESTÕES DE ROLETA".center(80))
    lines.append("═" * 80 + "\n")

    total_items = summary.get('total_items', 0)
    lines.append(f"📊 TOTAL DE SUGESTÕES ANALISADAS: {total_items:,}\n")

    # Por roleta
    lines.append("🎰 RESULTADOS POR ROLETA:")
    lines.append("-" * 80)
    for roulette, info in summary.get('by_roulette', {}).items():
        count = info.get('count', 0)
        lines.append(f"\n{roulette}")
        lines.append(f"  └─ {count:,} hits correlacionados")

        if 'analysis' in info and 'statistics' in info['analysis']:
            stats = info['analysis']['statistics']
            if stats.get('avg_rank'):
                lines.append(f"     • Média: {stats['avg_rank']:.1f}")
                lines.append(f"     • Mediana: {stats.get('median_rank')}")
            pct_10 = stats.get('percentage_top_10', 0)
            lines.append(f"     • Top 10: {pct_10:.1f}%")

    lines.append("\n" + "-" * 80)
    lines.append("\n📈 ANÁLISE CONSOLIDADA:")
    lines.append("-" * 80 + "\n")

    if 'statistics' in overall:
        stats = overall['statistics']
        total_hits = stats.get('total_hits', 0)

        lines.append(f"Total de hits: {total_hits:,}")
        avg = stats.get('avg_rank')
        if avg:
            lines.append(f"Ranking médio: {avg:.2f}")
        lines.append(f"Ranking mediano: {stats.get('median_rank')}")
        lines.append(f"Alcance: {stats.get('min_rank')} - {stats.get('max_rank')}\n")

        lines.append("TAXA DE ACERTO (onde a sugestão bateu):")
        lines.append(f"  🥇 Top 5: {stats.get('hits_in_top_5', 0)} hits ({stats.get('percentage_top_5', 0):.1f}%)")
        lines.append(f"  🥈 Top 10: {stats.get('hits_in_top_10', 0)} hits ({stats.get('percentage_top_10', 0):.1f}%)")
        lines.append(f"  🥉 Top 20: {stats.get('hits_in_top_20', 0)} hits ({stats.get('percentage_top_20', 0):.1f}%)")

    lines.append("\n" + "═" * 80 + "\n")
    return "\n".join(lines)


def generate_detailed_report(data: dict) -> str:
    """Gera relatório detalhado."""
    summary = data.get('summary', {})
    overall = summary.get('overall_analysis', {})

    lines = []
    lines.append("\n" + "═" * 100)
    lines.append("RELATÓRIO DETALHADO - DISTRIBUIÇÃO DE RANKINGS".center(100))
    lines.append("═" * 100 + "\n")

    if 'statistics' not in overall:
        return "\n".join(lines) + "\n❌ Nenhuma estatística encontrada\n"

    stats = overall['statistics']
    distribution = stats.get('distribution', {})

    if not distribution:
        return "\n".join(lines) + "\n❌ Distribuição não encontrada\n"

    total_hits = stats.get('total_hits', 0)
    max_count = max(int(v) for v in distribution.values()) if distribution else 0
    max_bar_width = 50

    ranks = sorted([int(k) for k in distribution.keys()])
    limit = min(30, len(ranks))

    lines.append("POSIÇÃO DO RANKING → QUANTIDADE DE HITS → VISUALIZAÇÃO")
    lines.append("-" * 100)

    for rank in ranks[:limit]:
        count = distribution.get(str(rank), 0)
        percentage = (count / total_hits * 100) if total_hits > 0 else 0
        bar_width = int((count / max_count * max_bar_width)) if max_count > 0 else 0
        bar = "█" * bar_width

        lines.append(f"Rank {rank:3d} │ {count:4d} hits ({percentage:5.1f}%) │ {bar}")

    lines.append("\n" + "═" * 100)
    lines.append(f"\nGerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")

    return "\n".join(lines)


def main():
    data = load_data()
    if not data:
        return

    # Gerar resumo executivo
    summary = generate_executive_summary(data)
    print(summary)

    with open("RESUMO_EXECUTIVO.txt", "w", encoding='utf-8') as f:
        f.write(summary)
    print("✅ Resumo salvo em RESUMO_EXECUTIVO.txt")

    # Gerar relatório detalhado
    report = generate_detailed_report(data)
    print(report)

    with open("RELATORIO_DETALHADO.txt", "w", encoding='utf-8') as f:
        f.write(report)
    print("✅ Relatório salvo em RELATORIO_DETALHADO.txt")

    # Info
    print(f"\n📄 Arquivos gerados:")
    print(f"   • suggestion_hits_3000_analysis.json (dados completos)")
    print(f"   • RESUMO_EXECUTIVO.txt")
    print(f"   • RELATORIO_DETALHADO.txt")


if __name__ == "__main__":
    main()
