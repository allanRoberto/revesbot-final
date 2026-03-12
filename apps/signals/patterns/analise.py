"""
Análise de Roleta - Números que se Puxam
Análise Estatística em 6 Camadas

Réplica exata da lógica JavaScript do HTML
"""

from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass
from collections import Counter


# Números vermelhos da roleta europeia
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

# Ordem física dos números na roda europeia
WHEEL_ORDER = [0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26]


@dataclass
class Methodology:
    """Detalhes da metodologia usada na análise"""
    frequency: List[int]
    anchors: List[int]
    chains: List[int]
    terminals: List[int]
    zero_pattern: List[int]
    all_triggers: List[int]


@dataclass
class AnalysisResult:
    """Resultado completo da análise"""
    final_group: List[int]
    main_triggers: List[int]
    secondary_triggers: List[int]
    confidence_score: float
    methodology: Methodology
    frequencies: Dict[int, float]
    
    @property
    def coverage(self) -> float:
        return (len(self.final_group) / 37) * 100
    
    @property
    def total_triggers(self) -> int:
        return len(self.main_triggers) + len(self.secondary_triggers)


def get_number_color(num: int) -> str:
    """Retorna a cor do número na roleta"""
    if num == 0:
        return 'green'
    return 'red' if num in RED_NUMBERS else 'black'


def get_wheel_neighbors(number: int, distance: int = 2) -> List[int]:
    """
    Retorna os vizinhos físicos de um número na roda.
    Réplica exata do JS: usa indexOf e loop de -distance a +distance
    """
    try:
        idx = WHEEL_ORDER.index(number)
    except ValueError:
        return []
    
    neighbors = []
    for i in range(-distance, distance + 1):
        if i != 0:
            neighbor_idx = (idx + i + len(WHEEL_ORDER)) % len(WHEEL_ORDER)
            neighbors.append(WHEEL_ORDER[neighbor_idx])
    
    return neighbors


def analyze_frequency(numbers: List[int]) -> Dict:
    """
    Camada 1: Frequência com decay.
    Réplica exata do JS.
    """
    freq = {i: 0.0 for i in range(37)}
    
    recent_window = min(30, len(numbers))
    recent_set = set(numbers[:recent_window])
    
    # Calcular frequência com decay
    for idx, num in enumerate(numbers):
        weight = 1 / (1 + idx * 0.02)
        freq[num] += weight
    
    # Aplicar penalidade para números recentes
    for num in recent_set:
        freq[num] *= 0.3
    
    # Ordenar por frequência (ordem decrescente)
    sorted_items = sorted(freq.items(), key=lambda x: (-x[1], x[0]))
    sorted_nums = [num for num, _ in sorted_items]
    
    return {
        'frequencies': freq,
        'topNumbers': sorted_nums[:15],
        'hotNumbers': sorted_nums[:8],
        'coldNumbers': sorted_nums[-8:]
    }


def find_anchors(numbers: List[int]) -> List[int]:
    """
    Camada 2: Âncoras estatísticas.
    Réplica exata do JS.
    """
    counts = {}
    
    # JS: for (let i = 0; i < numbers.length - 2; i++)
    for i in range(len(numbers) - 2):
        window = numbers[i:i + 10]
        unique = list(set(window))
        
        for num in unique:
            appearances = window.count(num)
            if appearances >= 2:
                counts[num] = counts.get(num, 0) + 1
    
    # Ordenar por contagem decrescente
    sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [num for num, _ in sorted_items[:6]]


def find_physical_chains(numbers: List[int]) -> List[int]:
    """
    Camada 3: Cadeias físicas.
    Réplica exata do JS.
    """
    chain_scores = {i: 0.0 for i in range(37)}
    
    for i in range(len(numbers) - 1):
        current = numbers[i]
        next_num = numbers[i + 1]
        
        neighbors = get_wheel_neighbors(current, 3)
        if next_num in neighbors:
            chain_scores[current] += 1
            chain_scores[next_num] += 1
            
            for n in neighbors:
                chain_scores[n] += 0.5
    
    sorted_items = sorted(chain_scores.items(), key=lambda x: (-x[1], x[0]))
    return [num for num, _ in sorted_items[:10]]


