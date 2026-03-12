#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    RANK STREAM FINAL v2.0                                    ║
║                                                                              ║
║  Sistema avançado de ranking de padrões com:                                 ║
║  - Pesos dinâmicos baseados em score e assertividade                        ║
║  - Integração com RouletteAnalyzer para análise estatística                 ║
║  - Validação de coesão física do grupo                                      ║
║  - Sistema de score composto multi-fator                                    ║
║  - Tracking de performance por padrão                                       ║
║  - Threshold adaptativo                                                      ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import argparse
import asyncio
import importlib.util
import inspect
import io
import json
import logging
import os
import pickle
import re
import statistics
import threading
import time
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import redis.asyncio as redis
import requests

from core.api import RouletteAPI
from core.redis import save_signal
from helpers.roulette_analyzer import RouletteAnalyzer, WHEEL_POSITION, EUROPEAN_WHEEL_ORDER
from helpers.roulettes_list import roulettes
from helpers.utils.get_neighbords import get_neighbords
from helpers.waiting_controller import waiting_controller
from patterns.registry import list_pattern_files


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════════════════

PATTERNS_DIR = Path(__file__).resolve().parent / "patterns_rank"
STATUS_REQUIRED = "processing"
BET_API_URL = "http://localhost:3000/api/bet"
PERFORMANCE_FILE = Path(__file__).resolve().parent / ".pattern_performance.pkl"

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÕES DE PESOS E THRESHOLDS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RankingConfig:
    """Configurações do sistema de ranking."""

    # Pesos para score composto
    weight_patterns: float = 0.25       # Peso para quantidade de padrões
    weight_hits: float = 0.20           # Peso para hits recentes
    weight_cohesion: float = 0.20       # Peso para coesão física
    weight_hot: float = 0.15            # Peso para hot numbers
    weight_analyzer: float = 0.10       # Peso para overlap com RouletteAnalyzer
    weight_anchors: float = 0.10        # Peso para âncoras

    # Thresholds
    min_patterns_active: int = 3        # Mínimo de padrões ativos para gerar sugestão
    min_composite_score: float = 0.45   # Score mínimo para aprovar sugestão
    min_cohesion: float = 0.15          # Coesão mínima do grupo
    min_terminal_diversity: int = 4     # Mínimo de terminais diferentes
    max_same_terminal: int = 4          # Máximo de números do mesmo terminal
    min_anchor_count: int = 1           # Mínimo de âncoras no grupo

    # Hot numbers
    hot_window: int = 400               # Janela para calcular hot numbers
    min_hot_overlap: float = 0.40       # Overlap mínimo com hot numbers

    # Hits recentes
    hits_window: int = 7                # Janela para verificar hits
    min_hits: int = 3                   # Hits mínimos na janela

    # Performance tracking
    min_samples_for_weight: int = 15    # Amostras mínimas para ajustar peso
    weight_min: float = 0.3             # Peso mínimo de um padrão
    weight_max: float = 2.5             # Peso máximo de um padrão

    # Adaptive threshold
    threshold_history_size: int = 50    # Tamanho do histórico de scores
    threshold_percentile: int = 60      # Percentil para threshold adaptativo


# ══════════════════════════════════════════════════════════════════════════════
# TRACKING DE PERFORMANCE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class PatternPerformance:
    """Performance histórica de um padrão."""
    hits: int = 0
    total: int = 0
    recent_results: list = field(default_factory=list)  # Últimos 50 resultados (True/False)

    @property
    def accuracy(self) -> float:
        if self.total == 0:
            return 0.5  # Default neutro
        return self.hits / self.total

    @property
    def recent_accuracy(self) -> float:
        if len(self.recent_results) < 10:
            return self.accuracy
        return sum(self.recent_results[-30:]) / len(self.recent_results[-30:])

    def add_result(self, hit: bool):
        self.total += 1
        if hit:
            self.hits += 1
        self.recent_results.append(hit)
        # Manter apenas últimos 50
        if len(self.recent_results) > 50:
            self.recent_results = self.recent_results[-50:]


