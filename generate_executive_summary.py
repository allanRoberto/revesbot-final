#!/usr/bin/env python3
"""Gera um resumo executivo da análise de sugestões."""
import json
from pathlib import Path
from datetime import datetime


def generate_summary(data: dict) -> str:
    """Gera um resumo executivo conciso."""
    summary = data.get('summary', {})
    overall = summary.get('overall_analysis', {})

    lines = []
    lines.append("")
    lines.append("╔" + "═" * 78 + "╗")
    lines.append("║" + " " * 78 + "║")
    lines.append("║" + " RESUMO EXECUTIVO - ANÁLISE DE SUGESTÕES DE ROLETA ".center(78) + "║")
    lines.append("║" + " " * 78 + "║")
    lines.append("╚" + "═" * 78 + "╝")
    lines.append("")

    total_items = summary.get('total_items', 0)
    lines.append(f"📊 AMOSTRA: {total_items:,} sugestões analisadas")
    lines.append("")

    # Por roleta
    lines.append("🎰 RESULTADOS POR ROLETA:")
    lines.append("-" * 80)

    for roulette, info in summary.get('by_roulette', {}).items():
        count = info.get('count', 0)
        lines.append(f"\n   {roulette}")
        lines.append(f"   └─ {count:,} hits correlacionados")

        if 'analysis' in info and 'statistics' in info['analysis']:
            stats = info['analysis']['statistics']
            if stats.get('avg_rank'):
                lines.append(f"      • Média: {stats['avg_rank']:.1f}")
            if stats.get('hits_in_top_10'):
                pct = stats.get('percentage_top_10', 0)
                lines.append(f"      • Top 10: {stats['hits_in_top_10']} ({pct:.1f}%)")

    lines.append("\n" + "-" * 80)
    lines.append("\n📈 ANÁLISE CONSOLIDADA:")
    lines.append("-" * 80)

    if 'statistics' in overall:
        stats = overall['statistics']
        total_hits = stats.get('total_hits', 0)

        lines.append(f"\n   Total de hits: {total_hits:,}")
        lines.append(f"   Ranking médio: {stats.get('avg_rank', 0):.1f}")
        lines.append(f"   Ranking mediano: {stats.get('median_rank', 'N/A')}")
        lines.append(f"   Alcance: {stats.get('min_rank', 'N/A')} - {stats.get('max_rank', 'N/A')}")

        lines.append(f"\n   Taxa de acerto (onde bateu):")
        lines.append(f"      🥇 Top 1: {stats.get('hits_in_top_5', 0)}/5 ({stats.get('percentage_top_5', 0):.1f}%)")
        lines.append(f"      🥈 Top 10: {stats.get('hits_in_top_10', 0)} ({stats.get('percentage_top_10', 0):.1f}%)")
        lines.append(f"      🥉 Top 20: {stats.get('hits_in_top_20', 0)} ({stats.get('percentage_top_20', 0):.1f}%)")

        # Análise qualitativa
        lines.append("\n💡 INTERPRETAÇÃO:")
        lines.append("-" * 80)

        avg = stats.get('avg_rank', 0)
        if avg < 15:
            quality = "EXCELENTE ✓ - Sugestões muito bem posicionadas"
        elif avg < 25:
            quality = "BOA ✓ - Sugestões bem posicionadas"
        elif avg < 37:
            quality = "ACEITÁVEL ~ - Sugestões moderadas"
        else:
            quality = "BAIXA ✗ - Sugestões não são boas preditoras"

        lines.append(f"\n   Qualidade das sugestões: {quality}")

        top_10_pct = stats.get('percentage_top_10', 0)
        if top_10_pct > 30:
            accuracy = "ALTA ✓ - Mais de 30% dos acertos estão no top 10"
        elif top_10_pct > 20:
            accuracy = "MODERADA ~ - 20-30% dos acertos estão no top 10"
        else:
            accuracy = "BAIXA ✗ - Menos de 20% dos acertos estão no top 10"

        lines.append(f"   Concentração nos top 10: {accuracy}")

        if total_items > 0:
            correlation_pct = (total_hits / total_items * 100)
            lines.append(f"\n   Taxa de correlação: {correlation_pct:.1f}% das sugestões encontraram número no ranking")

    lines.append("\n" + "═" * 80)
    lines.append("")
    lines.append(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    lines.append("")

    return "\n".join(lines)


def main():
    filepath = Path("suggestion_hits_3000_analysis.json")

    if not filepath.exists():
        print(f"❌ Arquivo {filepath} não encontrado")
        print("Execute fetch_3000_suggestions_analysis.py primeiro")
        return

    with open(filepath, 'r') as f:
        data = json.load(f)

    summary = generate_summary(data)
    print(summary)

    # Salvar resumo
    summary_path = Path("RESUMO_EXECUTIVO_ANALISE.txt")
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary)

    print(f"✅ Resumo salvo em {summary_path}")


if __name__ == "__main__":
    main()
