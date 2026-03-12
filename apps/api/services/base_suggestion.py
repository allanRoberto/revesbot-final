"""
Serviço de Sugestão Base (Legacy)

Este módulo implementa a lógica de sugestão base que estava no frontend (api.html).
Inclui:
- Análise de puxadas (pulled numbers)
- Bucket analysis (dúzia, coluna, cor, setor, etc.)
- Construção de sugestão com filtros dominantes
- Sinais extras (setor, proteção local, cerco)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

# Ordem dos números na roleta europeia (sentido horário)
WHEEL_ORDER: List[int] = [
    0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6,
    27, 13, 36, 11, 30, 8, 23, 10, 5, 24,
    16, 33, 1, 20, 14, 31, 9, 22, 18, 29,
    7, 28, 12, 35, 3, 26,
]

WHEEL_INDEX: Dict[int, int] = {n: i for i, n in enumerate(WHEEL_ORDER)}

# Números vermelhos
RED_NUMBERS: Set[int] = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}

# Setores da roleta
SECTION_MAP: Dict[str, List[int]] = {
    "Jeu Zero": [12, 35, 3, 26, 0, 32, 15],
    "Voisins": [22, 18, 29, 7, 28, 12, 35, 3, 26, 0, 32, 15, 19, 4, 21, 2, 25],
    "Orphelins": [17, 34, 6, 1, 20, 14, 31, 9],
    "Tiers": [27, 13, 36, 11, 30, 8, 23, 10, 5, 24, 16, 33],
}

# Mapa de espelhos
MIRROR_MAP: Dict[int, List[int]] = {
    1: [10], 2: [20], 3: [30], 4: [], 5: [], 6: [], 7: [], 8: [], 9: [],
    10: [1], 11: [], 12: [21], 13: [31], 14: [], 15: [], 16: [], 17: [], 18: [],
    19: [], 20: [2], 21: [12], 22: [], 23: [32], 24: [], 25: [], 26: [], 27: [],
    28: [], 29: [], 30: [3], 31: [13], 32: [23], 33: [], 34: [], 35: [], 36: [], 0: [],
}


@dataclass
class Bucket:
    """Estatísticas dos números puxados"""
    dozen: Dict[str, int]
    column: Dict[str, int]
    highlow: Dict[str, int]
    parity: Dict[str, int]
    color: Dict[str, int]
    section: Dict[str, int]
    horse: Dict[str, int]


@dataclass
class DominantPick:
    """Padrão dominante detectado"""
    category: str
    key: str
    count: int
    ratio: float


@dataclass
class BaseSuggestionResult:
    """Resultado da sugestão base"""
    available: bool
    suggestion: List[int]
    confidence: Dict[str, any]
    pulled_numbers: List[int]
    pulled_counts: Dict[int, int]
    bucket: Dict[str, Dict[str, int]]
    dominant_patterns: List[Dict[str, any]]
    signals: Dict[str, any]
    explanation: str


def get_color(n: int) -> str:
    """Retorna a cor do número"""
    if n == 0:
        return "green"
    return "red" if n in RED_NUMBERS else "black"


def get_dozen(n: int) -> str:
    """Retorna a dúzia do número (labels idênticos ao frontend)"""
    if n == 0:
        return "Zero"
    if n <= 12:
        return "1ª"
    if n <= 24:
        return "2ª"
    return "3ª"


def get_column(n: int) -> str:
    """Retorna a coluna do número (labels idênticos ao frontend)"""
    if n == 0:
        return "Zero"
    col = (n - 1) % 3
    if col == 0:
        return "C1"
    if col == 1:
        return "C2"
    return "C3"


def get_highlow(n: int) -> str:
    """Retorna se é alto ou baixo (labels idênticos ao frontend)"""
    if n == 0:
        return "Zero"
    return "Baixo" if n <= 18 else "Alto"


def get_parity(n: int) -> str:
    """Retorna paridade (labels idênticos ao frontend)"""
    if n == 0:
        return "Zero"
    return "Par" if n % 2 == 0 else "Ímpar"


def get_sections(n: int) -> List[str]:
    """Retorna os setores que contêm o número"""
    sections = []
    for name, numbers in SECTION_MAP.items():
        if n in numbers:
            sections.append(name)
    return sections


def get_neighbors(n: int, span: int = 2) -> List[int]:
    """Retorna os vizinhos na roleta"""
    if n not in WHEEL_INDEX:
        return []
    idx = WHEEL_INDEX[n]
    neighbors = []
    for offset in range(-span, span + 1):
        if offset != 0:
            neighbor_idx = (idx + offset) % len(WHEEL_ORDER)
            neighbors.append(WHEEL_ORDER[neighbor_idx])
    return neighbors


def analyze_pulled_numbers(
    history: List[int],
    focus_number: int,
    from_index: int = 0
) -> Tuple[List[int], Dict[int, int]]:
    """
    Analisa os números que foram "puxados" pelo número foco.

    Lógica idêntica ao frontend (api.html):
    - history = [mais recente, ..., mais antigo]
    - Se focus_number aparece em idx, o "puxado" é history[idx - 1]
    - Ou seja, o número que veio DEPOIS do focus_number em tempo real

    Args:
        history: Lista de resultados (mais recente primeiro)
        focus_number: Número para analisar
        from_index: Índice inicial no histórico

    Returns:
        Tuple com lista de puxados e contagem de cada um
    """
    occurrences = []

    # Encontra todas as ocorrências do número foco
    for i in range(from_index, len(history)):
        if history[i] == focus_number:
            occurrences.append(i)

    # Pega os números que vieram DEPOIS de cada ocorrência (idx - 1 no array)
    # Isso porque o array está ordenado do mais recente para o mais antigo
    pulled = []
    for idx in occurrences:
        if from_index is not None:
            if idx - 1 >= from_index and idx - 1 >= 0:
                pulled.append(history[idx - 1])
        elif idx > 0:
            pulled.append(history[idx - 1])

    # Conta frequência de cada puxado
    pulled_counts: Dict[int, int] = defaultdict(int)
    for n in pulled:
        pulled_counts[n] += 1

    return pulled, dict(pulled_counts)


def build_bucket(pulled: List[int]) -> Bucket:
    """
    Classifica os números puxados em categorias estatísticas.
    Labels idênticos ao frontend (api.html).
    """
    bucket = Bucket(
        dozen={"1ª": 0, "2ª": 0, "3ª": 0, "Zero": 0},
        column={"C1": 0, "C2": 0, "C3": 0, "Zero": 0},
        highlow={"Baixo": 0, "Alto": 0, "Zero": 0},
        parity={"Par": 0, "Ímpar": 0, "Zero": 0},
        color={"red": 0, "black": 0, "green": 0},
        section={"Jeu Zero": 0, "Voisins": 0, "Orphelins": 0, "Tiers": 0},
        horse={"147": 0, "258": 0, "036": 0, "369": 0},
    )

    for n in pulled:
        bucket.dozen[get_dozen(n)] += 1
        bucket.column[get_column(n)] += 1
        bucket.highlow[get_highlow(n)] += 1
        bucket.parity[get_parity(n)] += 1
        bucket.color[get_color(n)] += 1

        for sec in get_sections(n):
            if sec in bucket.section:
                bucket.section[sec] += 1

        # Cavalos (terminais)
        term = n % 10
        if term in [1, 4, 7]:
            bucket.horse["147"] += 1
        if term in [2, 5, 8]:
            bucket.horse["258"] += 1
        if term in [0, 3, 6]:
            bucket.horse["036"] += 1
        if term in [3, 6, 9]:
            bucket.horse["369"] += 1

    return bucket


def find_dominant(
    category_counts: Dict[str, int],
    total: int,
    min_ratio: float = 0.6,
    min_count: int = 3
) -> Optional[DominantPick]:
    """
    Encontra o padrão dominante em uma categoria.
    """
    if total < min_count:
        return None

    sorted_items = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)
    if not sorted_items:
        return None

    key, count = sorted_items[0]
    if count < min_count:
        return None

    ratio = count / total
    if ratio < min_ratio:
        return None

    return DominantPick(category="", key=key, count=count, ratio=ratio)


def analyze_sector_signal(
    history: List[int],
    from_index: int = 0,
    window: int = 20
) -> Dict[str, any]:
    """
    Analisa sinais de alternância de setores.
    """
    segment = history[from_index:from_index + window]
    if len(segment) < 6:
        return {"alternation_active": False, "target_zone": set(), "cold_numbers": set()}

    # Conta frequência por posição na roleta
    freq_by_idx: Dict[int, int] = defaultdict(int)
    for n in segment:
        if n in WHEEL_INDEX:
            freq_by_idx[WHEEL_INDEX[n]] += 1

    # Encontra zona quente e fria
    hot_indices = []
    cold_indices = []
    avg_freq = len(segment) / 37

    for idx in range(37):
        freq = freq_by_idx.get(idx, 0)
        if freq > avg_freq * 1.5:
            hot_indices.append(idx)
        elif freq < avg_freq * 0.5:
            cold_indices.append(idx)

    # Zona alvo: oposta à zona quente
    target_zone = set()
    if hot_indices:
        # Zona oposta (180 graus)
        for hot_idx in hot_indices:
            opposite_idx = (hot_idx + 18) % 37
            for offset in range(-3, 4):
                target_idx = (opposite_idx + offset) % 37
                target_zone.add(WHEEL_ORDER[target_idx])

    cold_numbers = {WHEEL_ORDER[idx] for idx in cold_indices}

    return {
        "alternation_active": len(hot_indices) >= 2,
        "target_zone": target_zone,
        "cold_numbers": cold_numbers,
    }


def analyze_local_protection(
    history: List[int],
    from_index: int = 0,
    window: int = 100
) -> Dict[str, any]:
    """
    Analisa proteção local (números que aparecem em transições).
    """
    segment = history[from_index:from_index + window]
    if len(segment) < 10:
        return {"active": False, "boosts": {}}

    # Analisa transições (pares consecutivos)
    transition_counts: Dict[int, int] = defaultdict(int)
    for i in range(len(segment) - 1):
        curr, prev = segment[i], segment[i + 1]
        # Números que aparecem após transições específicas
        transition_counts[curr] += 1

    # Boost para números com mais transições
    avg_transitions = sum(transition_counts.values()) / max(1, len(transition_counts))
    boosts: Dict[int, float] = {}

    for n, count in transition_counts.items():
        if count > avg_transitions * 1.3:
            boosts[n] = min(2.0, (count / avg_transitions) * 0.8)

    return {
        "active": len(boosts) > 0,
        "boosts": boosts,
    }


def analyze_siege_signal(
    history: List[int],
    from_index: int = 0,
    window: int = 6,
    min_occurrences: int = 3
) -> Dict[str, any]:
    """
    Analisa sinal de cerco (números que aparecem muito em sequência).
    """
    segment = history[from_index:from_index + window]
    if len(segment) < window:
        return {"active": False, "strong_set": set(), "scores": {}}

    # Conta frequência na janela
    freq: Dict[int, int] = defaultdict(int)
    for n in segment:
        freq[n] += 1

    # Números cercados (aparecem >= min_occurrences vezes)
    strong_set = set()
    scores: Dict[int, float] = {}

    for n, count in freq.items():
        if count >= min_occurrences:
            strong_set.add(n)
            scores[n] = count * 1.5

    return {
        "active": len(strong_set) > 0,
        "strong_set": strong_set,
        "scores": scores,
    }


def compute_confidence(bucket: Bucket, total_pulled: int) -> Dict[str, any]:
    """
    Calcula a confiança baseada nos padrões dominantes.
    """
    if total_pulled < 3:
        return {"score": 0, "label": "Muito Baixa"}

    score = 0
    dominant_count = 0

    # Verifica cada categoria
    categories = [
        ("dozen", bucket.dozen),
        ("column", bucket.column),
        ("highlow", bucket.highlow),
        ("parity", bucket.parity),
        ("color", bucket.color),
        ("section", bucket.section),
    ]

    for cat_name, cat_data in categories:
        # Filtra valores zero
        filtered = {k: v for k, v in cat_data.items() if k not in ["Zero", "green"]}
        dom = find_dominant(filtered, total_pulled, min_ratio=0.55, min_count=2)
        if dom:
            dominant_count += 1
            score += dom.ratio * 15

    # Bônus por múltiplos dominantes
    if dominant_count >= 4:
        score += 20
    elif dominant_count >= 3:
        score += 12
    elif dominant_count >= 2:
        score += 5

    # Bônus por volume de dados
    if total_pulled >= 20:
        score += 10
    elif total_pulled >= 10:
        score += 5

    score = max(0, min(100, int(score)))

    if score >= 85:
        label = "Muito Alta"
    elif score >= 70:
        label = "Alta"
    elif score >= 55:
        label = "Media"
    elif score >= 40:
        label = "Baixa"
    else:
        label = "Muito Baixa"

    return {"score": score, "label": label}


def build_base_suggestion(
    bucket: Bucket,
    pulled_counts: Dict[int, int],
    total_pulled: int,
    history: List[int],
    from_index: int = 0,
    max_numbers: int = 12,
    siege_veto_relief: float = 0.5,
) -> Tuple[List[int], List[Dict], str]:
    """
    Constrói a sugestão base a partir dos padrões dominantes.

    Returns:
        Tuple com (lista de números, padrões dominantes, explicação)
    """
    if total_pulled < 3:
        return [], [], "Dados insuficientes para sugestão base."

    dominant_patterns = []

    # Detecta padrões dominantes
    def check_dominant(category: str, data: Dict[str, int]) -> Optional[DominantPick]:
        filtered = {k: v for k, v in data.items() if k not in ["Zero", "green"]}
        dom = find_dominant(filtered, total_pulled, min_ratio=0.6, min_count=3)
        if dom:
            dom.category = category
            dominant_patterns.append({
                "category": category,
                "key": dom.key,
                "count": dom.count,
                "ratio": round(dom.ratio, 3),
            })
            return dom
        return None

    picks = []

    dozen_dom = check_dominant("dozen", bucket.dozen)
    if dozen_dom:
        picks.append(("dozen", dozen_dom.key))

    column_dom = check_dominant("column", bucket.column)
    if column_dom:
        picks.append(("column", column_dom.key))

    section_dom = check_dominant("section", bucket.section)
    if section_dom:
        picks.append(("section", section_dom.key))

    highlow_dom = check_dominant("highlow", bucket.highlow)
    if highlow_dom:
        picks.append(("highlow", highlow_dom.key))

    parity_dom = check_dominant("parity", bucket.parity)
    if parity_dom:
        picks.append(("parity", parity_dom.key))

    color_dom = check_dominant("color", bucket.color)
    if color_dom:
        picks.append(("color", color_dom.key))

    # Começa com todos os números (1-36)
    base = list(range(1, 37))

    # Aplica filtros (labels idênticos ao frontend)
    def apply_filter(category: str, key: str):
        nonlocal base
        if category == "dozen":
            if key == "1ª":
                base = [n for n in base if 1 <= n <= 12]
            elif key == "2ª":
                base = [n for n in base if 13 <= n <= 24]
            elif key == "3ª":
                base = [n for n in base if 25 <= n <= 36]
        elif category == "column":
            # Frontend: (n-1) % 3 === 0 ? C1 : (n-1) % 3 === 1 ? C2 : C3
            if key == "C1":
                base = [n for n in base if (n - 1) % 3 == 0]
            elif key == "C2":
                base = [n for n in base if (n - 1) % 3 == 1]
            elif key == "C3":
                base = [n for n in base if (n - 1) % 3 == 2]
        elif category == "section":
            if key in SECTION_MAP:
                base = [n for n in base if n in SECTION_MAP[key]]
        elif category == "highlow":
            if key == "Baixo":
                base = [n for n in base if n <= 18]
            elif key == "Alto":
                base = [n for n in base if n >= 19]
        elif category == "parity":
            if key == "Par":
                base = [n for n in base if n % 2 == 0 and n != 0]
            elif key == "Ímpar":
                base = [n for n in base if n % 2 == 1]
        elif category == "color":
            if key == "red":
                base = [n for n in base if n in RED_NUMBERS]
            elif key == "black":
                base = [n for n in base if n not in RED_NUMBERS and n != 0]

    # Aplica todos os filtros dominantes
    for category, key in picks:
        apply_filter(category, key)

    # Se ficou vazio, relaxa filtros (remove o menos dominante)
    if not base and picks:
        base = list(range(1, 37))
        # Reordena por ratio e aplica todos menos o mais fraco
        sorted_patterns = sorted(dominant_patterns, key=lambda x: x["ratio"])
        for pattern in sorted_patterns[1:]:
            apply_filter(pattern["category"], pattern["key"])

    # Se ainda vazio ou muito grande, usa top puxados
    if not base or len(base) == 36:
        top_pulled = sorted(pulled_counts.items(), key=lambda x: x[1], reverse=True)[:12]
        base = [int(n) for n, _ in top_pulled if isinstance(n, int) or str(n).isdigit()]
        base = [int(n) for n in base]

    # Adiciona vizinhos se lista muito pequena
    if len(base) == 1:
        n = base[0]
        neighbors = get_neighbors(n, 2)
        base = list(set([n] + neighbors))

    # Analisa sinais extras
    sector_signal = analyze_sector_signal(history, from_index)
    local_protection = analyze_local_protection(history, from_index)
    siege_signal = analyze_siege_signal(history, from_index)

    # Função de scoring
    def score_candidate(n: int) -> float:
        s = 0.0

        # Score por frequência nos puxados
        if n in pulled_counts:
            s += pulled_counts[n] * 1.2

        # Score por alternância de setor
        if sector_signal["alternation_active"] and n in sector_signal["target_zone"]:
            s += 2.4

        # Penalidade por zona fria
        cold_penalty = 2.1 if n in sector_signal["cold_numbers"] else 0

        # Reduz penalidade se está em cerco
        if siege_signal["active"] and n in siege_signal["strong_set"]:
            cold_penalty *= max(0, 1 - siege_veto_relief)

        s -= cold_penalty

        # Boost de proteção local
        if local_protection["active"] and n in local_protection["boosts"]:
            s += local_protection["boosts"][n]

        # Score de cerco
        if siege_signal["active"] and n in siege_signal["scores"]:
            s += siege_signal["scores"][n]

        return s

    # Ranqueia candidatos
    candidates = list(set(base))
    candidates = [n for n in candidates if isinstance(n, int) and 0 <= n <= 36]
    ranked = sorted(candidates, key=lambda n: (-score_candidate(n), n))

    # Pega top N e ordena numericamente (igual ao frontend)
    result = sorted(ranked[:max_numbers])

    # Constrói explicação
    if dominant_patterns:
        patterns_str = ", ".join([f"{p['category']}={p['key']} ({p['ratio']*100:.0f}%)" for p in dominant_patterns])
        explanation = f"Sugestao baseada em {len(dominant_patterns)} padrao(es) dominante(s): {patterns_str}"
    else:
        explanation = "Sugestao baseada nos numeros mais puxados."

    return result, dominant_patterns, explanation


def build_extended_suggestion(numbers: List[int]) -> List[int]:
    """
    Expande a sugestão com vizinhos e espelhos.
    """
    extended = set(numbers)

    for n in numbers:
        # Adiciona vizinhos numéricos
        if n - 1 >= 0:
            extended.add(n - 1)
        if n + 1 <= 36:
            extended.add(n + 1)

        # Adiciona espelhos
        mirrors = MIRROR_MAP.get(n, [])
        for m in mirrors:
            extended.add(m)

    return sorted(extended)


def generate_base_suggestion(
    history: List[int],
    focus_number: int,
    from_index: int = 0,
    max_numbers: int = 12,
) -> BaseSuggestionResult:
    """
    Gera a sugestão base completa para um número foco.

    Esta função implementa toda a lógica que estava no frontend (api.html).
    """
    if len(history) < 5:
        return BaseSuggestionResult(
            available=False,
            suggestion=[],
            confidence={"score": 0, "label": "Muito Baixa"},
            pulled_numbers=[],
            pulled_counts={},
            bucket={},
            dominant_patterns=[],
            signals={},
            explanation="Historico insuficiente.",
        )

    # 1. Analisa puxadas
    pulled, pulled_counts = analyze_pulled_numbers(history, focus_number, from_index)

    if len(pulled) < 3:
        return BaseSuggestionResult(
            available=False,
            suggestion=[],
            confidence={"score": 0, "label": "Muito Baixa"},
            pulled_numbers=pulled,
            pulled_counts=pulled_counts,
            bucket={},
            dominant_patterns=[],
            signals={},
            explanation=f"Numero {focus_number} tem poucas ocorrencias ({len(pulled)} puxadas).",
        )

    # 2. Constrói bucket de estatísticas
    bucket = build_bucket(pulled)

    # 3. Calcula confiança
    confidence = compute_confidence(bucket, len(pulled))

    # 4. Constrói sugestão base
    suggestion, dominant_patterns, explanation = build_base_suggestion(
        bucket=bucket,
        pulled_counts=pulled_counts,
        total_pulled=len(pulled),
        history=history,
        from_index=from_index,
        max_numbers=max_numbers,
    )

    # 5. Coleta sinais
    signals = {
        "sector": analyze_sector_signal(history, from_index),
        "local_protection": analyze_local_protection(history, from_index),
        "siege": analyze_siege_signal(history, from_index),
    }

    # Converte bucket para dict
    bucket_dict = {
        "dozen": bucket.dozen,
        "column": bucket.column,
        "highlow": bucket.highlow,
        "parity": bucket.parity,
        "color": bucket.color,
        "section": bucket.section,
        "horse": bucket.horse,
    }

    return BaseSuggestionResult(
        available=len(suggestion) > 0,
        suggestion=suggestion,
        confidence=confidence,
        pulled_numbers=pulled,
        pulled_counts=pulled_counts,
        bucket=bucket_dict,
        dominant_patterns=dominant_patterns,
        signals=signals,
        explanation=explanation,
    )


# Instância singleton para uso
base_suggestion_service = None


def get_base_suggestion_service():
    """Retorna a instância do serviço."""
    global base_suggestion_service
    if base_suggestion_service is None:
        base_suggestion_service = BaseSuggestionService()
    return base_suggestion_service


class BaseSuggestionService:
    """Serviço de sugestão base."""

    def generate(
        self,
        history: List[int],
        focus_number: int,
        from_index: int = 0,
        max_numbers: int = 12,
    ) -> BaseSuggestionResult:
        """Gera sugestão base."""
        return generate_base_suggestion(history, focus_number, from_index, max_numbers)

    def generate_extended(
        self,
        history: List[int],
        focus_number: int,
        from_index: int = 0,
        max_numbers: int = 12,
    ) -> Dict[str, any]:
        """Gera sugestão base com lista estendida."""
        result = self.generate(history, focus_number, from_index, max_numbers)
        extended = build_extended_suggestion(result.suggestion) if result.suggestion else []

        return {
            "base": result,
            "extended": extended,
        }