def find_active_terminals(numbers: List[int]) -> Dict:
    """
    Camada 4: Terminais ativos.
    Réplica exata do JS.
    """
    terminal_counts = {i: 0 for i in range(10)}
    
    # JS usa slice(0, 50)
    for num in numbers[:50]:
        terminal = num % 10
        terminal_counts[terminal] += 1
    
    # Top 3 terminais
    sorted_items = sorted(terminal_counts.items(), key=lambda x: (-x[1], x[0]))
    top_terminals = [t for t, _ in sorted_items[:3]]
    
    # Números que terminam com esses dígitos
    terminal_numbers = []
    for t in top_terminals:
        for i in range(37):
            if i % 10 == t:
                terminal_numbers.append(i)
    
    # Remover duplicatas mantendo ordem
    seen = set()
    unique_terminal_numbers = []
    for n in terminal_numbers:
        if n not in seen:
            seen.add(n)
            unique_terminal_numbers.append(n)
    
    return {
        'topTerminals': top_terminals,
        'terminalNumbers': unique_terminal_numbers
    }


def analyze_zero_behavior(numbers: List[int]) -> List[int]:
    """
    Camada 5: Comportamento do zero.
    Réplica exata do JS.
    """
    after_zero = []
    
    for idx, num in enumerate(numbers):
        # JS: if (num === 0 && idx > 0)
        if num == 0 and idx > 0:
            # JS: numbers.slice(idx + 1, idx + 4) - pega 3 números DEPOIS do zero na lista
            before = numbers[idx + 1:idx + 4]
            after_zero.extend(before)
    
    # Contar frequência
    counts = Counter(after_zero)
    sorted_items = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [num for num, _ in sorted_items[:5]]


def define_triggers(candidates: List[int], numbers: List[int]) -> Tuple[List[int], List[int]]:
    """
    Camada 6: Gatilhos.
    Réplica exata do JS - mantém ordem de inserção como JS Set.
    """
    last_20 = set(numbers[:20])
    
    # Gatilhos principais
    main_triggers = [n for n in candidates if n in last_20][:3]
    
    # Gatilhos secundários - manter ordem de inserção como JS Set
    secondary_ordered = []
    seen = set()
    
    for t in main_triggers:
        for n in get_wheel_neighbors(t, 2):
            if n not in seen:
                seen.add(n)
                secondary_ordered.append(n)
    
    # Remover os que são gatilhos principais
    secondary_triggers = [n for n in secondary_ordered if n not in main_triggers][:3]
    
    return main_triggers, secondary_triggers


def run_full_analysis(numbers: List[int]) -> AnalysisResult:
    """
    Executa análise completa.
    Réplica exata do JS runFullAnalysis.
    """
    if len(numbers) < 50:
        raise ValueError("Dados insuficientes para análise (mínimo 50 números)")
    
    # Camada 1: Frequência
    freq_analysis = analyze_frequency(numbers)
    
    # Camada 2: Âncoras
    anchors = find_anchors(numbers)
    
    # Camada 3: Cadeias físicas
    chains = find_physical_chains(numbers)
    
    # Camada 4: Terminais
    terminals = find_active_terminals(numbers)
    
    # Camada 5: Zero
    zero_pattern = analyze_zero_behavior(numbers)
    
    # Combinar candidatos - EXATAMENTE como no JS
    all_candidates = (
        freq_analysis['hotNumbers'] +
        anchors +
        chains +
        terminals['terminalNumbers'][:5] +
        zero_pattern
    )
    
    # Pontuar candidatos
    scores = {}
    for num in all_candidates:
        scores[num] = scores.get(num, 0) + 1
    
    # Ordenar por score (JS: sort((a, b) => b[1] - a[1]))
    # No JS, quando scores são iguais, a ordem original do objeto é mantida
    # Vamos ordenar por score decrescente, depois por número
    sorted_scores = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    candidates = [num for num, _ in sorted_scores[:20]]
    
    # Expandir com vizinhos - usando SET como no JS
    expanded = set(candidates)
    for num in candidates[:6]:
        for n in get_wheel_neighbors(num, 1):
            expanded.add(n)
    
    # IMPORTANTE: No JS, [...expanded] mantém ordem de inserção do Set
    # Em Python, set não mantém ordem, então precisamos replicar o comportamento
    # O JS adiciona primeiro os candidates, depois os vizinhos
    expanded_ordered = []
    seen = set()
    
    # Primeiro adiciona os candidates
    for num in candidates:
        if num not in seen:
            seen.add(num)
            expanded_ordered.append(num)
    
    # Depois adiciona vizinhos dos 6 primeiros
    for num in candidates[:6]:
        for n in get_wheel_neighbors(num, 1):
            if n not in seen:
                seen.add(n)
                expanded_ordered.append(n)
    
    # Grupo final (9-13 números)
    final_group = expanded_ordered[:11]
    
    if len(final_group) < 9:
        for c in candidates:
            if c not in final_group and len(final_group) < 12:
                final_group.append(c)
    
    # Camada 6: Gatilhos
    main_triggers, secondary_triggers = define_triggers(final_group, numbers)
    
    # Calcular score de confiança
    confidence_score = 50.0
    
    anchors_in_group = len([a for a in anchors if a in final_group])
    confidence_score += anchors_in_group * 5
    
    chains_in_group = len([c for c in chains if c in final_group])
    confidence_score += chains_in_group * 3
    
    confidence_score += len(terminals['topTerminals']) * 4
    
    confidence_score = max(30, min(95, confidence_score))
    
    # Ordenar grupo final
    final_group_sorted = sorted(final_group)
    
    methodology = Methodology(
        frequency=freq_analysis['hotNumbers'],
        anchors=anchors,
        chains=chains[:5],
        terminals=terminals['topTerminals'],
        zero_pattern=zero_pattern,
        all_triggers=main_triggers + secondary_triggers
    )
    
    return AnalysisResult(
        final_group=final_group_sorted,
        main_triggers=main_triggers,
        secondary_triggers=secondary_triggers,
        confidence_score=confidence_score,
        methodology=methodology,
        frequencies=freq_analysis['frequencies']
    )