class PerformanceTracker:
    """Gerencia tracking de performance dos padrões."""

    def __init__(self, file_path: Path = PERFORMANCE_FILE):
        self.file_path = file_path
        self.patterns: dict[str, PatternPerformance] = {}
        self.score_history: list[float] = []
        self._load()

    def _load(self):
        """Carrega dados de performance do disco."""
        if self.file_path.exists():
            try:
                with open(self.file_path, 'rb') as f:
                    data = pickle.load(f)
                    self.patterns = data.get('patterns', {})
                    self.score_history = data.get('score_history', [])
                logger.debug("Performance data loaded: %d patterns", len(self.patterns))
            except Exception as e:
                logger.warning("Failed to load performance data: %s", e)
                self.patterns = {}
                self.score_history = []

    def _save(self):
        """Salva dados de performance no disco."""
        try:
            with open(self.file_path, 'wb') as f:
                pickle.dump({
                    'patterns': self.patterns,
                    'score_history': self.score_history
                }, f)
        except Exception as e:
            logger.warning("Failed to save performance data: %s", e)

    def get_pattern_weight(self, pattern_name: str, config: RankingConfig) -> float:
        """Retorna peso do padrão baseado na performance histórica."""
        if pattern_name not in self.patterns:
            return 1.0

        perf = self.patterns[pattern_name]
        if perf.total < config.min_samples_for_weight:
            return 1.0

        # Usar média ponderada entre accuracy geral e recente
        accuracy = (perf.accuracy * 0.4) + (perf.recent_accuracy * 0.6)

        # Mapear accuracy (0-1) para peso (weight_min - weight_max)
        weight = config.weight_min + (accuracy * (config.weight_max - config.weight_min))
        return max(config.weight_min, min(config.weight_max, weight))

    def update_pattern(self, pattern_name: str, hit: bool):
        """Atualiza performance de um padrão."""
        if pattern_name not in self.patterns:
            self.patterns[pattern_name] = PatternPerformance()
        self.patterns[pattern_name].add_result(hit)
        self._save()

    def add_score(self, score: float, config: RankingConfig):
        """Adiciona score ao histórico."""
        self.score_history.append(score)
        if len(self.score_history) > config.threshold_history_size:
            self.score_history = self.score_history[-config.threshold_history_size:]
        self._save()

    def get_adaptive_threshold(self, config: RankingConfig) -> float:
        """Retorna threshold adaptativo baseado no histórico."""
        if len(self.score_history) < 20:
            return config.min_composite_score

        try:
            # Usar percentil configurado
            sorted_scores = sorted(self.score_history)
            idx = int(len(sorted_scores) * config.threshold_percentile / 100)
            return max(config.min_composite_score, sorted_scores[idx])
        except Exception:
            return config.min_composite_score

    def get_stats(self) -> dict:
        """Retorna estatísticas de performance."""
        if not self.patterns:
            return {
                'total_patterns': 0,
                'patterns_with_data': 0,
                'avg_accuracy': 0,
                'best_patterns': []
            }

        accuracies = [p.accuracy for p in self.patterns.values() if p.total >= 10]
        return {
            'total_patterns': len(self.patterns),
            'patterns_with_data': len([p for p in self.patterns.values() if p.total >= 10]),
            'avg_accuracy': statistics.mean(accuracies) if accuracies else 0,
            'best_patterns': sorted(
                [(name, p.accuracy, p.total) for name, p in self.patterns.items() if p.total >= 10],
                key=lambda x: x[1],
                reverse=True
            )[:5]
        }


# Instância global do tracker
performance_tracker = PerformanceTracker()


# ══════════════════════════════════════════════════════════════════════════════
# FUNÇÕES DE VALIDAÇÃO E ANÁLISE
# ══════════════════════════════════════════════════════════════════════════════

def _sanitize_module_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _get_wheel_distance(num1: int, num2: int) -> int:
    """Calcula distância física entre dois números na roleta."""
    if num1 not in WHEEL_POSITION or num2 not in WHEEL_POSITION:
        return 37

    pos1 = WHEEL_POSITION[num1]
    pos2 = WHEEL_POSITION[num2]

    direct = abs(pos1 - pos2)
    wraparound = len(EUROPEAN_WHEEL_ORDER) - direct

    return min(direct, wraparound)


def _calculate_cohesion_score(suggestion: list[int]) -> float:
    """
    Calcula quão coesos são os números na roleta física.

    Números que formam grupos contíguos ou próximos na roleta
    têm maior score de coesão.
    """
    if len(suggestion) < 2:
        return 0.0

    suggestion_set = set(suggestion)
    connections = 0

    for num in suggestion:
        # Vizinhos até distância 2
        neighbors = get_neighbords(num, 2)
        connections += len(set(neighbors) & suggestion_set)

    # Normalizar pela quantidade máxima possível
    max_connections = len(suggestion) * 4
    return connections / max_connections if max_connections > 0 else 0.0


def _calculate_clustering_score(suggestion: list[int]) -> float:
    """
    Calcula score de clustering - números que formam grupos na roleta.

    Analisa se os números estão distribuídos em poucos clusters
    ou dispersos por toda a roleta.
    """
    if len(suggestion) < 3:
        return 0.0

    # Ordenar por posição na roleta
    positions = sorted([WHEEL_POSITION.get(n, 0) for n in suggestion])

    # Calcular gaps entre posições consecutivas
    gaps = []
    for i in range(len(positions) - 1):
        gap = positions[i + 1] - positions[i]
        gaps.append(gap)

    # Gap wrap-around
    wrap_gap = (37 - positions[-1]) + positions[0]
    gaps.append(wrap_gap)

    if not gaps:
        return 0.0

    # Score baseado em variância dos gaps
    # Gaps uniformes = disperso (ruim), gaps variados = clusters (bom)
    avg_gap = statistics.mean(gaps)
    variance = statistics.variance(gaps) if len(gaps) > 1 else 0

    # Normalizar
    max_variance = (37 / 2) ** 2  # Variância máxima teórica
    clustering = min(1.0, variance / max_variance) if max_variance > 0 else 0

    return clustering


