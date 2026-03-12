#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    ROULETTE STATISTICAL ANALYZER v1.0                        ║
║                                                                              ║
║  Sistema de análise estatística para identificação de zonas concentradas    ║
║  em históricos de roleta europeia.                                          ║
║                                                                              ║
║  ⚠️  ESTUDO ESTATÍSTICO EDUCATIVO - NÃO GARANTE RESULTADOS                  ║
╚══════════════════════════════════════════════════════════════════════════════╝

Metodologia implementada:
1. Repetição de Exatos (frequência em janelas curtas/médias)
2. Âncoras Numéricas (central, sustentação, retorno)
3. Chain/Vizinhança Física da Roleta
4. Análise de Terminais
5. Alternância de Terminais
6. Tratamento especial do Zero

Autor: Sistema de Análise Estatística
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple
import statistics


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTES E CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════════════════

# Ordem física da roleta europeia (sentido horário começando do zero)
EUROPEAN_WHEEL_ORDER: List[int] = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
    5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26
]

# Mapeamento de posição física para cada número
WHEEL_POSITION: Dict[int, int] = {num: idx for idx, num in enumerate(EUROPEAN_WHEEL_ORDER)}

# Quantidade total de números na roleta europeia
TOTAL_NUMBERS = 37


class AnchorType(Enum):
    """Tipos de âncoras numéricas."""
    CENTRAL = "central"          # Número mais recorrente
    SUSTENTACAO = "sustentacao"  # Conecta outros números
    RETORNO = "retorno"          # Reaparece após ausência


@dataclass
class NumberStats:
    """Estatísticas detalhadas de um número."""
    number: int
    total_frequency: int = 0
    frequency_short: int = 0      # Janela curta (últimos 30)
    frequency_medium: int = 0     # Janela média (últimos 80)
    recency_score: float = 0.0    # Pontuação por recência
    chain_score: float = 0.0      # Pontuação por vizinhança
    terminal_score: float = 0.0   # Pontuação por terminal
    anchor_type: Optional[AnchorType] = None
    anchor_strength: float = 0.0
    positions: List[int] = field(default_factory=list)  # Posições onde apareceu
    
    @property
    def combined_score(self) -> float:
        """Score combinado ponderado."""
        # Pesos calibrados baseados na metodologia aprendida
        weights = {
            'frequency_total': 2.0,      # Frequência total importante
            'frequency_short': 4.0,      # Janela curta tem peso maior
            'frequency_medium': 2.0,     # Janela média
            'recency': 3.0,              # Recência muito importante
            'chain': 1.5,                # Vizinhança física
            'terminal': 1.2,             # Terminais como conectores
            'anchor': 2.5                # Âncoras importantes
        }
        
        # Normalização para evitar dominância de uma métrica
        freq_score = (
            self.total_frequency * weights['frequency_total'] +
            self.frequency_short * weights['frequency_short'] +
            self.frequency_medium * weights['frequency_medium']
        )
        
        score = (
            freq_score +
            self.recency_score * weights['recency'] +
            self.chain_score * weights['chain'] +
            self.terminal_score * weights['terminal'] +
            self.anchor_strength * weights['anchor']
        )
        return score
    
    @property
    def is_strong_candidate(self) -> bool:
        """Verifica se é candidato forte (≥5 repetições)."""
        return self.total_frequency >= 5
    
    @property
    def is_radar_candidate(self) -> bool:
        """Verifica se entra no radar (≥3 repetições)."""
        return self.total_frequency >= 3


@dataclass
class TerminalGroup:
    """Grupo de números com mesmo terminal."""
    terminal: int
    numbers: List[int] = field(default_factory=list)
    frequency: int = 0
    recent_activity: float = 0.0
    alternation_detected: bool = False


@dataclass
class ChainCluster:
    """Cluster de números por vizinhança física."""
    center: int
    members: Set[int] = field(default_factory=set)
    strength: float = 0.0
    span: int = 0  # Quantidade de posições consecutivas


@dataclass
class AnalysisResult:
    """Resultado completo da análise."""
    final_group: List[int]
    main_triggers: List[int]
    secondary_triggers: List[int]
    number_stats: Dict[int, NumberStats]
    terminal_groups: Dict[int, TerminalGroup]
    chain_clusters: List[ChainCluster]
    zero_analysis: Dict
    confidence_score: float


# ══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES AUXILIARES - VIZINHANÇA FÍSICA
# ══════════════════════════════════════════════════════════════════════════════

def get_wheel_neighbors(number: int, distance: int = 1) -> List[int]:
    """
    Retorna vizinhos físicos de um número na roleta.
    
    Args:
        number: Número central
        distance: Distância de vizinhança (1 = diretos, 2 = segundo nível)
    
    Returns:
        Lista de vizinhos ordenados por proximidade
    """
    if number not in WHEEL_POSITION:
        return []
    
    pos = WHEEL_POSITION[number]
    neighbors = []
    
    for d in range(1, distance + 1):
        # Vizinho à esquerda
        left_pos = (pos - d) % len(EUROPEAN_WHEEL_ORDER)
        neighbors.append(EUROPEAN_WHEEL_ORDER[left_pos])
        
        # Vizinho à direita
        right_pos = (pos + d) % len(EUROPEAN_WHEEL_ORDER)
        neighbors.append(EUROPEAN_WHEEL_ORDER[right_pos])
    
    return neighbors


def get_wheel_distance(num1: int, num2: int) -> int:
    """
    Calcula distância física entre dois números na roleta.
    
    Returns:
        Menor distância (pode ir por qualquer lado da roleta)
    """
    if num1 not in WHEEL_POSITION or num2 not in WHEEL_POSITION:
        return TOTAL_NUMBERS  # Máxima distância se inválido
    
    pos1 = WHEEL_POSITION[num1]
    pos2 = WHEEL_POSITION[num2]
    
    direct = abs(pos1 - pos2)
    wraparound = len(EUROPEAN_WHEEL_ORDER) - direct
    
    return min(direct, wraparound)


