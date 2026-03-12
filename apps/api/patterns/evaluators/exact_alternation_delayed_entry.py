from __future__ import annotations

from typing import Any, Dict, List


def evaluate(
    engine: Any,
    history: List[int],
    base_suggestion: List[int],
    from_index: int,
    definition: Any,
    focus_number: int | None = None,
) -> Dict[str, Any]:
    return engine._eval_exact_alternation_delayed_entry(
        history,
        base_suggestion,
        from_index,
        definition,
        focus_number,
    )