def _analyze_terminal_distribution(suggestion: list[int]) -> tuple[bool, int, int]:
    """
    Analisa distribuição de terminais no grupo.

    Returns:
        (is_valid, num_terminals, max_same_terminal)
    """
    if not suggestion:
        return False, 0, 0

    terminals = [n % 10 for n in suggestion]
    terminal_counts = Counter(terminals)

    num_terminals = len(terminal_counts)
    max_same = max(terminal_counts.values())

    return True, num_terminals, max_same


def _calculate_hot_overlap(suggestion: list[int], numbers: list[int], top_n: int = 12) -> float:
    """Calcula overlap com os números mais frequentes (hot numbers)."""
    if not numbers or not suggestion:
        return 0.0

    counts = Counter(numbers)
    hot_numbers = {n for n, _ in counts.most_common(top_n)}

    overlap = len(set(suggestion) & hot_numbers)
    return overlap / len(suggestion)


def _validate_with_analyzer(
    suggestion: list[int],
    numbers: list[int]
) -> tuple[float, int, list[int]]:
    """
    Valida sugestão usando o RouletteAnalyzer.

    Returns:
        (overlap_ratio, anchor_count, anchors_in_suggestion)
    """
    try:
        analyzer = RouletteAnalyzer(numbers)
        analyzer.analyze_frequency()
        analyzer.calculate_recency_scores()
        analyzer.identify_anchors()
        analyzer.analyze_chains()

        suggestion_set = set(suggestion)

        # Contar âncoras na sugestão
        anchors = []
        for num in suggestion:
            stats = analyzer.number_stats.get(num)
            if stats and stats.anchor_type is not None:
                anchors.append(num)

        # Calcular overlap com grupo do analyzer
        result = analyzer.build_final_group()
        if result:
            analyzer_group, _, _ = result
            analyzer_set = set(analyzer_group)
            overlap = len(analyzer_set & suggestion_set)
            overlap_ratio = overlap / len(suggestion) if suggestion else 0.0
        else:
            overlap_ratio = 0.0

        return overlap_ratio, len(anchors), anchors

    except Exception as e:
        logger.debug("Analyzer validation failed: %s", e)
        return 0.0, 0, []


def _has_repeated_terminal(last_three: list[int]) -> bool:
    terminals = [n % 10 for n in last_three]
    return len(set(terminals)) != len(terminals)


def _is_consecutive_sequence(last_three: list[int]) -> bool:
    if len(last_three) < 3:
        return False
    a, b, c = last_three[:3]
    return (b == a - 1 and c == b - 1) or (b == a + 1 and c == b + 1)


def _are_neighbors(a: int, b: int) -> bool:
    return b in get_neighbords(a, 1) or a in get_neighbords(b, 1)


def _has_adjacent_neighbors(last_three: list[int]) -> bool:
    if len(last_three) < 3:
        return False
    a, b, c = last_three[:3]
    return _are_neighbors(a, b) or _are_neighbors(b, c)


def _is_alternating_sequence(last_three: list[int]) -> bool:
    if len(last_three) < 3:
        return False
    a, b, c = last_three[:3]
    return abs(a - c) == 1 and b not in (a, c)


def _is_alternating_repeat(last_three: list[int]) -> bool:
    if len(last_three) < 3:
        return False
    a, b, c = last_three[:3]
    return a == c and b != a


def _should_skip_suggestion(last_three: list[int]) -> str | None:
    """Verifica se deve pular a sugestão baseado nos últimos números."""
    if len(last_three) < 3:
        return None

    if _has_repeated_terminal(last_three):
        return "repeticao_terminal"
    if last_three[1] == 0:
        return "zero_atras"
    if _is_consecutive_sequence(last_three):
        return "sequencia_consecutiva"
    if _has_adjacent_neighbors(last_three):
        return "vizinhos_consecutivos"
    if _is_alternating_sequence(last_three):
        return "sequencia_alternada"
    if _is_alternating_repeat(last_three):
        return "repeticao_alternada"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# SCORE COMPOSTO
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SuggestionAnalysis:
    """Análise completa de uma sugestão."""
    suggestion: list[int]

    # Métricas brutas
    pattern_count: int = 0
    hit_count: int = 0
    cohesion: float = 0.0
    clustering: float = 0.0
    hot_overlap: float = 0.0
    analyzer_overlap: float = 0.0
    anchor_count: int = 0
    anchors: list[int] = field(default_factory=list)
    terminal_diversity: int = 0
    max_same_terminal: int = 0

    # Scores normalizados (0-1)
    score_patterns: float = 0.0
    score_hits: float = 0.0
    score_cohesion: float = 0.0
    score_hot: float = 0.0
    score_analyzer: float = 0.0
    score_anchors: float = 0.0

    # Score final
    composite_score: float = 0.0

    # Validações
    is_valid: bool = True
    rejection_reason: str = ""

    # Padrões que contribuíram
    contributing_patterns: dict[str, list[int]] = field(default_factory=dict)