def get_terminal(number: int) -> int:
    """Retorna o terminal (último dígito) de um número."""
    return number % 10


def get_terminal_family(terminal: int) -> List[int]:
    """Retorna todos os números com determinado terminal."""
    return [n for n in range(37) if get_terminal(n) == terminal]


# ══════════════════════════════════════════════════════════════════════════════
# CLASSE PRINCIPAL DO ANALISADOR
# ══════════════════════════════════════════════════════════════════════════════

class RouletteAnalyzer:
    """
    Analisador estatístico de histórico de roleta.
    
    Implementa metodologia multicamadas para identificação de zonas
    estatisticamente concentradas.
    """
    
    # Configurações de janelas de análise
    WINDOW_SHORT = 30
    WINDOW_MEDIUM = 80
    
    # Limiares para classificação
    THRESHOLD_RADAR = 3      # Mínimo para entrar no radar
    THRESHOLD_STRONG = 5     # Candidato forte a âncora
    
    # Configurações de output
    MIN_GROUP_SIZE = 9
    MAX_GROUP_SIZE = 13
    TARGET_GROUP_SIZE = 12
    NUM_MAIN_TRIGGERS = 3
    MAX_SECONDARY_TRIGGERS = 2
    
    def __init__(self, history: List[int]):
        """
        Inicializa o analisador com histórico.
        
        Args:
            history: Lista de números (índice 0 = mais recente)
        """
        self.history = self._validate_history(history)
        self.history_length = len(self.history)
        
        # Estruturas de análise
        self.number_stats: Dict[int, NumberStats] = {
            n: NumberStats(number=n) for n in range(37)
        }
        self.terminal_groups: Dict[int, TerminalGroup] = {
            t: TerminalGroup(terminal=t, numbers=get_terminal_family(t))
            for t in range(10)
        }
        self.chain_clusters: List[ChainCluster] = []
        self.zero_analysis: Dict = {}
        
    def _validate_history(self, history: List[int]) -> List[int]:
        """Valida e limpa o histórico de entrada."""
        validated = []
        for num in history:
            if isinstance(num, (int, float)):
                num_int = int(num)
                if 0 <= num_int <= 36:
                    validated.append(num_int)
        return validated
    
    # ══════════════════════════════════════════════════════════════════════════
    # CAMADA 1: REPETIÇÃO DE EXATOS
    # ══════════════════════════════════════════════════════════════════════════
    
    def analyze_frequency(self) -> None:
        """
        Analisa frequência de números em diferentes janelas.
        
        - Janela curta: últimos 30 giros
        - Janela média: últimos 80 giros
        - Peso maior para repetições recentes e em blocos curtos
        """
        # Frequência total
        total_counts = Counter(self.history)
        
        # Janela curta
        short_window = self.history[:self.WINDOW_SHORT]
        short_counts = Counter(short_window)
        
        # Janela média
        medium_window = self.history[:self.WINDOW_MEDIUM]
        medium_counts = Counter(medium_window)
        
        for num in range(37):
            stats = self.number_stats[num]
            stats.total_frequency = total_counts.get(num, 0)
            stats.frequency_short = short_counts.get(num, 0)
            stats.frequency_medium = medium_counts.get(num, 0)
            
            # Registrar posições onde o número apareceu
            stats.positions = [i for i, n in enumerate(self.history) if n == num]
    
    def calculate_recency_scores(self) -> None:
        """
        Calcula pontuação por recência.
        
        Números que aparecem mais recentemente recebem pontuação maior.
        Usa decay exponencial baseado na posição.
        """
        decay_factor = 0.97  # Fator de decaimento por posição
        
        for num in range(37):
            stats = self.number_stats[num]
            score = 0.0
            
            for pos in stats.positions:
                # Peso decai exponencialmente com a distância
                weight = decay_factor ** pos
                score += weight
            
            # Bônus para repetições em blocos curtos (últimos 15 giros)
            recent_positions = [p for p in stats.positions if p < 15]
            if len(recent_positions) >= 2:
                # Verificar se há repetições próximas
                for i in range(len(recent_positions) - 1):
                    gap = recent_positions[i + 1] - recent_positions[i]
                    if gap <= 5:  # Repetição muito próxima
                        score += 1.5
                    elif gap <= 10:
                        score += 0.8
            
            stats.recency_score = score
    
    # ══════════════════════════════════════════════════════════════════════════
    # CAMADA 2: ÂNCORAS NUMÉRICAS
    # ══════════════════════════════════════════════════════════════════════════
    
    def identify_anchors(self) -> None:
        """
        Identifica e classifica âncoras numéricas.
        
        - Âncora central: número mais recorrente
        - Âncora de sustentação: conecta outros números frequentes
        - Âncora de retorno: reaparece após período de ausência
        """
        # Ordenar por frequência total
        sorted_by_freq = sorted(
            [(n, s.total_frequency) for n, s in self.number_stats.items()],
            key=lambda x: x[1],
            reverse=True
        )
        
        # Identificar âncora central (mais frequente)
        if sorted_by_freq[0][1] >= self.THRESHOLD_STRONG:
            central_num = sorted_by_freq[0][0]
            self.number_stats[central_num].anchor_type = AnchorType.CENTRAL
            self.number_stats[central_num].anchor_strength = 3.0
        
        # Identificar âncoras de sustentação
        self._identify_sustentation_anchors()
        
        # Identificar âncoras de retorno
        self._identify_return_anchors()
    
    def _identify_sustentation_anchors(self) -> None:
        """
        Identifica âncoras de sustentação.
        
        São números que frequentemente aparecem próximos (no tempo)
        de outros números frequentes, funcionando como conectores.
        """
        # Pegar os top 10 números mais frequentes
        top_frequent = sorted(
            [(n, s.total_frequency) for n, s in self.number_stats.items()],
            key=lambda x: x[1],
            reverse=True
        )[:10]
        top_numbers = {n for n, _ in top_frequent}
        
        connection_count: Dict[int, int] = defaultdict(int)
        
        # Para cada número, contar quantas vezes aparece perto de outros top
        for num, stats in self.number_stats.items():
            if stats.total_frequency < self.THRESHOLD_RADAR:
                continue
                
            for pos in stats.positions:
                # Verificar janela de ±3 posições
                for offset in range(-3, 4):
                    if offset == 0:
                        continue
                    check_pos = pos + offset
                    if 0 <= check_pos < self.history_length:
                        neighbor_num = self.history[check_pos]
                        if neighbor_num in top_numbers and neighbor_num != num:
                            connection_count[num] += 1
        
        # Números com muitas conexões são âncoras de sustentação
        if connection_count:
            max_connections = max(connection_count.values())
            threshold = max_connections * 0.7
            
            for num, count in connection_count.items():
                stats = self.number_stats[num]
                if count >= threshold and stats.anchor_type is None:
                    stats.anchor_type = AnchorType.SUSTENTACAO
                    stats.anchor_strength = 2.0 + (count / max_connections)
    
    def _identify_return_anchors(self) -> None:
        """
        Identifica âncoras de retorno.
        
        São números que aparecem, ficam ausentes por um período,
        e depois retornam com força.
        """
        for num in range(37):
            stats = self.number_stats[num]
            
            if len(stats.positions) < 3:
                continue
            
            # Verificar padrão de ausência seguida de retorno
            gaps = []
            for i in range(len(stats.positions) - 1):
                gap = stats.positions[i + 1] - stats.positions[i]
                gaps.append(gap)
            
            if not gaps:
                continue
                
            avg_gap = statistics.mean(gaps)
            
            # Verificar se há um gap grande seguido de aparições frequentes
            for i, gap in enumerate(gaps):
                if gap > avg_gap * 2:  # Gap significativo
                    # Verificar se após o gap há atividade intensa
                    remaining_positions = stats.positions[:i+1]
                    if len(remaining_positions) >= 2:
                        recent_gaps = [
                            remaining_positions[j+1] - remaining_positions[j]
                            for j in range(len(remaining_positions) - 1)
                        ]
                        if recent_gaps and statistics.mean(recent_gaps) < avg_gap * 0.5:
                            if stats.anchor_type is None:
                                stats.anchor_type = AnchorType.RETORNO
                                stats.anchor_strength = 1.8
                            break
    
    # ══════════════════════════════════════════════════════════════════════════
    # CAMADA 3: CHAIN (VIZINHANÇA FÍSICA)
    # ══════════════════════════════════════════════════════════════════════════
    
    def analyze_chains(self) -> None:
        """
        Analisa cadeias de vizinhança física na roleta.
        
        Quando um número aparece, verifica se seus vizinhos físicos
        também têm atividade recente.
        """
        # Calcular score de chain para cada número
        for num in range(37):
            stats = self.number_stats[num]
            chain_score = 0.0
            
            # Vizinhos diretos (distância 1)
            direct_neighbors = get_wheel_neighbors(num, distance=1)
            for neighbor in direct_neighbors:
                neighbor_stats = self.number_stats[neighbor]
                # Score baseado na frequência do vizinho
                chain_score += neighbor_stats.frequency_short * 1.5
                chain_score += neighbor_stats.frequency_medium * 0.5
            
            # Vizinhos de segundo nível (distância 2)
            second_neighbors = get_wheel_neighbors(num, distance=2)
            for neighbor in second_neighbors[2:]:  # Pular os diretos que já foram contados
                neighbor_stats = self.number_stats[neighbor]
                chain_score += neighbor_stats.frequency_short * 0.8
                chain_score += neighbor_stats.frequency_medium * 0.3
            
            stats.chain_score = chain_score
        
        # Identificar clusters de chain
        self._identify_chain_clusters()
    
    def _identify_chain_clusters(self) -> None:
        """Identifica clusters de números fisicamente próximos com atividade."""
        visited: Set[int] = set()
        
        # Ordenar números por frequência para começar pelos mais ativos
        active_numbers = sorted(
            [(n, s.frequency_short + s.frequency_medium) 
             for n, s in self.number_stats.items()
             if s.total_frequency >= self.THRESHOLD_RADAR],
            key=lambda x: x[1],
            reverse=True
        )
        
        for num, _ in active_numbers:
            if num in visited:
                continue
            
            # Iniciar novo cluster
            cluster = ChainCluster(center=num)
            cluster.members.add(num)
            
            # Expandir cluster incluindo vizinhos ativos
            self._expand_cluster(cluster, visited)
            
            if len(cluster.members) >= 2:
                # Calcular força do cluster
                cluster.strength = sum(
                    self.number_stats[n].frequency_short + 
                    self.number_stats[n].frequency_medium
                    for n in cluster.members
                )
                
                # Calcular span (posições consecutivas ocupadas)
                positions = sorted([WHEEL_POSITION[n] for n in cluster.members])
                cluster.span = self._calculate_span(positions)
                
                self.chain_clusters.append(cluster)
            
            visited.update(cluster.members)
    
    def _expand_cluster(self, cluster: ChainCluster, visited: Set[int]) -> None:
        """Expande um cluster incluindo vizinhos ativos."""
        to_check = list(cluster.members)
        
        while to_check:
            current = to_check.pop(0)
            neighbors = get_wheel_neighbors(current, distance=2)
            
            for neighbor in neighbors:
                if neighbor in visited or neighbor in cluster.members:
                    continue
                
                neighbor_stats = self.number_stats[neighbor]
                if neighbor_stats.total_frequency >= self.THRESHOLD_RADAR:
                    cluster.members.add(neighbor)
                    to_check.append(neighbor)
    
    def _calculate_span(self, positions: List[int]) -> int:
        """Calcula o span de posições, considerando wrap-around."""
        if len(positions) <= 1:
            return len(positions)
        
        # Verificar span direto
        direct_span = positions[-1] - positions[0] + 1
        
        # Verificar span com wrap-around
        wrap_span = (len(EUROPEAN_WHEEL_ORDER) - positions[-1]) + positions[0] + 1
        
        return min(direct_span, wrap_span)
    
    # ══════════════════════════════════════════════════════════════════════════
    # CAMADA 4 & 5: TERMINAIS E ALTERNÂNCIA
    # ══════════════════════════════════════════════════════════════════════════
    
    def analyze_terminals(self) -> None:
        """
        Analisa padrões de terminais.
        
        - Repetição do mesmo terminal
        - Concentração de terminais próximos
        - Alternância de terminais
        """
        # Extrair sequência de terminais do histórico
        terminal_sequence = [get_terminal(n) for n in self.history]
        
        # Análise por terminal
        for terminal in range(10):
            group = self.terminal_groups[terminal]
            
            # Frequência do terminal
            group.frequency = sum(
                1 for t in terminal_sequence[:self.WINDOW_MEDIUM] if t == terminal
            )
            
            # Atividade recente
            recent_count = sum(
                1 for t in terminal_sequence[:self.WINDOW_SHORT] if t == terminal
            )
            group.recent_activity = recent_count / max(1, group.frequency) if group.frequency > 0 else 0
        
        # Detectar alternância de terminais
        self._detect_terminal_alternation(terminal_sequence)
        
        # Atualizar scores dos números baseado em terminais
        self._update_terminal_scores()
    
    def _detect_terminal_alternation(self, terminal_sequence: List[int]) -> None:
        """
        Detecta padrões de alternância A → B → A.
        
        Indica compressão estatística quando terminais alternam.
        """
        if len(terminal_sequence) < 10:
            return
        
        # Verificar padrões nos últimos 30 terminais
        recent = terminal_sequence[:30]
        
        # Contar transições entre terminais
        transitions: Dict[Tuple[int, int], int] = defaultdict(int)
        for i in range(len(recent) - 1):
            transitions[(recent[i], recent[i + 1])] += 1
        
        # Detectar alternância (A → B e B → A ambos frequentes)
        for (t1, t2), count1 in transitions.items():
            if t1 == t2:
                continue
            count2 = transitions.get((t2, t1), 0)
            
            if count1 >= 2 and count2 >= 2:
                self.terminal_groups[t1].alternation_detected = True
                self.terminal_groups[t2].alternation_detected = True
    
    def _update_terminal_scores(self) -> None:
        """Atualiza scores dos números baseado na análise de terminais."""
        for num in range(37):
            terminal = get_terminal(num)
            group = self.terminal_groups[terminal]
            
            stats = self.number_stats[num]
            
            # Score base pela frequência do terminal
            base_score = group.frequency / max(1, self.WINDOW_MEDIUM / 10)
            
            # Bônus por atividade recente do terminal
            recency_bonus = group.recent_activity * 2
            
            # Bônus por alternância detectada
            alternation_bonus = 1.5 if group.alternation_detected else 0
            
            stats.terminal_score = base_score + recency_bonus + alternation_bonus
    
    # ══════════════════════════════════════════════════════════════════════════
    # CAMADA 6: ANÁLISE DO ZERO
    # ══════════════════════════════════════════════════════════════════════════
    
    def analyze_zero(self) -> None:
        """
        Análise especial do zero.
        
        O zero atua como regulador de ciclo e sua presença
        indica compressão e reforça números próximos.
        """
        zero_stats = self.number_stats[0]
        
        self.zero_analysis = {
            'frequency': zero_stats.total_frequency,
            'frequency_short': zero_stats.frequency_short,
            'frequency_medium': zero_stats.frequency_medium,
            'positions': zero_stats.positions.copy(),
            'compression_indicator': False,
            'reinforced_numbers': set()
        }
        
        # Verificar se zero indica compressão
        if zero_stats.frequency_short >= 2:
            self.zero_analysis['compression_indicator'] = True
            
            # Identificar números reforçados pelo zero
            for pos in zero_stats.positions[:5]:  # Últimas 5 aparições
                # Números que aparecem perto do zero
                for offset in range(-5, 6):
                    check_pos = pos + offset
                    if 0 <= check_pos < self.history_length and offset != 0:
                        nearby_num = self.history[check_pos]
                        self.zero_analysis['reinforced_numbers'].add(nearby_num)
            
            # Dar bônus para números próximos fisicamente do zero
            zero_neighbors = get_wheel_neighbors(0, distance=2)
            for neighbor in zero_neighbors:
                self.number_stats[neighbor].chain_score += 1.5
    
    # ══════════════════════════════════════════════════════════════════════════
    # CONSTRUÇÃO DO GRUPO FINAL
    # ══════════════════════════════════════════════════════════════════════════
    
    def build_final_group(self) -> Tuple[List[int], List[int], List[int]]:
        """
        Constrói o grupo final de números.
        
        Returns:
            Tuple contendo:
            - Lista do grupo final (9-13 números)
            - Lista de gatilhos principais (3)
            - Lista de gatilhos secundários (0-2)
        """
        # Passo 1: Listar números mais frequentes
        candidates = self._get_initial_candidates()
        
        # Passo 2: Adicionar vizinhos físicos relevantes
        candidates = self._add_relevant_neighbors(candidates)
        
        # Passo 3: Incluir terminais ativos
        candidates = self._include_active_terminals(candidates)
        
        # Passo 4: Remover números isolados
        candidates = self._remove_isolated_numbers(candidates)
        
        # Passo 5: Ajustar para tamanho alvo
        final_group = self._adjust_to_target_size(candidates)
        
        # Passo 6: Definir gatilhos
        main_triggers, secondary_triggers = self._define_triggers(final_group)
        
        return final_group, main_triggers, secondary_triggers
    
    def _get_initial_candidates(self) -> List[int]:
        """Obtém candidatos iniciais baseado em frequência e scores."""
        # Primeiro, pegar todos que passam no threshold
        candidates_with_scores = [
            (n, s.combined_score, s.total_frequency) 
            for n, s in self.number_stats.items()
            if s.total_frequency >= self.THRESHOLD_RADAR
        ]
        
        # Ordenar por score combinado, com desempate por frequência
        sorted_numbers = sorted(
            candidates_with_scores,
            key=lambda x: (x[1], x[2]),
            reverse=True
        )
        
        # Pegar os top candidatos (mais que o target para ter margem)
        initial = [n for n, _, _ in sorted_numbers[:self.TARGET_GROUP_SIZE + 8]]
        
        return initial
    
    def _add_relevant_neighbors(self, candidates: List[int]) -> List[int]:
        """Adiciona vizinhos físicos relevantes aos candidatos."""
        expanded = set(candidates)
        candidate_set = set(candidates)
        
        # Para cada candidato forte, verificar se há vizinhos que devem entrar
        # Priorizar vizinhos de números mais fortes
        for num in candidates[:8]:  # Top 8 candidatos
            neighbors = get_wheel_neighbors(num, distance=2)
            for neighbor in neighbors:
                if neighbor in candidate_set:
                    continue
                neighbor_stats = self.number_stats[neighbor]
                # Incluir vizinho se tem frequência razoável OU se está em chain forte
                if (neighbor_stats.frequency_short >= 2 or 
                    neighbor_stats.frequency_medium >= 3 or
                    neighbor_stats.chain_score >= 5):
                    expanded.add(neighbor)
        
        return list(expanded)
    
    def _include_active_terminals(self, candidates: List[int]) -> List[int]:
        """Inclui números de terminais muito ativos."""
        expanded = set(candidates)
        candidate_set = set(candidates)
        
        # Identificar terminais dos números já no grupo
        group_terminals = Counter(get_terminal(n) for n in candidates[:8])
        
        # Terminais mais representados no grupo
        top_terminals = [t for t, _ in group_terminals.most_common(4)]
        
        for terminal in top_terminals:
            # Adicionar números deste terminal que têm boa frequência
            for num in self.terminal_groups[terminal].numbers:
                if num in candidate_set:
                    continue
                stats = self.number_stats[num]
                if stats.total_frequency >= 3 or stats.frequency_short >= 2:
                    expanded.add(num)
        
        return list(expanded)
    
    def _remove_isolated_numbers(self, candidates: List[int]) -> List[int]:
        """Remove números que não têm conexão com o grupo."""
        if len(candidates) <= self.TARGET_GROUP_SIZE:
            return candidates
        
        # Calcular conectividade de cada candidato
        connectivity = {}
        candidate_set = set(candidates)
        
        for num in candidates:
            conn_score = 0
            
            # Conexão por vizinhança física
            neighbors = get_wheel_neighbors(num, distance=2)
            for neighbor in neighbors:
                if neighbor in candidate_set:
                    conn_score += 1
            
            # Conexão por terminal
            terminal = get_terminal(num)
            for other in candidates:
                if other != num and get_terminal(other) == terminal:
                    conn_score += 0.5
            
            connectivity[num] = conn_score
        
        # Remover números com menor conectividade
        sorted_by_conn = sorted(
            candidates,
            key=lambda n: (connectivity[n], self.number_stats[n].combined_score),
            reverse=True
        )
        
        return sorted_by_conn
    
    def _adjust_to_target_size(self, candidates: List[int]) -> List[int]:
        """Ajusta lista para o tamanho alvo (9-13, preferencialmente 12)."""
        if len(candidates) <= self.MIN_GROUP_SIZE:
            return candidates
        
        # Ordenar por score combinado final
        sorted_candidates = sorted(
            candidates,
            key=lambda n: self.number_stats[n].combined_score,
            reverse=True
        )
        
        # Retornar tamanho alvo
        return sorted_candidates[:self.TARGET_GROUP_SIZE]
    
    def _define_triggers(self, final_group: List[int]) -> Tuple[List[int], List[int]]:
        """
        Define gatilhos principais e secundários.
        
        Gatilhos principais: números mais repetidos, âncoras centrais,
        números que aparecem, somem e retornam com força.
        
        Prioriza números com:
        - Alta frequência recente (janela curta)
        - Alta frequência total  
        - Capacidade de "puxar" outros números (aparecem antes de outros do grupo)
        - Padrão de retorno (ausência seguida de reaparição)
        """
        # Ordenar grupo por critérios de gatilho
        trigger_scores = []
        
        for num in final_group:
            stats = self.number_stats[num]
            
            score = 0.0
            
            # Frequência total é muito importante para gatilhos
            score += stats.total_frequency * 4.0
            
            # Frequência recente
            score += stats.frequency_short * 6.0
            score += stats.frequency_medium * 2.5
            
            # Recência (aparições recentes)
            score += stats.recency_score * 2.5
            
            # Ser âncora (especialmente central ou retorno)
            if stats.anchor_type == AnchorType.CENTRAL:
                score += 10.0
            elif stats.anchor_type == AnchorType.RETORNO:
                score += 6.0
            elif stats.anchor_type == AnchorType.SUSTENTACAO:
                score += 4.0
            
            # Capacidade de puxar (calculada pela proximidade temporal com outros frequentes)
            pull_score = self._calculate_pull_score(num, final_group)
            score += pull_score * 2.5
            
            # Bônus para números que aparecem muito na janela curta
            if stats.frequency_short >= 3:
                score += 5.0
            
            trigger_scores.append((num, score))
        
        sorted_triggers = sorted(trigger_scores, key=lambda x: x[1], reverse=True)
        
        # Principais: top 3
        main_triggers = [n for n, _ in sorted_triggers[:self.NUM_MAIN_TRIGGERS]]
        
        # Secundários: avaliar se há empate ou clusters disputando
        secondary_triggers = []
        
        if len(sorted_triggers) > 3:
            # Verificar se há scores muito próximos ao terceiro
            third_score = sorted_triggers[2][1]
            
            for num, score in sorted_triggers[3:6]:
                if score >= third_score * 0.80:  # Dentro de 20% do terceiro
                    secondary_triggers.append(num)
        
        return main_triggers, secondary_triggers[:self.MAX_SECONDARY_TRIGGERS]
    
    def _calculate_pull_score(self, num: int, group: List[int]) -> float:
        """
        Calcula a capacidade de um número "puxar" outros do grupo.
        
        Verifica quantas vezes números do grupo aparecem logo após este número.
        """
        stats = self.number_stats[num]
        pull_score = 0.0
        group_set = set(group) - {num}
        
        for pos in stats.positions:
            # Verificar os 5 números seguintes
            for offset in range(1, 6):
                check_pos = pos + offset
                if check_pos < self.history_length:
                    following_num = self.history[check_pos]
                    if following_num in group_set:
                        # Peso maior para mais próximos
                        pull_score += (6 - offset) / 5.0
        
        return pull_score
    
    # ══════════════════════════════════════════════════════════════════════════
    # MÉTODO PRINCIPAL DE ANÁLISE
    # ══════════════════════════════════════════════════════════════════════════
    
    def analyze(self) -> AnalysisResult:
        """
        Executa análise completa do histórico.
        
        Returns:
            AnalysisResult com todos os dados da análise
        """
        # Executar todas as camadas de análise
        self.analyze_frequency()
        self.calculate_recency_scores()
        self.identify_anchors()
        self.analyze_chains()
        self.analyze_terminals()
        self.analyze_zero()
        
        # Construir grupo final
        final_group, main_triggers, secondary_triggers = self.build_final_group()
        
        # Calcular score de confiança
        confidence = self._calculate_confidence(final_group)
        
        return AnalysisResult(
            final_group=final_group,
            main_triggers=main_triggers,
            secondary_triggers=secondary_triggers,
            number_stats=self.number_stats,
            terminal_groups=self.terminal_groups,
            chain_clusters=self.chain_clusters,
            zero_analysis=self.zero_analysis,
            confidence_score=confidence
        )
    
    def _calculate_confidence(self, final_group: List[int]) -> float:
        """
        Calcula score de confiança da análise.
        
        Baseado em:
        - Força das âncoras
        - Coesão do grupo (conectividade)
        - Atividade recente
        """
        if not final_group:
            return 0.0
        
        # Força média das âncoras
        anchor_strength = sum(
            self.number_stats[n].anchor_strength 
            for n in final_group
        ) / len(final_group)
        
        # Coesão do grupo (média de conexões)
        group_set = set(final_group)
        connectivity = 0
        for num in final_group:
            neighbors = get_wheel_neighbors(num, distance=2)
            connectivity += sum(1 for n in neighbors if n in group_set)
        avg_connectivity = connectivity / len(final_group)
        
        # Atividade recente
        recent_activity = sum(
            self.number_stats[n].frequency_short 
            for n in final_group
        )
        
        # Combinar métricas
        confidence = min(100, (
            anchor_strength * 10 +
            avg_connectivity * 8 +
            recent_activity * 1.5
        ))
        
        return round(confidence, 1)


