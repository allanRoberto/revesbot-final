from __future__ import annotations

import pytest

from api.services.jev_evaluation import JevEvaluationError, evaluate_saved_ranking


def _record() -> dict:
    ranking = [
        {
            "numero": number,
            "posicao": number + 1,
            "estimativa_jev_nao_validada": 0.20 if number == 0 else 0.08,
        }
        for number in range(37)
    ]
    immediate = [
        {
            "numero": number,
            "posicao": number + 1,
            "probabilidade": 0.10 if number == 0 else 0.90 / 36,
        }
        for number in range(37)
    ]
    return {
        "analysis_type": "number_ranking",
        "ranking": ranking,
        "ranking_proxima_rodada": immediate,
        "proxima_rodada": {"numero_escolhido": 0},
    }


def test_evaluation_calculates_proper_scores_top_hits_and_immediate_hit() -> None:
    result = evaluate_saved_ranking(_record(), [0, 3, 10])
    metrics = result["metricas_tres_rodadas"]
    assert metrics["brier_medio_37_numeros"] > 0
    assert metrics["log_loss_binario_medio_37_numeros"] > 0
    assert metrics["acertos_por_corte"] == {
        "top_1": True,
        "top_3": True,
        "top_5": True,
        "top_10": True,
    }
    assert result["metrica_proxima_rodada"]["acertou_escolha"] is True
    assert result["metrica_proxima_rodada"]["posicao_do_numero_real"] == 1


def test_evaluation_rejects_incomplete_record_or_wrong_result_count() -> None:
    record = _record()
    record["ranking"].pop()
    with pytest.raises(JevEvaluationError):
        evaluate_saved_ranking(record, [0, 1, 2])
    with pytest.raises(JevEvaluationError):
        evaluate_saved_ranking(_record(), [0, 1])


def test_evaluation_compares_meta_ranking_without_another_inference() -> None:
    record = _record()
    record["ranking_meta"] = [
        {
            "numero": number,
            "posicao": number + 1,
            "probabilidade_meta": 0.18 if number == 0 else 0.075,
        }
        for number in range(37)
    ]
    record["ranking_meta_proxima_rodada"] = [
        {
            "numero": number,
            "posicao": number + 1,
            "probabilidade_meta": 0.15 if number == 0 else 0.85 / 36,
        }
        for number in range(37)
    ]
    record["sinal_meta"] = {"available": True}

    result = evaluate_saved_ranking(record, [0, 3, 10])

    assert "metricas_meta_tres_rodadas" in result
    assert result["metrica_meta_proxima_rodada"]["acertou_escolha"] is True
    assert result["comparacao_meta_vs_jev"]["positivo_significa_meta_melhor"] is True
    assert result["comparacao_meta_vs_jev"]["sinal_meta_disponivel_na_previsao"] is True