def _calculate_composite_score(
    suggestion: list[int],
    numbers: list[int],
    pattern_count: int,
    pattern_bets: dict[str, list[int]],
    config: RankingConfig
) -> SuggestionAnalysis:
    """
    Calcula score composto para a sugestão analisando múltiplos fatores.
    """
    analysis = SuggestionAnalysis(
        suggestion=suggestion,
        pattern_count=pattern_count,
        contributing_patterns=pattern_bets
    )

    # ── Hits recentes ─────────────────────────────────────────────────────────
    hits_window = numbers[:config.hits_window]
    analysis.hit_count = len(set(suggestion) & set(hits_window))
    analysis.score_hits = analysis.hit_count / config.hits_window

    # ── Coesão física ─────────────────────────────────────────────────────────
    analysis.cohesion = _calculate_cohesion_score(suggestion)
    analysis.clustering = _calculate_clustering_score(suggestion)
    analysis.score_cohesion = (analysis.cohesion * 0.6) + (analysis.clustering * 0.4)

    # ── Hot numbers ───────────────────────────────────────────────────────────
    analysis.hot_overlap = _calculate_hot_overlap(
        suggestion,
        numbers[:config.hot_window],
        top_n=len(suggestion)
    )
    analysis.score_hot = analysis.hot_overlap

    # ── Análise estatística (RouletteAnalyzer) ────────────────────────────────
    analyzer_overlap, anchor_count, anchors = _validate_with_analyzer(suggestion, numbers)
    analysis.analyzer_overlap = analyzer_overlap
    analysis.anchor_count = anchor_count
    analysis.anchors = anchors
    analysis.score_analyzer = analyzer_overlap
    analysis.score_anchors = min(1.0, anchor_count / 3)  # 3+ âncoras = 1.0

    # ── Distribuição de terminais ─────────────────────────────────────────────
    _, num_terminals, max_same = _analyze_terminal_distribution(suggestion)
    analysis.terminal_diversity = num_terminals
    analysis.max_same_terminal = max_same

    # ── Score de padrões ──────────────────────────────────────────────────────
    # Normalizar para 0-1 (10+ padrões = score máximo)
    analysis.score_patterns = min(1.0, pattern_count / 10)

    # ── Validações ────────────────────────────────────────────────────────────
    if pattern_count < config.min_patterns_active:
        analysis.is_valid = False
        analysis.rejection_reason = f"poucos_padroes ({pattern_count} < {config.min_patterns_active})"
    elif analysis.hot_overlap < config.min_hot_overlap:
        analysis.is_valid = False
        analysis.rejection_reason = f"hot_overlap_baixo ({analysis.hot_overlap:.1%} < {config.min_hot_overlap:.0%})"
    elif analysis.cohesion < config.min_cohesion:
        analysis.is_valid = False
        analysis.rejection_reason = f"coesao_baixa ({analysis.cohesion:.2f} < {config.min_cohesion})"
    elif num_terminals < config.min_terminal_diversity:
        analysis.is_valid = False
        analysis.rejection_reason = f"terminais_pouco_diversos ({num_terminals} < {config.min_terminal_diversity})"
    elif max_same > config.max_same_terminal:
        analysis.is_valid = False
        analysis.rejection_reason = f"terminal_concentrado ({max_same} > {config.max_same_terminal})"
    elif analysis.hit_count < config.min_hits:
        analysis.is_valid = False
        analysis.rejection_reason = f"poucos_hits ({analysis.hit_count} < {config.min_hits})"

    # ── Score composto ────────────────────────────────────────────────────────
    analysis.composite_score = (
        analysis.score_patterns * config.weight_patterns +
        analysis.score_hits * config.weight_hits +
        analysis.score_cohesion * config.weight_cohesion +
        analysis.score_hot * config.weight_hot +
        analysis.score_analyzer * config.weight_analyzer +
        analysis.score_anchors * config.weight_anchors
    )

    return analysis


# ══════════════════════════════════════════════════════════════════════════════
# CARREGAMENTO E EXECUÇÃO DE PADRÕES
# ══════════════════════════════════════════════════════════════════════════════