# ══════════════════════════════════════════════════════════════════════════════
# FORMATADOR DE OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

class OutputFormatter:
    """Formata o resultado da análise para exibição."""
    
    @staticmethod
    def format_result(result: AnalysisResult) -> str:
        """
        Formata resultado no padrão especificado.
        
        Args:
            result: Resultado da análise
            
        Returns:
            String formatada para exibição
        """
        group_str = " · ".join(str(n) for n in result.final_group)
        triggers_str = " · ".join(str(n) for n in result.main_triggers)
        
        output = []
        output.append("🔗 GRUPO DE 12 NÚMEROS QUE ESTÃO SE PUXANDO NO HISTÓRICO")
        output.append("")
        output.append(f"Grupo final ({len(result.final_group)} números):")
        output.append(group_str)
        output.append("")
        output.append("🎯 GATILHOS MAIS FORTES DE ATIVAÇÃO")
        output.append("")
        output.append("Gatilhos principais:")
        output.append(triggers_str)
        
        if result.secondary_triggers:
            secondary_str = " · ".join(str(n) for n in result.secondary_triggers)
            output.append(f"(gatilhos secundários: {secondary_str})")
        
        output.append("")
        output.append("✅ RESUMO SECO")
        output.append("")
        output.append("Grupo:")
        output.append(group_str)
        output.append("")
        output.append("Gatilhos fortes:")
        output.append(triggers_str)
        
        return "\n".join(output)
    
    @staticmethod
    def format_detailed_report(result: AnalysisResult) -> str:
        """
        Formata relatório detalhado da análise.
        
        Args:
            result: Resultado da análise
            
        Returns:
            Relatório completo com todas as métricas
        """
        lines = []
        lines.append("=" * 70)
        lines.append("RELATÓRIO DETALHADO DE ANÁLISE ESTATÍSTICA")
        lines.append("=" * 70)
        lines.append("")
        
        # Grupo final
        lines.append("📊 GRUPO FINAL")
        lines.append("-" * 40)
        for num in result.final_group:
            stats = result.number_stats[num]
            anchor_info = f" [{stats.anchor_type.value}]" if stats.anchor_type else ""
            lines.append(
                f"  {num:2d}: freq={stats.total_frequency:2d} | "
                f"curta={stats.frequency_short:2d} | "
                f"média={stats.frequency_medium:2d} | "
                f"score={stats.combined_score:.1f}{anchor_info}"
            )
        lines.append("")
        
        # Gatilhos
        lines.append("🎯 GATILHOS")
        lines.append("-" * 40)
        lines.append(f"  Principais: {result.main_triggers}")
        lines.append(f"  Secundários: {result.secondary_triggers}")
        lines.append("")
        
        # Clusters de chain
        if result.chain_clusters:
            lines.append("🔗 CLUSTERS DE VIZINHANÇA")
            lines.append("-" * 40)
            for i, cluster in enumerate(result.chain_clusters[:5], 1):
                members = sorted(cluster.members)
                lines.append(
                    f"  Cluster {i}: centro={cluster.center}, "
                    f"membros={members}, força={cluster.strength:.1f}"
                )
            lines.append("")
        
        # Análise do zero
        lines.append("0️⃣  ANÁLISE DO ZERO")
        lines.append("-" * 40)
        lines.append(f"  Frequência total: {result.zero_analysis['frequency']}")
        lines.append(f"  Frequência curta: {result.zero_analysis['frequency_short']}")
        lines.append(f"  Compressão: {'Sim' if result.zero_analysis['compression_indicator'] else 'Não'}")
        if result.zero_analysis['reinforced_numbers']:
            lines.append(f"  Números reforçados: {sorted(result.zero_analysis['reinforced_numbers'])}")
        lines.append("")
        
        # Terminais ativos
        lines.append("🔢 TERMINAIS MAIS ATIVOS")
        lines.append("-" * 40)
        sorted_terminals = sorted(
            result.terminal_groups.items(),
            key=lambda x: x[1].frequency + x[1].recent_activity * 5,
            reverse=True
        )
        for terminal, group in sorted_terminals[:5]:
            alt = " [ALTERNÂNCIA]" if group.alternation_detected else ""
            lines.append(
                f"  Terminal {terminal}: freq={group.frequency}, "
                f"atividade={group.recent_activity:.2f}{alt}"
            )
        lines.append("")
        
        # Confiança
        lines.append("📈 MÉTRICAS")
        lines.append("-" * 40)
        lines.append(f"  Score de confiança: {result.confidence_score}%")
        lines.append("")
        lines.append("=" * 70)
        
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES DE ENTRADA
# ══════════════════════════════════════════════════════════════════════════════

