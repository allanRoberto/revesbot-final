"""
Pattern Correlation Module

Identifica quais padrões funcionam melhor juntos através de uma matriz de correlação.
Quando múltiplos padrões ativam simultaneamente e acertam juntos, aumentamos o peso
das sugestões quando esses padrões co-ocorrem novamente.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PatternCoOccurrence:
    """Registra co-ocorrência entre dois padrões."""
    pattern_a: str
    pattern_b: str
    co_fires: int = 0        # Vezes que ambos ativaram juntos
    co_hits: int = 0         # Vezes que ambos acertaram juntos
    co_misses: int = 0       # Vezes que ambos erraram juntos
    correlation_score: float = 0.0  # Coeficiente de correlação

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_a": self.pattern_a,
            "pattern_b": self.pattern_b,
            "co_fires": self.co_fires,
            "co_hits": self.co_hits,
            "co_misses": self.co_misses,
            "correlation_score": round(self.correlation_score, 4),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternCoOccurrence":
        return cls(
            pattern_a=str(data.get("pattern_a", "")),
            pattern_b=str(data.get("pattern_b", "")),
            co_fires=int(data.get("co_fires", 0)),
            co_hits=int(data.get("co_hits", 0)),
            co_misses=int(data.get("co_misses", 0)),
            correlation_score=float(data.get("correlation_score", 0.0)),
        )


@dataclass
class CorrelationMatrix:
    """
    Matriz de correlação entre padrões.
    Armazena e calcula correlações baseadas em co-ocorrências.
    """
    _matrix: Dict[Tuple[str, str], PatternCoOccurrence] = field(default_factory=dict)
    _storage_path: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "correlation_matrix.json")
    _min_co_fires: int = 5  # Mínimo de co-ativações para considerar correlação válida
    _dirty: bool = False

    def __post_init__(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _normalize_key(self, pattern_a: str, pattern_b: str) -> Tuple[str, str]:
        """Normaliza a chave para evitar duplicatas (a,b) e (b,a)."""
        return tuple(sorted([pattern_a, pattern_b]))

    def _load(self) -> None:
        """Carrega matriz do disco."""
        if not self._storage_path.exists():
            return
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for item in raw.get("correlations", []):
                co = PatternCoOccurrence.from_dict(item)
                key = self._normalize_key(co.pattern_a, co.pattern_b)
                self._matrix[key] = co
            logger.info("Correlation matrix loaded: %d entries", len(self._matrix))
        except Exception as exc:
            logger.warning("Failed to load correlation matrix: %s", exc)

    def save(self) -> None:
        """Salva matriz no disco."""
        if not self._dirty:
            return
        try:
            data = {
                "version": "1.0.0",
                "correlations": [co.to_dict() for co in self._matrix.values()],
            }
            self._storage_path.write_text(
                json.dumps(data, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8"
            )
            self._dirty = False
            logger.info("Correlation matrix saved: %d entries", len(self._matrix))
        except Exception as exc:
            logger.warning("Failed to save correlation matrix: %s", exc)

    def update_correlation(
        self,
        active_patterns: List[str],
        hit: bool,
        suggested_numbers: List[int],
        actual_number: int | None = None,
    ) -> None:
        """
        Atualiza matriz após cada resultado.

        Args:
            active_patterns: IDs dos padrões que ativaram neste sinal
            hit: Se o sinal acertou
            suggested_numbers: Números sugeridos
            actual_number: Número que saiu (opcional)
        """
        if len(active_patterns) < 2:
            return

        # Cria pares de padrões
        patterns = sorted(set(active_patterns))
        for i, pattern_a in enumerate(patterns):
            for pattern_b in patterns[i + 1:]:
                key = self._normalize_key(pattern_a, pattern_b)

                if key not in self._matrix:
                    self._matrix[key] = PatternCoOccurrence(
                        pattern_a=key[0],
                        pattern_b=key[1],
                    )

                co = self._matrix[key]
                co.co_fires += 1

                if hit:
                    co.co_hits += 1
                else:
                    co.co_misses += 1

                # Recalcula correlação usando hit rate conjunto
                if co.co_fires >= self._min_co_fires:
                    co.correlation_score = co.co_hits / co.co_fires

        self._dirty = True

    def compute_correlation_boost(
        self,
        active_patterns: List[str],
        target_number: int | None = None,
    ) -> float:
        """
        Calcula boost baseado em correlações entre padrões ativos.

        Retorna multiplicador entre 0.7 e 1.4:
        - 1.0: correlação neutra
        - >1.0: padrões com boa correlação histórica
        - <1.0: padrões com má correlação histórica
        """
        if len(active_patterns) < 2:
            return 1.0

        patterns = sorted(set(active_patterns))
        total_score = 0.0
        valid_pairs = 0

        for i, pattern_a in enumerate(patterns):
            for pattern_b in patterns[i + 1:]:
                key = self._normalize_key(pattern_a, pattern_b)

                if key in self._matrix:
                    co = self._matrix[key]
                    if co.co_fires >= self._min_co_fires:
                        total_score += co.correlation_score
                        valid_pairs += 1

        if valid_pairs == 0:
            return 1.0

        avg_correlation = total_score / valid_pairs

        # Mapear: 0.0 -> 0.7, 0.5 -> 1.0, 1.0 -> 1.4
        boost = 0.7 + (avg_correlation * 0.7)
        return max(0.7, min(1.4, boost))

    def get_agreement_score(
        self,
        contributions: List[Dict[str, Any]],
        target_number: int,
    ) -> float:
        """
        Mede concordância entre padrões ativos para um número específico.

        Retorna score 0.0-1.0 indicando quanto os padrões concordam
        (todos sugerem o mesmo número vs sugestões dispersas).
        """
        if not contributions:
            return 0.0

        # Conta quantos padrões sugerem o número alvo
        supporting = 0
        for contrib in contributions:
            numbers = contrib.get("numbers", [])
            if target_number in numbers:
                supporting += 1

        return supporting / len(contributions)

    def get_pair_correlation(self, pattern_a: str, pattern_b: str) -> Dict[str, Any]:
        """Retorna dados de correlação entre dois padrões específicos."""
        key = self._normalize_key(pattern_a, pattern_b)

        if key not in self._matrix:
            return {
                "pattern_a": pattern_a,
                "pattern_b": pattern_b,
                "co_fires": 0,
                "co_hits": 0,
                "co_misses": 0,
                "correlation_score": 0.0,
                "valid": False,
            }

        co = self._matrix[key]
        return {
            **co.to_dict(),
            "valid": co.co_fires >= self._min_co_fires,
        }

    def get_best_partners(self, pattern_id: str, top_n: int = 5) -> List[Dict[str, Any]]:
        """Retorna os padrões com melhor correlação com o padrão especificado."""
        partners = []

        for key, co in self._matrix.items():
            if pattern_id not in key:
                continue
            if co.co_fires < self._min_co_fires:
                continue

            partner = key[1] if key[0] == pattern_id else key[0]
            partners.append({
                "partner_id": partner,
                "co_fires": co.co_fires,
                "co_hits": co.co_hits,
                "correlation_score": co.correlation_score,
            })

        partners.sort(key=lambda x: -x["correlation_score"])
        return partners[:top_n]

    def get_matrix_summary(self) -> Dict[str, Any]:
        """Retorna resumo completo da matriz de correlação."""
        valid_pairs = []
        total_co_fires = 0
        total_co_hits = 0

        for co in self._matrix.values():
            total_co_fires += co.co_fires
            total_co_hits += co.co_hits

            if co.co_fires >= self._min_co_fires:
                valid_pairs.append(co.to_dict())

        valid_pairs.sort(key=lambda x: -x["correlation_score"])

        return {
            "version": "1.0.0",
            "total_pairs": len(self._matrix),
            "valid_pairs": len(valid_pairs),
            "total_co_fires": total_co_fires,
            "total_co_hits": total_co_hits,
            "overall_correlation": round(total_co_hits / total_co_fires, 4) if total_co_fires > 0 else 0.0,
            "top_positive": valid_pairs[:10],
            "top_negative": sorted(valid_pairs, key=lambda x: x["correlation_score"])[:10],
            "min_co_fires_threshold": self._min_co_fires,
        }

    def clear(self) -> None:
        """Limpa toda a matriz."""
        self._matrix.clear()
        self._dirty = True
        self.save()


# Instância singleton
correlation_matrix = CorrelationMatrix()