def _load_pattern_module(path: Path):
    module_name = f"rank_stream_patterns.{_sanitize_module_name(path.stem)}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            spec.loader.exec_module(module)
    except Exception as exc:
        logger.debug("Falha ao importar %s: %s", path.name, exc)
        return None
    return module


def _call_process_roulette(func, roulette: dict, numbers: list[int]) -> Any:
    sig = inspect.signature(func)
    num_params = len(sig.parameters)
    if num_params < 2:
        raise TypeError("process_roulette precisa de ao menos 2 parametros")

    args = [roulette, numbers]
    if num_params >= 3:
        args.append(None)
    if num_params >= 4:
        args.append(None)
    return func(*args)


def _normalize_bets(bets: Any) -> list[int]:
    if bets is None:
        return []
    if isinstance(bets, list):
        return [int(b) for b in bets if isinstance(b, (int, float))]
    return [int(bets)]


def _find_roulette(slug: str) -> dict:
    for roulette in roulettes:
        if roulette.get("slug") == slug:
            return roulette
    raise ValueError(f"Roleta nao encontrada para slug: {slug}")


def _load_pattern_functions() -> list[tuple[str, Callable]]:
    """Carrega funções de padrões com seus nomes."""
    functions: list[tuple[str, Callable]] = []
    for path in list_pattern_files(PATTERNS_DIR):
        module = _load_pattern_module(path)
        if module is None:
            continue
        func = getattr(module, "process_roulette", None)
        if func is None:
            continue
        functions.append((path.stem, func))
    return functions


def _rank_from_patterns(
    roulette: dict,
    numbers: list[int],
    funcs: list[tuple[str, Callable]],
    top: int,
    config: RankingConfig
) -> tuple[list[int], int, dict[str, list[int]], dict[str, float]]:
    """
    Executa padrões e retorna ranking ponderado.

    Returns:
        (top_numbers, patterns_active, pattern_bets, pattern_weights)
    """
    weighted_counts: Counter[int] = Counter()
    patterns_active = 0
    last_number = numbers[0] if numbers else None
    pattern_bets: dict[str, set[int]] = {}
    pattern_weights: dict[str, float] = {}

    for pattern_name, func in funcs:
        try:
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                signal = _call_process_roulette(func, roulette, numbers)

            # Log de erros capturados no stderr
            stderr_output = stderr_capture.getvalue().strip()
            if stderr_output:
                print(f"[PATTERN ERROR] {pattern_name}: {stderr_output[:200]}")

        except Exception as exc:
            print(f"[PATTERN EXCEPTION] {pattern_name}: {exc}")
            continue

        if not isinstance(signal, dict):
            print(f"[PATTERN] {pattern_name}: None (sem ativacao)")
            continue

        status = str(signal.get("status", "")).lower().strip()
        if status == "waiting":
            triggers = signal.get("triggers", [])
            print(f"[PATTERN] {pattern_name}: waiting (aguardando gatilho {triggers})")
            waiting_controller.register(signal)
            continue
        if status != STATUS_REQUIRED:
            print(f"[PATTERN] {pattern_name}: {status} (ignorado)")
            continue

        # Padrão ativou com processing
        bets_preview = signal.get("bets", [])[:5]
        print(f"[PATTERN] {pattern_name}: ATIVO ({len(signal.get('bets', []))} nums) -> {bets_preview}...")

        bets = _normalize_bets(signal.get("bets"))
        if not bets:
            continue

        # Obter nome do padrão do sinal ou usar nome do arquivo
        signal_pattern = str(signal.get("pattern", "")).strip() or pattern_name

        # Calcular peso do padrão
        base_weight = 1.0

        # Peso do score retornado pelo padrão (normalizado)
        pattern_score = signal.get("score", 0)
        if pattern_score and isinstance(pattern_score, (int, float)):
            # Score de 0-100 mapeado para 0.5-1.5
            score_weight = 0.5 + (min(100, max(0, pattern_score)) / 100)
        else:
            score_weight = 1.0

        # Peso da performance histórica
        perf_weight = performance_tracker.get_pattern_weight(signal_pattern, config)

        # Peso final = média ponderada
        final_weight = (base_weight * 0.2) + (score_weight * 0.3) + (perf_weight * 0.5)
        final_weight = max(config.weight_min, min(config.weight_max, final_weight))

        pattern_weights[signal_pattern] = final_weight
        pattern_bets.setdefault(signal_pattern, set()).update(bets)
        patterns_active += 1

        for number in set(bets):
            weighted_counts[number] += final_weight

    # Processar sinais waiting que foram ativados
    for signal in waiting_controller.consume_trigger(last_number):
        bets = _normalize_bets(signal.get("bets"))
        if not bets:
            continue
        signal_pattern = str(signal.get("pattern", "")).strip() or "WAITING"

        weight = pattern_weights.get(signal_pattern, 1.0)
        pattern_bets.setdefault(signal_pattern, set()).update(bets)
        patterns_active += 1

        for number in set(bets):
            weighted_counts[number] += weight

    # Ordenar por contagem ponderada (decrescente), desempate pelo número
    ranked = sorted(weighted_counts.items(), key=lambda x: (-x[1], x[0]))
    top_numbers = [n for n, _ in ranked[:top]]

    # Converter sets para lists ordenadas
    pattern_numbers = {
        name: sorted(nums) for name, nums in sorted(pattern_bets.items())
    }

    return top_numbers, patterns_active, pattern_numbers, pattern_weights