def parse_input(input_text: str) -> List[int]:
    """
    Parseia entrada de texto para lista de números.
    
    Aceita:
    - Um número por linha
    - Números separados por vírgula
    - Números separados por espaço
    
    Args:
        input_text: Texto com números
        
    Returns:
        Lista de números (índice 0 = mais recente)
    """
    numbers = []
    
    # Tentar split por linha primeiro
    lines = input_text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Tentar parsear como número único
        try:
            num = int(line)
            if 0 <= num <= 36:
                numbers.append(num)
            continue
        except ValueError:
            pass
        
        # Tentar split por vírgula ou espaço
        parts = line.replace(',', ' ').split()
        for part in parts:
            try:
                num = int(part.strip())
                if 0 <= num <= 36:
                    numbers.append(num)
            except ValueError:
                continue
    
    return numbers


# ══════════════════════════════════════════════════════════════════════════════
# VALIDADOR DE ASSERTIVIDADE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TriggerActivation:
    """Representa uma ativação de gatilho encontrada."""
    position: int
    trigger: int
    next_three: List[int]
    hits: List[int]
    hit_count: int


@dataclass 
class AssertivityResult:
    """Resultado da análise de assertividade."""
    total_activations: int
    activations_with_hit: int
    total_attempts: int
    total_hits: int
    hit_rate_per_attempt: float
    activation_success_rate: float
    group_numbers_found: Dict[int, int]  # número -> quantidade de aparições
    group_numbers_missing: List[int]
    activations: List[TriggerActivation]


