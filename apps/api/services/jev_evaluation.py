"""Deterministic out-of-sample metrics for one saved Jev number ranking."""
from __future__ import annotations

import math
from typing import Any, Sequence

from api.services.jev_ranking import ROULETTE_NUMBERS


class JevEvaluationError(ValueError):
    pass


def _validate_ranking(
    value: Any, *, probability_key: str, position_key: str
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(ROULETTE_NUMBERS):
        raise JevEvaluationError("O ranking salvo está incompleto.")
    seen: set[int] = set()
    validated: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise JevEvaluationError("O ranking salvo contém um item inválido.")
        number = item.get("numero")
        probability = item.get(probability_key)
        position = item.get(position_key)
        if (
            isinstance(number, bool)
            or not isinstance(number, int)
            or number not in ROULETTE_NUMBERS
            or number in seen
            or isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not math.isfinite(float(probability))
            or not 0 <= float(probability) <= 1
            or isinstance(position, bool)
            or not isinstance(position, int)
            or not 1 <= position <= len(ROULETTE_NUMBERS)
        ):
            raise JevEvaluationError("O ranking salvo contém valores inválidos.")
        seen.add(number)
        validated.append(item)
    if seen != set(ROULETTE_NUMBERS) or {item[position_key] for item in validated} != set(
        range(1, len(ROULETTE_NUMBERS) + 1)
    ):
        raise JevEvaluationError("O ranking salvo não cobre os números 0 a 36.")
    return validated


def _three_spin_metrics(
    ranking: Sequence[dict[str, Any]],
    actual_results: Sequence[int],
    *,
    probability_key: str,
) -> dict[str, Any]:
    by_number = {item["numero"]: item for item in ranking}
    observed = set(actual_results)
    epsilon = 1e-15
    brier_terms: list[float] = []
    log_loss_terms: list[float] = []
    for number in ROULETTE_NUMBERS:
        probability = float(by_number[number][probability_key])
        outcome = 1.0 if number in observed else 0.0
        brier_terms.append((probability - outcome) ** 2)
        clipped = min(1 - epsilon, max(epsilon, probability))
        log_loss_terms.append(
            -(outcome * math.log(clipped) + (1 - outcome) * math.log(1 - clipped))
        )

    ordered = sorted(ranking, key=lambda item: item["posicao"])
    return {
        "brier_medio_37_numeros": sum(brier_terms) / len(brier_terms),
        "log_loss_binario_medio_37_numeros": sum(log_loss_terms) / len(log_loss_terms),
        "acertos_por_corte": {
            f"top_{size}": any(item["numero"] in observed for item in ordered[:size])
            for size in (1, 3, 5, 10)
        },
        "posicoes_dos_resultados_reais": [
            {
                "rodada": index,
                "numero": number,
                "posicao": by_number[number]["posicao"],
                "probabilidade": by_number[number][probability_key],
            }
            for index, number in enumerate(actual_results, start=1)
        ],
    }


def _immediate_metric(
    ranking: Sequence[dict[str, Any]],
    first_actual: int,
    *,
    probability_key: str,
    selected: int,
) -> dict[str, Any]:
    by_number = {item["numero"]: item for item in ranking}
    actual = by_number[first_actual]
    return {
        "numero_escolhido": selected,
        "numero_real": first_actual,
        "acertou_escolha": selected == first_actual,
        "posicao_do_numero_real": actual["posicao"],
        "probabilidade_do_numero_real": actual[probability_key],
    }


def evaluate_saved_ranking(record: dict[str, Any], actual_results: Sequence[int]) -> dict[str, Any]:
    if record.get("analysis_type") != "number_ranking":
        raise JevEvaluationError("O registro informado não é um ranking de números.")
    if len(actual_results) != 3 or any(number not in ROULETTE_NUMBERS for number in actual_results):
        raise JevEvaluationError("Informe exatamente os três resultados reais seguintes, de 0 a 36.")

    ranking = _validate_ranking(
        record.get("ranking"),
        probability_key="estimativa_jev_nao_validada",
        position_key="posicao",
    )
    immediate_ranking = _validate_ranking(
        record.get("ranking_proxima_rodada"),
        probability_key="probabilidade",
        position_key="posicao",
    )
    if not math.isclose(
        sum(float(item["probabilidade"]) for item in immediate_ranking),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-6,
    ):
        raise JevEvaluationError("A distribuição do ranking imediato é inválida.")
    selected = record.get("proxima_rodada", {}).get("numero_escolhido")
    if isinstance(selected, bool) or not isinstance(selected, int) or selected not in ROULETTE_NUMBERS:
        raise JevEvaluationError("A escolha salva para a próxima rodada é inválida.")
    first_actual = actual_results[0]
    original_metrics = _three_spin_metrics(
        ranking,
        actual_results,
        probability_key="estimativa_jev_nao_validada",
    )
    result = {
        "resultados_reais": list(actual_results),
        "metricas_tres_rodadas": original_metrics,
        "metrica_proxima_rodada": _immediate_metric(
            immediate_ranking,
            first_actual,
            probability_key="probabilidade",
            selected=selected,
        ),
    }

    if record.get("ranking_meta") is not None or record.get("ranking_meta_proxima_rodada") is not None:
        meta_ranking = _validate_ranking(
            record.get("ranking_meta"),
            probability_key="probabilidade_meta",
            position_key="posicao",
        )
        meta_immediate = _validate_ranking(
            record.get("ranking_meta_proxima_rodada"),
            probability_key="probabilidade_meta",
            position_key="posicao",
        )
        if not math.isclose(
            sum(float(item["probabilidade_meta"]) for item in meta_immediate),
            1.0,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise JevEvaluationError("A distribuição do meta-ranking imediato é inválida.")
        meta_metrics = _three_spin_metrics(
            meta_ranking,
            actual_results,
            probability_key="probabilidade_meta",
        )
        meta_selected = min(meta_immediate, key=lambda item: item["posicao"])["numero"]
        result["metricas_meta_tres_rodadas"] = meta_metrics
        result["metrica_meta_proxima_rodada"] = _immediate_metric(
            meta_immediate,
            first_actual,
            probability_key="probabilidade_meta",
            selected=meta_selected,
        )
        result["comparacao_meta_vs_jev"] = {
            "ganho_brier": (
                original_metrics["brier_medio_37_numeros"]
                - meta_metrics["brier_medio_37_numeros"]
            ),
            "ganho_log_loss": (
                original_metrics["log_loss_binario_medio_37_numeros"]
                - meta_metrics["log_loss_binario_medio_37_numeros"]
            ),
            "positivo_significa_meta_melhor": True,
            "sinal_meta_disponivel_na_previsao": bool(
                record.get("sinal_meta", {}).get("available", False)
            ),
        }
    return result
