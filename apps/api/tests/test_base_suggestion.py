"""
Testes para verificar que a lógica do backend replica exatamente o frontend.

Execute com: python -m pytest api/tests/test_base_suggestion.py -v
"""
import pytest
from api.services.base_suggestion import (
    analyze_pulled_numbers,
    build_bucket,
    find_dominant,
    build_base_suggestion,
    get_dozen,
    get_column,
    get_highlow,
    get_parity,
    get_color,
    generate_base_suggestion,
)


class TestLabels:
    """Testa se os labels são idênticos ao frontend."""

    def test_dozen_labels(self):
        """Dúzias devem usar 1ª, 2ª, 3ª, Zero"""
        assert get_dozen(0) == "Zero"
        assert get_dozen(1) == "1ª"
        assert get_dozen(12) == "1ª"
        assert get_dozen(13) == "2ª"
        assert get_dozen(24) == "2ª"
        assert get_dozen(25) == "3ª"
        assert get_dozen(36) == "3ª"

    def test_column_labels(self):
        """Colunas devem usar C1, C2, C3, Zero"""
        assert get_column(0) == "Zero"
        # C1: 1, 4, 7, 10, 13, 16, 19, 22, 25, 28, 31, 34
        assert get_column(1) == "C1"
        assert get_column(4) == "C1"
        assert get_column(34) == "C1"
        # C2: 2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32, 35
        assert get_column(2) == "C2"
        assert get_column(5) == "C2"
        assert get_column(35) == "C2"
        # C3: 3, 6, 9, 12, 15, 18, 21, 24, 27, 30, 33, 36
        assert get_column(3) == "C3"
        assert get_column(6) == "C3"
        assert get_column(36) == "C3"

    def test_highlow_labels(self):
        """Alto/Baixo devem usar Baixo, Alto, Zero"""
        assert get_highlow(0) == "Zero"
        assert get_highlow(1) == "Baixo"
        assert get_highlow(18) == "Baixo"
        assert get_highlow(19) == "Alto"
        assert get_highlow(36) == "Alto"

    def test_parity_labels(self):
        """Paridade deve usar Par, Ímpar, Zero"""
        assert get_parity(0) == "Zero"
        assert get_parity(2) == "Par"
        assert get_parity(36) == "Par"
        assert get_parity(1) == "Ímpar"
        assert get_parity(35) == "Ímpar"

    def test_color_labels(self):
        """Cores devem usar red, black, green"""
        assert get_color(0) == "green"
        assert get_color(1) == "red"
        assert get_color(2) == "black"
        assert get_color(3) == "red"
        assert get_color(4) == "black"


class TestPulledNumbers:
    """Testa a lógica de puxadas (pulled numbers)."""

    def test_pulled_numbers_basic(self):
        """
        Testa que pulled numbers pega o número ANTERIOR no array (mais recente em tempo).

        Se history = [A, B, C, D] onde A é mais recente:
        - Se focus=C está em idx=2, pulled deve ser B (idx=1)
        """
        history = [10, 20, 15, 30, 15, 40]
        # 15 aparece em idx=2 e idx=4
        # Pulled de idx=2 é history[1] = 20
        # Pulled de idx=4 é history[3] = 30
        pulled, counts = analyze_pulled_numbers(history, focus_number=15, from_index=0)

        assert 20 in pulled
        assert 30 in pulled
        assert len(pulled) == 2

    def test_pulled_numbers_first_position(self):
        """Se o número está na posição 0, não há puxada."""
        history = [15, 20, 30, 40]
        pulled, counts = analyze_pulled_numbers(history, focus_number=15, from_index=0)

        # 15 está em idx=0, não pode puxar idx=-1
        assert len(pulled) == 0

    def test_pulled_numbers_with_from_index(self):
        """Testa from_index para limitar a busca."""
        history = [10, 15, 20, 15, 30]
        # Com from_index=2, só olha a partir de idx=2
        # 15 aparece em idx=3, pulled seria history[2] = 20
        pulled, counts = analyze_pulled_numbers(history, focus_number=15, from_index=2)

        assert 20 in pulled
        assert len(pulled) == 1