class AssertivityValidator:
    """
    Valida assertividade de uma análise contra resultados reais.
    
    Verifica se os gatilhos principais ativaram e se os números
    do grupo apareceram nas 3 tentativas seguintes.
    """
    
    def __init__(
        self, 
        group: List[int], 
        main_triggers: List[int],
        results: List[int]
    ):
        """
        Args:
            group: Grupo de números sugeridos
            main_triggers: Gatilhos principais
            results: Resultados reais (índice 0 = mais recente)
        """
        self.group = set(group)
        self.main_triggers = set(main_triggers)
        self.results = results
        
    def validate(self) -> AssertivityResult:
        """
        Executa validação completa de assertividade.
        
        Returns:
            AssertivityResult com todas as métricas
        """
        activations = self._find_trigger_activations()
        group_appearances = self._count_group_appearances()
        
        # Calcular métricas
        total_activations = len(activations)
        activations_with_hit = sum(1 for a in activations if a.hit_count > 0)
        total_attempts = total_activations * 3
        total_hits = sum(a.hit_count for a in activations)
        
        hit_rate = (total_hits / total_attempts * 100) if total_attempts > 0 else 0
        success_rate = (activations_with_hit / total_activations * 100) if total_activations > 0 else 0
        
        missing = [n for n in self.group if group_appearances.get(n, 0) == 0]
        
        return AssertivityResult(
            total_activations=total_activations,
            activations_with_hit=activations_with_hit,
            total_attempts=total_attempts,
            total_hits=total_hits,
            hit_rate_per_attempt=round(hit_rate, 1),
            activation_success_rate=round(success_rate, 1),
            group_numbers_found={n: c for n, c in group_appearances.items() if c > 0},
            group_numbers_missing=missing,
            activations=activations
        )
    
    def _find_trigger_activations(self) -> List[TriggerActivation]:
        """Encontra todas as ativações de gatilho no histórico."""
        activations = []
        
        for i, num in enumerate(self.results):
            if num in self.main_triggers:
                # Verificar se há pelo menos 3 números após
                if i + 3 < len(self.results):
                    next_three = self.results[i + 1:i + 4]
                    hits = [n for n in next_three if n in self.group]
                    
                    activations.append(TriggerActivation(
                        position=i,
                        trigger=num,
                        next_three=next_three,
                        hits=hits,
                        hit_count=len(hits)
                    ))
        
        return activations
    
    def _count_group_appearances(self) -> Dict[int, int]:
        """Conta aparições de cada número do grupo nos resultados."""
        counts = Counter(self.results)
        return {n: counts.get(n, 0) for n in self.group}
    
    def format_report(self) -> str:
        """Formata relatório de assertividade."""
        result = self.validate()
        
        lines = []
        lines.append("=" * 60)
        lines.append("ANÁLISE DE ASSERTIVIDADE")
        lines.append("=" * 60)
        lines.append("")
        
        # Configuração
        lines.append(f"Gatilhos: {sorted(self.main_triggers)}")
        lines.append(f"Grupo: {sorted(self.group)}")
        lines.append("")
        
        # Ativações
        lines.append("🔍 ATIVAÇÕES DE GATILHO + 3 TENTATIVAS")
        lines.append("-" * 40)
        
        for act in result.activations:
            hit_mark = "✅" if act.hit_count > 0 else "❌"
            next_str = " · ".join(
                f"{n}{'✓' if n in self.group else ''}" 
                for n in act.next_three
            )
            lines.append(
                f"  Pos {act.position:3d} | Gatilho {act.trigger:2d} → "
                f"[{next_str}] = {act.hit_count}/3 {hit_mark}"
            )
        
        lines.append("")
        
        # Métricas
        lines.append("📊 RESUMO")
        lines.append("-" * 40)
        lines.append(f"  Ativações encontradas: {result.total_activations}")
        lines.append(f"  Ativações com ≥1 acerto: {result.activations_with_hit}/{result.total_activations} ({result.activation_success_rate}%)")
        lines.append(f"  Total de tentativas: {result.total_attempts}")
        lines.append(f"  Total de acertos: {result.total_hits}")
        lines.append(f"  Taxa de acerto/tentativa: {result.hit_rate_per_attempt}%")
        lines.append("")
        
        # Números do grupo
        lines.append("🎯 NÚMEROS DO GRUPO NOS RESULTADOS")
        lines.append("-" * 40)
        
        sorted_found = sorted(
            result.group_numbers_found.items(),
            key=lambda x: x[1],
            reverse=True
        )
        for num, count in sorted_found:
            lines.append(f"  {num:2d}: {count}x ✅")
        
        if result.group_numbers_missing:
            lines.append(f"\n  Não apareceram: {result.group_numbers_missing}")
        else:
            lines.append(f"\n  ✅ Todos os números do grupo apareceram!")
        
        lines.append("")
        lines.append("=" * 60)
        
        return "\n".join(lines)


