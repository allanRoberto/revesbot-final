"""
Suggestion Filter Module

Sistema de filtros de qualidade que decide se uma sugestão deve ser emitida
baseado em critérios como número de padrões ativos, confiança, pressão negativa
e sobreposição entre padrões.
"""
from __future__ import annotations

import copy
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


@dataclass
class FilterResult:
    """Resultado da avaliação de filtros."""
    passed: bool
    reason: str | None
    filter_details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "filter_details": self.filter_details,
        }


class SuggestionFilter:
    """
    Sistema de filtros de qualidade para sugestões.

    Verifica múltiplos critérios antes de permitir que uma sugestão seja emitida:
    - Número mínimo de padrões ativos
    - Confiança mínima
    - Pressão negativa máxima
    - Sobreposição mínima entre padrões (consenso)
    """

    DEFAULT_FILTERS = {
        "min_patterns": {"enabled": True, "threshold": 3},
        "min_confidence": {"enabled": True, "threshold": 55},
        "max_negative_pressure": {"enabled": True, "threshold": 0.45},
        "min_overlap_ratio": {"enabled": True, "threshold": 0.25},
    }

    def __init__(self, config_path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        self._config_path = config_path or (base_dir / "config" / "suggestion_filters.json")
        self._filters = copy.deepcopy(self.DEFAULT_FILTERS)
        self._load_config()

    def _load_config(self) -> None:
        """Carrega configuração do disco."""
        if not self._config_path.exists():
            return
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
            filters = raw.get("filters", {})
            for key, value in filters.items():
                if key in self._filters and isinstance(value, dict):
                    self._filters[key].update(value)
            logger.info("Suggestion filters loaded: %s", list(self._filters.keys()))
        except Exception as exc:
            logger.warning("Failed to load suggestion filters: %s", exc)

    def save_config(self) -> None:
        """Salva configuração no disco."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "version": "1.0.0",
                "description": "Configuracao de filtros de qualidade para sugestoes",
                "filters": self._filters,
            }
            self._config_path.write_text(
                json.dumps(data, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("Failed to save suggestion filters: %s", exc)

    def should_suggest(
        self,
        positive_contributions: List[Dict[str, Any]],
        confidence_context: Dict[str, float],
        confidence_score: int,
    ) -> FilterResult:
        """
        Decide se uma sugestão deve ser emitida.

        Args:
            positive_contributions: Lista de contribuições positivas
            confidence_context: Contexto de confiança (consensus_score, negative_pressure, etc.)
            confidence_score: Score de confiança final

        Returns:
            FilterResult indicando se passou e motivo de falha
        """
        filter_details = {}

        # 1. Filtro de padrões mínimos
        min_patterns_filter = self._filters.get("min_patterns", {})
        if min_patterns_filter.get("enabled", True):
            threshold = min_patterns_filter.get("threshold", 3)
            actual = len(positive_contributions)
            passed = actual >= threshold
            filter_details["min_patterns"] = {
                "passed": passed,
                "threshold": threshold,
                "actual": actual,
            }
            if not passed:
                return FilterResult(
                    passed=False,
                    reason=f"Padroes insuficientes: {actual}/{threshold}",
                    filter_details=filter_details,
                )

        # 2. Filtro de confiança mínima
        min_confidence_filter = self._filters.get("min_confidence", {})
        if min_confidence_filter.get("enabled", True):
            threshold = min_confidence_filter.get("threshold", 55)
            passed = confidence_score >= threshold
            filter_details["min_confidence"] = {
                "passed": passed,
                "threshold": threshold,
                "actual": confidence_score,
            }
            if not passed:
                return FilterResult(
                    passed=False,
                    reason=f"Confianca baixa: {confidence_score}/{threshold}",
                    filter_details=filter_details,
                )

        # 3. Filtro de pressão negativa
        max_neg_filter = self._filters.get("max_negative_pressure", {})
        if max_neg_filter.get("enabled", True):
            threshold = max_neg_filter.get("threshold", 0.45)
            actual = float(confidence_context.get("negative_pressure", 0.0))
            passed = actual <= threshold
            filter_details["max_negative_pressure"] = {
                "passed": passed,
                "threshold": threshold,
                "actual": round(actual, 3),
            }
            if not passed:
                return FilterResult(
                    passed=False,
                    reason=f"Pressao negativa alta: {actual:.2f}/{threshold}",
                    filter_details=filter_details,
                )

        # 4. Filtro de sobreposição (consenso)
        min_overlap_filter = self._filters.get("min_overlap_ratio", {})
        if min_overlap_filter.get("enabled", True):
            threshold = min_overlap_filter.get("threshold", 0.25)
            # Usa weighted_consensus ou consensus_score como métrica de sobreposição
            actual = max(
                float(confidence_context.get("weighted_consensus", 0.0)),
                float(confidence_context.get("consensus_score", 0.0)),
            )
            passed = actual >= threshold
            filter_details["min_overlap_ratio"] = {
                "passed": passed,
                "threshold": threshold,
                "actual": round(actual, 3),
            }
            if not passed:
                return FilterResult(
                    passed=False,
                    reason=f"Consenso baixo: {actual:.2f}/{threshold}",
                    filter_details=filter_details,
                )

        return FilterResult(
            passed=True,
            reason=None,
            filter_details=filter_details,
        )

    def get_filter_config(self) -> Dict[str, Any]:
        """Retorna configuração atual dos filtros."""
        return {
            "version": "1.0.0",
            "filters": self._filters,
        }

    def update_filter(
        self,
        filter_name: str,
        enabled: bool | None = None,
        threshold: float | int | None = None,
    ) -> Dict[str, Any]:
        """
        Atualiza configuração de um filtro específico.

        Args:
            filter_name: Nome do filtro
            enabled: Se o filtro está ativo
            threshold: Novo threshold

        Returns:
            Configuração atualizada do filtro
        """
        if filter_name not in self._filters:
            return {"error": f"Filtro '{filter_name}' nao encontrado"}

        if enabled is not None:
            self._filters[filter_name]["enabled"] = bool(enabled)
        if threshold is not None:
            self._filters[filter_name]["threshold"] = threshold

        self.save_config()
        return {
            "filter_name": filter_name,
            "updated": True,
            "config": self._filters[filter_name],
        }

    def disable_all(self) -> None:
        """Desabilita todos os filtros."""
        for filter_config in self._filters.values():
            filter_config["enabled"] = False
        self.save_config()

    def enable_all(self) -> None:
        """Habilita todos os filtros."""
        for filter_config in self._filters.values():
            filter_config["enabled"] = True
        self.save_config()

    def reset_to_defaults(self) -> None:
        """Restaura filtros para valores padrão."""
        self._filters = copy.deepcopy(self.DEFAULT_FILTERS)
        self.save_config()


# Instância singleton
suggestion_filter = SuggestionFilter()