def format_analysis_report(analysis: AnalysisResult, total_numbers: int) -> str:
    """Formata o resultado em relatório legível."""
    lines = [
        "=" * 60,
        "  ANÁLISE DE ROLETA - NÚMEROS QUE SE PUXAM",
        "=" * 60,
        "",
        f"📊 Números Analisados: {total_numbers}",
        f"🎯 Tamanho do Grupo: {len(analysis.final_group)}",
        f"🔔 Total de Gatilhos: {analysis.total_triggers}",
        f"📈 Cobertura: {analysis.coverage:.1f}%",
        "",
        "-" * 60,
        "  GRUPO IDENTIFICADO",
        "-" * 60,
        f"  {', '.join(map(str, analysis.final_group))}",
        "",
        "-" * 60,
        "  GATILHOS",
        "-" * 60,
        f"  Principais: {', '.join(map(str, analysis.main_triggers)) or 'N/A'}",
        f"  Secundários: {', '.join(map(str, analysis.secondary_triggers)) or 'N/A'}",
        "",
        "-" * 60,
        "  METODOLOGIA (6 CAMADAS)",
        "-" * 60,
        f"  1. Frequência & Decay: {', '.join(map(str, analysis.methodology.frequency[:4]))}",
        f"  2. Âncoras Estatísticas: {', '.join(map(str, analysis.methodology.anchors[:3]))}",
        f"  3. Cadeias Físicas: {', '.join(map(str, analysis.methodology.chains[:3]))}",
        f"  4. Terminais Ativos: T{', T'.join(map(str, analysis.methodology.terminals))}",
        f"  5. Padrão do Zero: {', '.join(map(str, analysis.methodology.zero_pattern[:3])) or 'N/A'}",
        f"  6. Gatilhos: {', '.join(map(str, analysis.methodology.all_triggers))}",
        "",
        "-" * 60,
        f"  SCORE DE CONFIANÇA: {analysis.confidence_score:.1f}/100",
        "-" * 60,
    ]
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Teste
    sample = [
        17, 32, 15, 0, 26, 3, 35, 12, 28, 7,
        29, 18, 22, 9, 31, 14, 20, 1, 33, 16,
        24, 5, 10, 23, 8, 30, 11, 36, 13, 27,
        6, 34, 17, 25, 2, 21, 4, 19, 15, 32,
        0, 26, 3, 35, 12, 28, 7, 29, 18, 22,
        9, 31, 14, 20, 1, 33, 16, 24, 5, 10
    ]
    
    result = run_full_analysis(sample)
    print(format_analysis_report(result, len(sample)))