def validate_assertivity(
    group: List[int],
    triggers: List[int], 
    results: List[int]
) -> str:
    """
    Função de conveniência para validar assertividade.
    
    Args:
        group: Grupo de números sugeridos
        triggers: Gatilhos principais
        results: Resultados reais (índice 0 = mais recente)
        
    Returns:
        Relatório formatado
    """
    validator = AssertivityValidator(group, triggers, results)
    return validator.format_report()


def analyze_history(history: List[int], detailed: bool = False) -> str:
    """
    Função principal para análise de histórico.
    
    Args:
        history: Lista de números (índice 0 = mais recente)
        detailed: Se True, retorna relatório detalhado
        
    Returns:
        Resultado formatado
    """
    if len(history) < 30:
        return "⚠️ Histórico insuficiente. Forneça pelo menos 30 números para análise."
    
    analyzer = RouletteAnalyzer(history)
    result = analyzer.analyze()
    
    if detailed:
        return OutputFormatter.format_detailed_report(result)
    else:
        return OutputFormatter.format_result(result)


def analyze_from_text(input_text: str, detailed: bool = False) -> str:
    """
    Analisa histórico a partir de texto.
    
    Args:
        input_text: Texto com números (um por linha, mais recente no topo)
        detailed: Se True, retorna relatório detalhado
        
    Returns:
        Resultado formatado
    """
    history = parse_input(input_text)
    return analyze_history(history, detailed)


