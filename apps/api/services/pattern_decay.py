"""
Pattern Decay Module

Sistema de decay que reduz o peso de padrões que estão falhando consecutivamente.
Padrões que erram muito são temporariamente penalizados ou desabilitados.
Quando começam a acertar novamente, recuperam gradualmente o peso.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class DecayConfig:
    """Configuração do sistema de decay."""
    decay_start_misses: int = 3      # Inicia decay após N erros consecutivos
    decay_per_miss: float = 0.10     # Redução percentual por erro (10%)
    max_decay: float = 0.50          # Máximo de redução (50%)
    disable_threshold: int = 8       # Desabilita após N erros consecutivos
    recovery_hits_needed: int = 3    # Acertos necessários para recuperar
    recovery_per_hit: float = 0.15   # Recuperação por acerto (15%)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decay_start_misses": self.decay_start_misses,
            "decay_per_miss": self.decay_per_miss,
            "max_decay": self.max_decay,
            "disable_threshold": self.disable_threshold,
            "recovery_hits_needed": self.recovery_hits_needed,
            "recovery_per_hit": self.recovery_per_hit,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecayConfig":
        return cls(
            decay_start_misses=int(data.get("decay_start_misses", 3)),
            decay_per_miss=float(data.get("decay_per_miss", 0.10)),
            max_decay=float(data.get("max_decay", 0.50)),
            disable_threshold=int(data.get("disable_threshold", 8)),
            recovery_hits_needed=int(data.get("recovery_hits_needed", 3)),
            recovery_per_hit=float(data.get("recovery_per_hit", 0.15)),
        )


@dataclass
class PatternDecayState:
    """Estado de decay de um padrão específico."""
    pattern_id: str
    consecutive_misses: int = 0
    consecutive_hits: int = 0
    current_decay: float = 0.0       # Percentual de decay aplicado (0.0 - 0.5)
    is_disabled: bool = False
    total_signals: int = 0
    total_hits: int = 0
    total_misses: int = 0
    last_updated: str = ""

    @property
    def multiplier(self) -> float:
        """Retorna multiplicador atual (1.0 - decay)."""
        if self.is_disabled:
            return 0.0
        return max(0.5, 1.0 - self.current_decay)

    @property
    def hit_rate(self) -> float:
        """Taxa de acerto histórica."""
        return self.total_hits / self.total_signals if self.total_signals > 0 else 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "consecutive_misses": self.consecutive_misses,
            "consecutive_hits": self.consecutive_hits,
            "current_decay": round(self.current_decay, 4),
            "multiplier": round(self.multiplier, 4),
            "is_disabled": self.is_disabled,
            "total_signals": self.total_signals,
            "total_hits": self.total_hits,
            "total_misses": self.total_misses,
            "hit_rate": round(self.hit_rate, 4),
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PatternDecayState":
        return cls(
            pattern_id=str(data.get("pattern_id", "")),
            consecutive_misses=int(data.get("consecutive_misses", 0)),
            consecutive_hits=int(data.get("consecutive_hits", 0)),
            current_decay=float(data.get("current_decay", 0.0)),
            is_disabled=bool(data.get("is_disabled", False)),
            total_signals=int(data.get("total_signals", 0)),
            total_hits=int(data.get("total_hits", 0)),
            total_misses=int(data.get("total_misses", 0)),
            last_updated=str(data.get("last_updated", "")),
        )


class PatternDecayManager:
    """
    Gerenciador de decay de padrões.

    Controla multiplicadores baseados em performance recente.
    Padrões que erram consecutivamente têm peso reduzido.
    Padrões que acertam recuperam o peso gradualmente.
    """

    def __init__(self, storage_path: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent
        data_dir = base_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self._storage_path = storage_path or (data_dir / "pattern_decay_state.json")
        self._states: Dict[str, PatternDecayState] = {}
        self._config = DecayConfig()
        self._dirty = False
        self._load()

    def _load(self) -> None:
        """Carrega estado do disco."""
        if not self._storage_path.exists():
            return
        try:
            raw = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if "config" in raw:
                self._config = DecayConfig.from_dict(raw["config"])
            for item in raw.get("states", []):
                state = PatternDecayState.from_dict(item)
                self._states[state.pattern_id] = state
            logger.info("Pattern decay loaded: %d patterns", len(self._states))
        except Exception as exc:
            logger.warning("Failed to load pattern decay state: %s", exc)

    def save(self) -> None:
        """Salva estado no disco."""
        if not self._dirty:
            return
        try:
            data = {
                "version": "1.0.0",
                "config": self._config.to_dict(),
                "states": [s.to_dict() for s in self._states.values()],
            }
            self._storage_path.write_text(
                json.dumps(data, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8"
            )
            self._dirty = False
            logger.info("Pattern decay saved: %d patterns", len(self._states))
        except Exception as exc:
            logger.warning("Failed to save pattern decay state: %s", exc)

    def record_result(self, pattern_id: str, hit: bool) -> PatternDecayState:
        """
        Registra resultado de um sinal para o padrão.

        Args:
            pattern_id: ID do padrão
            hit: Se o sinal acertou

        Returns:
            Estado atualizado do padrão
        """
        if pattern_id not in self._states:
            self._states[pattern_id] = PatternDecayState(pattern_id=pattern_id)

        state = self._states[pattern_id]
        state.total_signals += 1
        state.last_updated = datetime.now(timezone.utc).isoformat()

        if hit:
            state.total_hits += 1
            state.consecutive_hits += 1
            state.consecutive_misses = 0

            # Recuperação de decay
            if state.consecutive_hits >= self._config.recovery_hits_needed:
                recovery = self._config.recovery_per_hit * state.consecutive_hits
                state.current_decay = max(0.0, state.current_decay - recovery)

                # Reabilita se estava desabilitado e recuperou
                if state.is_disabled and state.current_decay < self._config.max_decay * 0.5:
                    state.is_disabled = False
                    logger.info("Pattern %s reabilitado apos recuperacao", pattern_id)

        else:
            state.total_misses += 1
            state.consecutive_misses += 1
            state.consecutive_hits = 0

            # Aplica decay após threshold de misses
            if state.consecutive_misses >= self._config.decay_start_misses:
                extra_misses = state.consecutive_misses - self._config.decay_start_misses + 1
                new_decay = self._config.decay_per_miss * extra_misses
                state.current_decay = min(self._config.max_decay, state.current_decay + new_decay)

            # Desabilita se atingiu threshold
            if state.consecutive_misses >= self._config.disable_threshold:
                state.is_disabled = True
                logger.info("Pattern %s desabilitado apos %d misses", pattern_id, state.consecutive_misses)

        self._dirty = True
        return state

    def record_batch_result(
        self,
        pattern_ids: list[str],
        hit: bool,
    ) -> Dict[str, PatternDecayState]:
        """Registra resultado para múltiplos padrões."""
        results = {}
        for pattern_id in pattern_ids:
            results[pattern_id] = self.record_result(pattern_id, hit)
        return results

    def get_multiplier(self, pattern_id: str) -> float:
        """
        Retorna multiplicador atual para o padrão.

        Returns:
            Multiplicador entre 0.0 (desabilitado) e 1.0 (sem decay)
        """
        if pattern_id not in self._states:
            return 1.0
        return self._states[pattern_id].multiplier

    def is_disabled(self, pattern_id: str) -> bool:
        """Verifica se padrão está desabilitado por decay."""
        if pattern_id not in self._states:
            return False
        return self._states[pattern_id].is_disabled

    def get_pattern_state(self, pattern_id: str) -> Dict[str, Any]:
        """Retorna estado completo de um padrão."""
        if pattern_id not in self._states:
            return {
                "pattern_id": pattern_id,
                "exists": False,
                "multiplier": 1.0,
            }
        return {
            "exists": True,
            **self._states[pattern_id].to_dict(),
        }

    def get_decay_report(self) -> Dict[str, Any]:
        """Retorna relatório completo de decay de todos os padrões."""
        patterns = []
        disabled_count = 0
        decaying_count = 0

        for state in self._states.values():
            patterns.append(state.to_dict())
            if state.is_disabled:
                disabled_count += 1
            elif state.current_decay > 0:
                decaying_count += 1

        patterns.sort(key=lambda x: (-x["current_decay"], -x["consecutive_misses"]))

        return {
            "version": "1.0.0",
            "config": self._config.to_dict(),
            "summary": {
                "total_patterns": len(patterns),
                "disabled_patterns": disabled_count,
                "decaying_patterns": decaying_count,
                "healthy_patterns": len(patterns) - disabled_count - decaying_count,
            },
            "patterns": patterns,
        }

    def reset_pattern(self, pattern_id: str) -> Dict[str, Any]:
        """
        Reseta estado de decay de um padrão.

        Returns:
            Estado resetado
        """
        if pattern_id not in self._states:
            return {
                "pattern_id": pattern_id,
                "reset": False,
                "reason": "Padrao nao encontrado",
            }

        self._states[pattern_id] = PatternDecayState(
            pattern_id=pattern_id,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )
        self._dirty = True
        self.save()

        return {
            "pattern_id": pattern_id,
            "reset": True,
            "state": self._states[pattern_id].to_dict(),
        }

    def reset_all(self) -> Dict[str, Any]:
        """Reseta decay de todos os padrões."""
        count = len(self._states)
        self._states.clear()
        self._dirty = True
        self.save()

        return {
            "reset": True,
            "patterns_cleared": count,
        }

    def configure(
        self,
        decay_start_misses: int | None = None,
        decay_per_miss: float | None = None,
        max_decay: float | None = None,
        disable_threshold: int | None = None,
        recovery_hits_needed: int | None = None,
        recovery_per_hit: float | None = None,
    ) -> Dict[str, Any]:
        """
        Atualiza configuração de decay.

        Returns:
            Configuração atualizada
        """
        if decay_start_misses is not None:
            self._config.decay_start_misses = max(1, int(decay_start_misses))
        if decay_per_miss is not None:
            self._config.decay_per_miss = max(0.01, min(0.5, float(decay_per_miss)))
        if max_decay is not None:
            self._config.max_decay = max(0.1, min(0.9, float(max_decay)))
        if disable_threshold is not None:
            self._config.disable_threshold = max(3, int(disable_threshold))
        if recovery_hits_needed is not None:
            self._config.recovery_hits_needed = max(1, int(recovery_hits_needed))
        if recovery_per_hit is not None:
            self._config.recovery_per_hit = max(0.01, min(0.5, float(recovery_per_hit)))

        self._dirty = True
        self.save()

        return {
            "updated": True,
            "config": self._config.to_dict(),
        }

    def get_disabled_patterns(self) -> list[str]:
        """Retorna lista de IDs de padrões desabilitados."""
        return [
            state.pattern_id
            for state in self._states.values()
            if state.is_disabled
        ]


# Instância singleton
pattern_decay = PatternDecayManager()
