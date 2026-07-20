"""Matriz 37x37 pre-calculada de relacoes orbitais."""

from __future__ import annotations

from .constants import validate_number
from .relations import build_pair_relation
from .schemas import PairRelation


class RelationMatrix:
    __slots__ = ("_matrix",)

    def __init__(self) -> None:
        self._matrix = tuple(
            tuple(build_pair_relation(source, target) for target in range(37))
            for source in range(37)
        )

    def get(self, source: int, target: int) -> PairRelation:
        return self._matrix[validate_number(source)][validate_number(target)]

    def related(self, source: int, relation_type: str) -> tuple[int, ...]:
        relation_name = str(relation_type).strip()
        values: list[int] = []
        for target in range(37):
            relation = self.get(source, target)
            if relation_name in relation.active_types():
                values.append(target)
        return tuple(values)


RELATION_MATRIX = RelationMatrix()