# ══════════════════════════════════════════════════════════════════════════════
# API DE APOSTAS
# ══════════════════════════════════════════════════════════════════════════════

def _place_bet_sync(signal: dict) -> dict:
    print("[BET API] Aguardando 5 segundos antes de enviar aposta...")
    time.sleep(5)

    payload = {
        "bets": signal["bets"],
        "attempts": 3,
        "gales": signal.get("gales", 3),
        "roulette_url": signal["roulette_url"],
        "signal_id": str(signal.get("id", "")),
    }

    print(
        "[BET API] Enviando aposta: %s - %d numeros"
        % (signal["roulette_name"], len(signal["bets"]))
    )

    try:
        response = requests.post(BET_API_URL, json=payload, timeout=300)
        response.raise_for_status()
        try:
            result = response.json()
        except ValueError:
            result = {
                "success": False,
                "status": response.status_code,
                "error": "Resposta nao-JSON da API de apostas",
                "body": response.text,
            }
        print("[BET API] Resposta: %s" % result)
        return result
    except requests.RequestException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        body = getattr(getattr(e, "response", None), "text", None)
        print("[BET API] Erro ao chamar API de apostas: %s" % e)
        return {"success": False, "status": status, "error": str(e), "body": body}


def _fire_bet_async(signal: dict) -> None:
    def run_bet():
        try:
            _place_bet_sync(signal)
        except Exception as e:
            print("[BET THREAD] Erro na thread de aposta: %s" % e)

    thread = threading.Thread(target=run_bet, daemon=True)
    thread.start()
    print("[BET] Aposta disparada em background para %s" % signal["roulette_name"])


# ══════════════════════════════════════════════════════════════════════════════
# FORMATAÇÃO DE OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

def _format_analysis_output(analysis: SuggestionAnalysis, config: RankingConfig) -> str:
    """Formata análise para output detalhado."""
    lines = []

    lines.append("=" * 70)
    lines.append("ANALISE DE SUGESTAO")
    lines.append("=" * 70)

    # Sugestão
    lines.append(f"Numeros: {', '.join(str(n) for n in analysis.suggestion)}")
    lines.append("")

    # Métricas
    lines.append("METRICAS:")
    lines.append(f"  Padroes ativos:    {analysis.pattern_count:3d}     (score: {analysis.score_patterns:.2f})")
    lines.append(f"  Hits recentes:     {analysis.hit_count:3d}/{config.hits_window}   (score: {analysis.score_hits:.2f})")
    lines.append(f"  Coesao fisica:     {analysis.cohesion:.2f}    (score: {analysis.score_cohesion:.2f})")
    lines.append(f"  Hot overlap:       {analysis.hot_overlap:.1%}   (score: {analysis.score_hot:.2f})")
    lines.append(f"  Analyzer overlap:  {analysis.analyzer_overlap:.1%}   (score: {analysis.score_analyzer:.2f})")
    lines.append(f"  Ancoras:           {analysis.anchor_count:3d}     (score: {analysis.score_anchors:.2f})")
    if analysis.anchors:
        lines.append(f"    -> {analysis.anchors}")
    lines.append(f"  Terminais:         {analysis.terminal_diversity} diferentes, max {analysis.max_same_terminal} iguais")
    lines.append("")

    # Score final
    lines.append(f"SCORE COMPOSTO: {analysis.composite_score:.3f}")
    lines.append("")

    # Status
    if analysis.is_valid:
        lines.append("STATUS: APROVADO")
    else:
        lines.append(f"STATUS: REJEITADO ({analysis.rejection_reason})")

    lines.append("=" * 70)

    return "\n".join(lines)


def _format_patterns_output(
    pattern_bets: dict[str, list[int]],
    pattern_weights: dict[str, float],
    numbers: list[int]
) -> str:
    """Formata output dos padrões."""
    lines = []
    lines.append("PADROES ATIVOS:")

    for name, nums in sorted(pattern_bets.items()):
        weight = pattern_weights.get(name, 1.0)

        # Calcular hits do padrão
        bet_set = set(nums)
        hits = sum(1 for n in numbers[:50] if n in bet_set)

        # Performance histórica
        perf = performance_tracker.patterns.get(name)
        if perf and perf.total >= 10:
            acc_str = f" | acc: {perf.accuracy:.1%}"
        else:
            acc_str = ""

        lines.append(
            f"  [{weight:.2f}] {name}: {', '.join(str(n) for n in nums[:10])}"
            f"{'...' if len(nums) > 10 else ''} | hits: {hits}/50{acc_str}"
        )

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# LOOP PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def _get_result_channel() -> str:
    mode_simulator = os.getenv("SIMULATOR", "false").lower() == "true"
    if mode_simulator:
        return "new_result_simulate"
    return os.getenv("RESULT_CHANNEL", "new_result")