class TestBucket:
    """Testa a construção do bucket de estatísticas."""

    def test_bucket_dozen_counting(self):
        """Testa contagem de dúzias."""
        pulled = [1, 5, 10, 15, 25, 30]
        bucket = build_bucket(pulled)

        assert bucket.dozen["1ª"] == 3  # 1, 5, 10
        assert bucket.dozen["2ª"] == 1  # 15
        assert bucket.dozen["3ª"] == 2  # 25, 30

    def test_bucket_color_counting(self):
        """Testa contagem de cores."""
        pulled = [1, 3, 5, 2, 4, 0]  # 1,3,5 são red, 2,4 são black, 0 é green
        bucket = build_bucket(pulled)

        assert bucket.color["red"] == 3
        assert bucket.color["black"] == 2
        assert bucket.color["green"] == 1


class TestDominant:
    """Testa a detecção de padrões dominantes."""

    def test_find_dominant_basic(self):
        """Testa detecção de dominante com ratio >= 0.6 e count >= 3."""
        counts = {"1ª": 8, "2ª": 1, "3ª": 1}  # Total = 10, 1ª = 80%

        dom = find_dominant(counts, total=10, min_ratio=0.6, min_count=3)

        assert dom is not None
        assert dom.key == "1ª"
        assert dom.ratio == 0.8

    def test_find_dominant_no_match(self):
        """Não encontra dominante se ratio < 0.6."""
        counts = {"1ª": 4, "2ª": 3, "3ª": 3}  # Total = 10, 1ª = 40%

        dom = find_dominant(counts, total=10, min_ratio=0.6, min_count=3)

        assert dom is None

    def test_find_dominant_min_count(self):
        """Não encontra dominante se count < min_count."""
        counts = {"1ª": 2, "2ª": 1, "3ª": 0}  # 1ª = 67% mas count=2 < 3

        dom = find_dominant(counts, total=3, min_ratio=0.6, min_count=3)

        assert dom is None


class TestBuildBaseSuggestion:
    """Testa a construção da sugestão base."""

    def test_suggestion_with_dominant_dozen(self):
        """Quando há dúzia dominante, filtra para essa dúzia."""
        # Simula bucket com 1ª dúzia dominante (80%)
        from api.services.base_suggestion import Bucket

        bucket = Bucket(
            dozen={"1ª": 8, "2ª": 1, "3ª": 1, "Zero": 0},
            column={"C1": 3, "C2": 3, "C3": 4, "Zero": 0},
            highlow={"Baixo": 5, "Alto": 5, "Zero": 0},
            parity={"Par": 5, "Ímpar": 5, "Zero": 0},
            color={"red": 5, "black": 5, "green": 0},
            section={"Jeu Zero": 2, "Voisins": 3, "Orphelins": 2, "Tiers": 3},
            horse={"147": 3, "258": 3, "036": 2, "369": 2},
        )

        pulled_counts = {1: 2, 5: 2, 10: 2, 15: 1, 25: 1}

        result, patterns, explanation = build_base_suggestion(
            bucket=bucket,
            pulled_counts=pulled_counts,
            total_pulled=10,
            history=[1, 5, 10, 15, 25] * 10,
            from_index=0,
            max_numbers=8,
        )

        # Deve ter padrão dominante de dúzia
        assert any(p["category"] == "dozen" and p["key"] == "1ª" for p in patterns)

        # Todos os números devem ser da 1ª dúzia (1-12)
        for n in result:
            assert 1 <= n <= 12, f"Número {n} não está na 1ª dúzia"

    def test_suggestion_sorted_numerically(self):
        """A sugestão final deve estar ordenada numericamente."""
        result = generate_base_suggestion(
            history=list(range(1, 100)),
            focus_number=5,
            from_index=0,
            max_numbers=8,
        )

        if result.available and len(result.suggestion) > 1:
            assert result.suggestion == sorted(result.suggestion)


class TestIntegration:
    """Testes de integração com dados reais."""

    def test_full_flow(self):
        """Testa o fluxo completo de geração de sugestão."""
        # Histórico simulado onde o número 15 aparece várias vezes
        # e é frequentemente precedido por números da 2ª dúzia
        history = []
        for i in range(50):
            history.extend([15, 20])  # 15 sempre puxado por 20

        result = generate_base_suggestion(
            history=history,
            focus_number=15,
            from_index=0,
            max_numbers=8,
        )

        assert result.available
        assert len(result.suggestion) > 0
        assert 20 in result.pulled_numbers  # 20 deve estar nos puxados

    def test_insufficient_history(self):
        """Com histórico insuficiente, não gera sugestão."""
        result = generate_base_suggestion(
            history=[1, 2, 3],
            focus_number=1,
            from_index=0,
            max_numbers=8,
        )

        assert not result.available


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
