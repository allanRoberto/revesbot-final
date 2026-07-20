"""Construcao cronologica de orbitas sem acesso a resultados futuros."""

from __future__ import annotations

from typing import Any, Iterable, Iterator, Sequence

from .constants import validate_number
from .schemas import OrbitContext, OrbitObservation, OrbitOccurrence, ReplayDecision


class OrbitBuilder:
    def __init__(
        self,
        *,
        pre_window: int = 5,
        post_window: int = 5,
        memory_occurrences: int = 6,
    ) -> None:
        self.pre_window = max(1, int(pre_window))
        self.post_window = max(1, int(post_window))
        self.memory_occurrences = max(1, int(memory_occurrences))

    @staticmethod
    def normalize_chronological(history: Iterable[Any]) -> tuple[int, ...]:
        return tuple(validate_number(value) for value in history)

    def build_context(self, history_chronological: Sequence[Any], anchor_index: int) -> OrbitContext:
        history = self.normalize_chronological(history_chronological)
        if not history:
            raise ValueError("historico vazio")
        anchor = int(anchor_index)
        if not 0 <= anchor < len(history):
            raise IndexError(f"anchor_index fora do historico: {anchor}")
        pivot = history[anchor]
        pivot_indexes = [index for index in range(anchor + 1) if history[index] == pivot]
        selected = pivot_indexes[-self.memory_occurrences :]
        return self._build_context_from_indexes(history, anchor, selected, pivot=pivot)

    def build_context_for_pivot(
        self,
        history_chronological: Sequence[Any],
        pivot: int,
        *,
        anchor_index: int | None = None,
    ) -> OrbitContext:
        """Monta a orbita de um pivo conhecido no instante atual da decisao."""

        history = self.normalize_chronological(history_chronological)
        if not history:
            raise ValueError("historico vazio")
        anchor = len(history) - 1 if anchor_index is None else int(anchor_index)
        if not 0 <= anchor < len(history):
            raise IndexError(f"anchor_index fora do historico: {anchor}")
        pivot_value = validate_number(pivot)
        selected = [
            index for index in range(anchor + 1) if history[index] == pivot_value
        ][-self.memory_occurrences :]
        if not selected:
            raise ValueError(f"pivo {pivot_value} nao encontrado ate o anchor")
        return self._build_context_from_indexes(
            history,
            anchor,
            selected,
            pivot=pivot_value,
        )

    def build_recent_pivot_contexts(
        self,
        history_chronological: Sequence[Any],
        *,
        pivot_count: int = 3,
        anchor_index: int | None = None,
    ) -> tuple[OrbitContext, ...]:
        history = self.normalize_chronological(history_chronological)
        if not history:
            raise ValueError("historico vazio")
        anchor = len(history) - 1 if anchor_index is None else int(anchor_index)
        if not 0 <= anchor < len(history):
            raise IndexError(f"anchor_index fora do historico: {anchor}")
        count = max(1, min(int(pivot_count), anchor + 1))
        recent_positions = range(anchor, anchor - count, -1)
        contexts: list[OrbitContext] = []
        for position in recent_positions:
            pivot = history[position]
            selected = [
                index for index in range(anchor + 1) if history[index] == pivot
            ][-self.memory_occurrences :]
            contexts.append(
                self._build_context_from_indexes(
                    history,
                    anchor,
                    selected,
                    pivot=pivot,
                )
            )
        return tuple(contexts)

    def _build_context_from_indexes(
        self,
        history: Sequence[int],
        anchor: int,
        selected: Sequence[int],
        *,
        pivot: int | None = None,
    ) -> OrbitContext:
        pivot_value = history[anchor] if pivot is None else validate_number(pivot)
        occurrences: list[OrbitOccurrence] = []

        for order, occurrence_index in enumerate(reversed(selected)):
            lag = -order
            observations: list[OrbitObservation] = []
            before_start = max(0, occurrence_index - self.pre_window)
            after_end = min(anchor, occurrence_index + self.post_window)
            for spin_index in range(before_start, occurrence_index):
                observations.append(
                    OrbitObservation(
                        pivot=pivot_value,
                        number=history[spin_index],
                        occurrence_lag=lag,
                        relative_offset=spin_index - occurrence_index,
                        spin_index=spin_index,
                        occurrence_index=occurrence_index,
                    )
                )
            # A ocorrencia atual nao conhece seu lado posterior. Para as antigas,
            # somente resultados com indice <= anchor podem ser observados.
            if occurrence_index < anchor:
                for spin_index in range(occurrence_index + 1, after_end + 1):
                    observations.append(
                        OrbitObservation(
                            pivot=pivot_value,
                            number=history[spin_index],
                            occurrence_lag=lag,
                            relative_offset=spin_index - occurrence_index,
                            spin_index=spin_index,
                            occurrence_index=occurrence_index,
                        )
                    )
            occurrences.append(
                OrbitOccurrence(
                    pivot=pivot_value,
                    occurrence_lag=lag,
                    pivot_spin_index=occurrence_index,
                    observations=tuple(observations),
                    completed_at_anchor=(occurrence_index + self.post_window <= anchor),
                )
            )

        return OrbitContext(
            pivot=pivot_value,
            anchor_index=anchor,
            occurrences=tuple(occurrences),
            pre_window=self.pre_window,
            post_window=self.post_window,
            memory_occurrences=self.memory_occurrences,
        )

    def replay_decisions(
        self,
        history_chronological: Sequence[Any],
        *,
        horizon: int = 3,
        warmup: int = 300,
        timestamps: Sequence[Any] | None = None,
    ) -> Iterator[ReplayDecision]:
        history = self.normalize_chronological(history_chronological)
        safe_horizon = max(1, int(horizon))
        safe_warmup = max(self.pre_window, int(warmup))
        if timestamps is not None and len(timestamps) != len(history):
            raise ValueError("timestamps e historico precisam ter o mesmo tamanho")
        positions: list[list[int]] = [[] for _ in range(37)]
        for anchor, pivot in enumerate(history):
            positions[pivot].append(anchor)
            if anchor < safe_warmup or anchor >= len(history) - safe_horizon:
                continue
            context = self._build_context_from_indexes(
                history,
                anchor,
                positions[pivot][-self.memory_occurrences :],
                pivot=pivot,
            )
            targets = tuple(history[anchor + 1 : anchor + 1 + safe_horizon])
            yield ReplayDecision(
                context=context,
                targets=targets,
                timestamp=(timestamps[anchor] if timestamps is not None else None),
            )
