"""
Backtesting Module

Sistema que simula apostas em histórico passado para avaliar performance de padrões
com diferentes níveis de gale (1, 2, 3, 5, 12 tentativas).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


@dataclass
class GaleLevelMetrics:
    """Métricas de performance para um nível específico de gale."""
    level: int          # 1, 2, 3, 5, 12
    signals: int = 0
    hits: int = 0

    @property
    def hit_rate(self) -> float:
        return self.hits / self.signals if self.signals > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "signals": self.signals,
            "hits": self.hits,
            "hit_rate": round(self.hit_rate, 4),
        }


@dataclass
class PatternBacktestReport:
    """Relatório de backtest para um padrão específico."""
    pattern_id: str
    total_signals: int = 0
    gale_metrics: Dict[int, GaleLevelMetrics] = field(default_factory=dict)

    @property
    def best_gale_level(self) -> int:
        """Retorna o nível de gale com melhor relação custo-benefício."""
        if not self.gale_metrics:
            return 1

        # Encontra o menor gale com hit_rate >= 0.7 (70%)
        sorted_levels = sorted(self.gale_metrics.keys())
        for level in sorted_levels:
            if self.gale_metrics[level].hit_rate >= 0.7:
                return level

        # Se nenhum atingiu 70%, retorna o de maior hit_rate
        best = max(self.gale_metrics.values(), key=lambda m: m.hit_rate)
        return best.level

    @property
    def recommended_max_gale(self) -> int:
        """Recomenda limite de gale baseado em eficiência marginal."""
        if not self.gale_metrics:
            return 3

        sorted_levels = sorted(self.gale_metrics.keys())
        prev_rate = 0.0

        for level in sorted_levels:
            current_rate = self.gale_metrics[level].hit_rate
            # Se ganho marginal < 5%, não vale aumentar gale
            if level > 1 and (current_rate - prev_rate) < 0.05:
                return sorted_levels[sorted_levels.index(level) - 1]
            prev_rate = current_rate

        return sorted_levels[-1]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "total_signals": self.total_signals,
            "gale_metrics": {str(k): v.to_dict() for k, v in sorted(self.gale_metrics.items())},
            "best_gale_level": self.best_gale_level,
            "recommended_max_gale": self.recommended_max_gale,
        }


class BacktestEngine:
    """Motor de backtesting para avaliar padrões."""

    DEFAULT_GALE_LEVELS = [1, 2, 3, 5, 12]

    def __init__(self) -> None:
        self._reports: Dict[str, PatternBacktestReport] = {}
        self._overall_metrics: Dict[int, GaleLevelMetrics] = {}

    def run_backtest(
        self,
        history: List[int],
        pattern_engine: Any,
        gale_levels: List[int] | None = None,
        max_entries: int = 500,
        min_confidence: int = 0,
    ) -> Dict[str, Any]:
        """
        Executa backtest completo no histórico.

        Args:
            history: Lista de números do histórico
            pattern_engine: Instância do PatternEngine
            gale_levels: Níveis de gale a testar (default: [1, 2, 3, 5, 12])
            max_entries: Máximo de entradas a analisar
            min_confidence: Confiança mínima para considerar sinal válido

        Returns:
            Relatório completo de backtest
        """
        if gale_levels is None:
            gale_levels = self.DEFAULT_GALE_LEVELS

        normalized_history = [int(n) for n in history if 0 <= int(n) <= 36]
        if len(normalized_history) < max(gale_levels) + 1:
            return {
                "available": False,
                "error": "Histórico insuficiente para backtest",
                "required_min": max(gale_levels) + 1,
                "received": len(normalized_history),
            }

        # Inicializa métricas
        self._reports.clear()
        self._overall_metrics = {level: GaleLevelMetrics(level=level) for level in gale_levels}

        limit = min(len(normalized_history) - max(gale_levels), max_entries)
        signals_evaluated = 0
        signals_with_suggestion = 0

        for idx in range(max(gale_levels), limit + max(gale_levels)):
            # Avalia padrões neste ponto do histórico
            result = pattern_engine.evaluate(
                history=normalized_history,
                base_suggestion=[],
                focus_number=None,
                from_index=idx,
                max_numbers=18,
                use_adaptive_weights=False,
            )

            if not result.get("available", False):
                continue

            suggestion = result.get("suggestion", [])
            if not suggestion:
                continue

            confidence = result.get("confidence", {}).get("score", 0) or 0
            if confidence < min_confidence:
                continue

            signals_evaluated += 1
            signals_with_suggestion += 1

            # Obtém padrões que contribuíram
            active_patterns = [
                c.get("pattern_id", "")
                for c in result.get("contributions", [])
                if isinstance(c, dict) and c.get("pattern_id")
            ]

            # Avalia hits em cada nível de gale
            for gale in gale_levels:
                hit, hit_number = self._evaluate_at_gale_level(
                    suggestion=suggestion,
                    history=normalized_history,
                    from_index=idx,
                    gale=gale,
                )

                # Atualiza métricas gerais
                self._overall_metrics[gale].signals += 1
                if hit:
                    self._overall_metrics[gale].hits += 1

                # Atualiza métricas por padrão
                for pattern_id in active_patterns:
                    if pattern_id not in self._reports:
                        self._reports[pattern_id] = PatternBacktestReport(pattern_id=pattern_id)
                        for g in gale_levels:
                            self._reports[pattern_id].gale_metrics[g] = GaleLevelMetrics(level=g)

                    self._reports[pattern_id].total_signals += 1 if gale == gale_levels[0] else 0
                    self._reports[pattern_id].gale_metrics[gale].signals += 1
                    if hit:
                        self._reports[pattern_id].gale_metrics[gale].hits += 1

        return self.generate_performance_report(
            signals_evaluated=signals_evaluated,
            signals_with_suggestion=signals_with_suggestion,
            gale_levels=gale_levels,
        )

    def _evaluate_at_gale_level(
        self,
        suggestion: List[int],
        history: List[int],
        from_index: int,
        gale: int,
    ) -> tuple[bool, int | None]:
        """
        Verifica se a sugestão acertou dentro de N tentativas (gale).

        Args:
            suggestion: Lista de números sugeridos
            history: Histórico completo
            from_index: Índice inicial (onde a sugestão foi gerada)
            gale: Número máximo de tentativas

        Returns:
            Tupla (acertou, número_que_acertou)
        """
        suggestion_set = set(int(n) for n in suggestion)

        for step in range(1, gale + 1):
            look_idx = from_index - step
            if look_idx < 0:
                break

            number = int(history[look_idx])
            if number in suggestion_set:
                return True, number

        return False, None

    def evaluate_single_signal(
        self,
        suggestion: List[int],
        history: List[int],
        from_index: int,
        gale_levels: List[int] | None = None,
    ) -> Dict[str, Any]:
        """
        Avalia um único sinal contra o histórico.

        Útil para verificar performance em tempo real.
        """
        if gale_levels is None:
            gale_levels = self.DEFAULT_GALE_LEVELS

        results = {}
        for gale in gale_levels:
            hit, hit_number = self._evaluate_at_gale_level(
                suggestion=suggestion,
                history=history,
                from_index=from_index,
                gale=gale,
            )
            results[str(gale)] = {
                "hit": hit,
                "hit_number": hit_number,
                "attempts": gale,
            }

        # Encontra primeiro hit
        first_hit = None
        for gale in sorted(gale_levels):
            if results[str(gale)]["hit"]:
                first_hit = {
                    "gale_level": gale,
                    "hit_number": results[str(gale)]["hit_number"],
                }
                break

        return {
            "suggestion": suggestion,
            "from_index": from_index,
            "results_by_gale": results,
            "first_hit": first_hit,
            "hit": first_hit is not None,
        }

    def generate_performance_report(
        self,
        signals_evaluated: int = 0,
        signals_with_suggestion: int = 0,
        gale_levels: List[int] | None = None,
    ) -> Dict[str, Any]:
        """Gera relatório de performance completo."""
        if gale_levels is None:
            gale_levels = self.DEFAULT_GALE_LEVELS

        # Organiza padrões por performance
        pattern_reports = sorted(
            [r.to_dict() for r in self._reports.values()],
            key=lambda x: -x["gale_metrics"].get("3", {}).get("hit_rate", 0),
        )

        # Encontra melhores e piores padrões
        best_patterns = pattern_reports[:5]
        worst_patterns = sorted(
            pattern_reports,
            key=lambda x: x["gale_metrics"].get("3", {}).get("hit_rate", 1),
        )[:5]

        # Métricas gerais por gale
        overall_by_gale = {
            str(k): v.to_dict()
            for k, v in sorted(self._overall_metrics.items())
        }

        # Recomendação de gale ótimo
        optimal_gale = 3  # default
        for gale in sorted(gale_levels):
            metrics = self._overall_metrics.get(gale)
            if metrics and metrics.hit_rate >= 0.7:
                optimal_gale = gale
                break

        return {
            "available": True,
            "version": "1.0.0",
            "summary": {
                "signals_evaluated": signals_evaluated,
                "signals_with_suggestion": signals_with_suggestion,
                "gale_levels_tested": gale_levels,
                "optimal_gale": optimal_gale,
            },
            "overall_metrics": overall_by_gale,
            "best_patterns": best_patterns,
            "worst_patterns": worst_patterns,
            "all_patterns": pattern_reports,
        }

    def get_pattern_report(self, pattern_id: str) -> Dict[str, Any]:
        """Retorna relatório detalhado de um padrão específico."""
        if pattern_id not in self._reports:
            return {
                "available": False,
                "pattern_id": pattern_id,
                "error": "Padrão não encontrado no backtest",
            }

        report = self._reports[pattern_id]
        return {
            "available": True,
            **report.to_dict(),
        }


# Instância singleton
backtest_engine = BacktestEngine()