async def _fetch_initial_history(slug: str, limit: int) -> list[int]:
    api = RouletteAPI()
    resp = await api.api(slug, num_results=limit, full_results=False)
    results = resp.get("results", [])
    numbers = [r["value"] if isinstance(r, dict) else r for r in results]
    return numbers[:limit]


async def main_async(args: argparse.Namespace) -> int:
    config = RankingConfig()

    # Aplicar argumentos CLI às configurações
    if args.min_score:
        config.min_composite_score = args.min_score
    if args.min_patterns:
        config.min_patterns_active = args.min_patterns

    roulette = _find_roulette(args.slug)
    history = await _fetch_initial_history(args.slug, args.limit)
    if not history:
        logger.error("Nao foi possivel carregar historico para %s", args.slug)
        return 1

    funcs = _load_pattern_functions()
    if not funcs:
        logger.error("Nenhum pattern valido encontrado")
        return 1

    print(f"[INIT] Carregados {len(funcs)} padroes de {PATTERNS_DIR}")
    print(f"[INIT] Historico inicial: {len(history)} numeros")

    # Mostrar stats de performance
    stats = performance_tracker.get_stats()
    if stats['patterns_with_data'] > 0:
        print(f"[INIT] Performance tracking: {stats['patterns_with_data']} padroes com dados")
        print(f"[INIT] Accuracy media: {stats['avg_accuracy']:.1%}")
        if stats.get('best_patterns'):
            print("[INIT] Top padroes:")
            for name, acc, total in stats['best_patterns'][:3]:
                print(f"       - {name}: {acc:.1%} ({total} amostras)")

    redis_url = os.getenv("REDIS_CONNECT")
    if not redis_url:
        logger.error("REDIS_CONNECT nao configurado")
        return 1

    channel = _get_result_channel()
    client = redis.from_url(redis_url, decode_responses=True)
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)

    current_suggestion: list[int] = []
    since_last_rank = 0
    last_analysis: SuggestionAnalysis | None = None

    print(f"[STREAM] Escutando {channel} para {args.slug}")
    print(f"[STREAM] Atualizando sugestao a cada {args.every} numeros")
    print(f"[STREAM] Top {args.top} numeros por sugestao")
    print("-" * 70)

    try:
        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=1.0
            )
            if message is None:
                await asyncio.sleep(0.05)
                continue

            try:
                data = json.loads(message["data"])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if data.get("slug") != args.slug:
                continue

            number = data.get("result")
            if number is None:
                continue

            try:
                number = int(number)
            except (TypeError, ValueError):
                continue

            # Atualizar histórico
            history.insert(0, number)
            if len(history) > args.limit:
                history = history[:args.limit]

            since_last_rank += 1

            # Verificar se última sugestão acertou (para tracking de performance)
            if last_analysis and last_analysis.contributing_patterns:
                hit = number in set(last_analysis.suggestion)
                for pattern_name in last_analysis.contributing_patterns:
                    # Só atualiza se o número fazia parte da sugestão do padrão
                    if number in set(last_analysis.contributing_patterns[pattern_name]):
                        performance_tracker.update_pattern(pattern_name, hit)

            print(f"[SPIN] {number} | historico: {len(history)} | desde ultima: {since_last_rank}")

            if since_last_rank >= args.every:
                # Executar ranking
                current_suggestion, patterns_active, pattern_bets, pattern_weights = _rank_from_patterns(
                    roulette, history, funcs, args.top, config
                )
                since_last_rank = 0

                if not current_suggestion:
                    print(f"[RANK] Sem sugestao | padroes ativos: {patterns_active}")
                    last_analysis = None
                    continue

                last_three = history[:3]

                # Verificar skip básico
                skip_reason = _should_skip_suggestion(last_three)
                if skip_reason:
                    print(f"[SKIP] {skip_reason} | ultimos 3: {last_three}")
                    last_analysis = None
                    continue

                # Análise completa
                analysis = _calculate_composite_score(
                    current_suggestion,
                    history,
                    patterns_active,
                    pattern_bets,
                    config
                )
                last_analysis = analysis

                # Adicionar score ao histórico para threshold adaptativo
                performance_tracker.add_score(analysis.composite_score, config)

                # Obter threshold adaptativo
                adaptive_threshold = performance_tracker.get_adaptive_threshold(config)

                # Output de debug
                if args.debug:
                    print(_format_analysis_output(analysis, config))
                    print(_format_patterns_output(pattern_bets, pattern_weights, history))
                    print(f"[THRESHOLD] Adaptativo: {adaptive_threshold:.3f}")

                # Verificar validação
                if not analysis.is_valid:
                    print(
                        f"[REJECT] {analysis.rejection_reason} | "
                        f"score: {analysis.composite_score:.3f} | "
                        f"ultimos 3: {last_three}"
                    )
                    continue

                # Verificar score mínimo (usando threshold adaptativo)
                if analysis.composite_score < adaptive_threshold:
                    print(
                        f"[REJECT] score_baixo ({analysis.composite_score:.3f} < {adaptive_threshold:.3f}) | "
                        f"ultimos 3: {last_three}"
                    )
                    continue

                # ══════════════════════════════════════════════════════════════
                # SUGESTÃO APROVADA - DISPARAR APOSTA
                # ══════════════════════════════════════════════════════════════

                created_at = int(time.time())
                signal_id = save_signal(
                    roulette_id=roulette["slug"],
                    roulette_name=roulette["name"],
                    roulette_url=roulette["url"],
                    triggers=last_three,
                    targets=current_suggestion,
                    bets=current_suggestion,
                    snapshot=history[:500],
                    status="processing",
                    pattern=f"RANK-{patterns_active}-{analysis.composite_score:.2f}",
                    passed_spins=0,
                    spins_required=0,
                    gales=args.gales,
                    score=int(analysis.composite_score * 100),
                    message=f"Patterns: {patterns_active} | Anchors: {analysis.anchors}",
                    temp_state=None,
                    create_at=created_at,
                    timestamp=created_at,
                    tags=["rank_final", f"anchors:{analysis.anchor_count}"],
                )

                if args.place_bet:
                    _fire_bet_async({
                        "id": signal_id,
                        "bets": current_suggestion,
                        "gales": args.gales,
                        "roulette_url": roulette["url"],
                        "roulette_name": roulette["name"],
                    })
                else:
                    print("[BET] Aposta NAO enviada (use --place-bet para ativar)")

                print("=" * 70)
                print(f"[APROVADO] Score: {analysis.composite_score:.3f} | Padroes: {patterns_active}")
                print(f"[SUGESTAO] {', '.join(str(n) for n in current_suggestion)}")
                print(f"[ANCORAS]  {analysis.anchors}")
                print(f"[METRICAS] hits={analysis.hit_count} coes={analysis.cohesion:.2f} hot={analysis.hot_overlap:.1%}")
                print("=" * 70)

                # Output detalhado dos padrões
                if pattern_bets:
                    print("PADROES:")
                    for name, nums in sorted(pattern_bets.items())[:10]:
                        weight = pattern_weights.get(name, 1.0)
                        print(f"  [{weight:.2f}] {name}: {nums[:8]}{'...' if len(nums) > 8 else ''}")

    finally:
        await pubsub.unsubscribe(channel)
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rank Stream Final v2.0 - Sistema avancado de ranking de padroes."
    )
    parser.add_argument("slug", help="Slug da roleta (ex: pragmatic-auto-roulette)")
    parser.add_argument("--limit", type=int, default=500, help="Historico base (default: 500)")
    parser.add_argument("--top", type=int, default=18, help="Quantidade de numeros (default: 18)")
    parser.add_argument("--every", type=int, default=1, help="Atualiza sugestao a cada N numeros (default: 1)")
    parser.add_argument("--min-score", type=float, default=None, help="Score minimo para aprovar")
    parser.add_argument("--min-patterns", type=int, default=None, help="Padroes minimos ativos")
    parser.add_argument("--gales", type=int, default=3, help="Quantidade de gales/tentativas (default: 3)")
    parser.add_argument("--debug", action="store_true", help="Habilita logs de debug detalhados")
    parser.add_argument("--place-bet", action="store_true", help="Ativa envio de apostas para API localhost:3000")
    parser.add_argument("--stats", action="store_true", help="Mostra estatisticas de performance e sai")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%H:%M:%S"
    )

    # Modo stats
    if args.stats:
        stats = performance_tracker.get_stats()
        print("=" * 60)
        print("ESTATISTICAS DE PERFORMANCE DOS PADROES")
        print("=" * 60)
        print(f"Total de padroes rastreados: {stats['total_patterns']}")
        print(f"Padroes com dados suficientes: {stats['patterns_with_data']}")
        print(f"Accuracy media: {stats['avg_accuracy']:.1%}")
        print()
        if stats.get('best_patterns'):
            print("TOP 5 PADROES:")
            for name, acc, total in stats['best_patterns']:
                print(f"  {name}: {acc:.1%} ({total} amostras)")
        print("=" * 60)
        return 0

    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
