from __future__ import annotations

import ast
from pathlib import Path


EXCLUDED_FILES = {"__init__.py", "run_all_patterns.py", "registry.py"}


def _has_process_roulette(path: Path) -> bool:
    try:
        source = path.read_text(encoding="utf-8")
    except Exception:
        return False

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return False

    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "process_roulette":
            return True
    return False


def list_pattern_files(patterns_dir: Path | None = None) -> list[Path]:
    if patterns_dir is None:
        patterns_dir = Path(__file__).resolve().parent

    files: list[Path] = []
    for path in patterns_dir.glob("*.py"):
        if path.name in EXCLUDED_FILES:
            continue
        if _has_process_roulette(path):
            files.append(path)
    return sorted(files)