# ══════════════════════════════════════════════════════════════════════════════
# INTERFACE DE LINHA DE COMANDO
# ══════════════════════════════════════════════════════════════════════════════

def main():
    """Interface principal de linha de comando."""
    import sys
    
    print("=" * 70)
    print("       ROULETTE STATISTICAL ANALYZER v1.0")
    print("       Análise Estatística de Histórico de Roleta")
    print("=" * 70)
    print()
    print("⚠️  ESTUDO ESTATÍSTICO EDUCATIVO - NÃO GARANTE RESULTADOS")
    print()
    
    # Verificar argumentos
    detailed = '--detailed' in sys.argv or '-d' in sys.argv
    
    # Verificar se há input via pipe
    if not sys.stdin.isatty():
        input_text = sys.stdin.read()
        result = analyze_from_text(input_text, detailed)
        print(result)
        return
    
    # Modo interativo
    print("Cole o histórico de números (um por linha, mais recente no topo).")
    print("Digite 'FIM' em uma linha separada quando terminar.")
    print("Digite 'SAIR' para encerrar o programa.")
    print("-" * 70)
    
    while True:
        lines = []
        
        while True:
            try:
                line = input()
            except EOFError:
                break
            
            if line.strip().upper() == 'FIM':
                break
            if line.strip().upper() == 'SAIR':
                print("\nEncerrando...")
                return
            
            lines.append(line)
        
        if lines:
            input_text = '\n'.join(lines)
            result = analyze_from_text(input_text, detailed)
            print()
            print(result)
            print()
            print("-" * 70)
            print("Cole novo histórico ou digite 'SAIR' para encerrar:")
            print("-" * 70)


if __name__ == "__main__":
    main()