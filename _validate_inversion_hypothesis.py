"""
Valida a hipótese da "inversão sub-aplicada" em todos os 18.710 snapshots.

Cruza posição de acerto vs se o número estava em invertedNumbers.
Mede recência: em quantas jogadas atrás o próximo número foi sorteado?
"""
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import certifi
from pymongo import MongoClient, DESCENDING, ASCENDING

ROULETTE_ID = "pragmatic-auto-roulette"


def _read_dotenv() -> str | None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("MONGO_URL="):
            return line.split("=", 1)[1].strip()
    return None


def main():
    url = _read_dotenv()
    client = MongoClient(url, tls=True, tlsCAFile=certifi.where())
    db = client["roleta_db"]
    snaps_coll = db["suggestion_snapshots"]
    hist_coll = db["history"]

    # Carrega todo o histórico ordenado
    print("Carregando histórico...")
    hist_docs = list(
        hist_coll.find({"roulette_id": ROULETTE_ID})
        .sort("timestamp", ASCENDING)
    )
    print(f"Total de draws: {len(hist_docs)}")

    # Mapeia cada draw ao índice cronológico
    draw_map = {h.get("_id"): i for i, h in enumerate(hist_docs)}
    hist_by_ts = {h.get("timestamp"): h for h in hist_docs}

    print(f"\nProcessando snapshots ({snaps_coll.count_documents({'roulette_id': ROULETTE_ID})} totais)...")

    results = []
    cursor = (
        snaps_coll.find({"roulette_id": ROULETTE_ID})
        .sort("anchor_timestamp_utc", ASCENDING)
    )

    for i, snap in enumerate(cursor):
        if (i + 1) % 2000 == 0:
            print(f"  {i+1} processados...")

        anchor_ts = snap.get("anchor_timestamp_utc")
        anchor_num = snap.get("anchor_number")
        payload = snap.get("payload") or {}

        # Encontra próximo draw após anchor_ts
        next_doc = None
        for h in hist_docs:
            if h.get("timestamp") and anchor_ts and h.get("timestamp") > anchor_ts:
                next_doc = h
                break

        if not next_doc:
            continue

        next_num = next_doc.get("value")
        next_ts = next_doc.get("timestamp")

        # Posição no ranking
        ranking = payload.get("suggestion") or payload.get("list") or []
        try:
            pos = ranking.index(int(next_num)) + 1
        except (ValueError, TypeError):
            continue

        # Dados de inversão
        inv_numbers = set(payload.get("invertedNumbers") or [])
        inv_in_final = set(payload.get("invertedInFinal") or [])
        inv_removed = set(payload.get("invertedRemoved") or [])
        pulled_numbers = set(payload.get("pulledNumbers") or [])
        pulled_in_final = set(payload.get("pulledInFinal") or [])

        # Recência: em quantas jogadas atrás foi sorteado?
        anchor_idx = draw_map.get(snap.get("anchor_history_id"))
        next_idx = draw_map.get(next_doc.get("_id"))
        recency = next_idx - anchor_idx if anchor_idx is not None and next_idx is not None else None

        # Confiança
        confidence = payload.get("confidence") or {}
        conf_score = confidence.get("score")
        conf_label = confidence.get("label")

        results.append({
            "snapshot_id": snap.get("snapshot_id"),
            "anchor": anchor_num,
            "next": next_num,
            "pos": pos,
            "recency": recency,
            "in_inverted_numbers": int(next_num) in inv_numbers,
            "in_inverted_in_final": int(next_num) in inv_in_final,
            "in_inverted_removed": int(next_num) in inv_removed,
            "in_pulled_numbers": int(next_num) in pulled_numbers,
            "in_pulled_in_final": int(next_num) in pulled_in_final,
            "confidence_score": conf_score,
            "confidence_label": conf_label,
            "config_key": snap.get("config_key"),
        })

    print(f"\n✓ {len(results)} snapshots processados com sucesso\n")

    # Estatísticas
    if not results:
        print("Sem dados!")
        return

    positions = [r["pos"] for r in results]
    print(f"Posições gerais: n={len(positions)}, min={min(positions)}, max={max(positions)}, "
          f"média={sum(positions)/len(positions):.2f}, mediana={sorted(positions)[len(positions)//2]}")

    # Segmenta por invertedNumbers
    in_inv = [r["pos"] for r in results if r["in_inverted_numbers"]]
    not_in_inv = [r["pos"] for r in results if not r["in_inverted_numbers"]]

    print(f"\n📊 HIPÓTESE PRINCIPAL (invertedNumbers):")
    print(f"  next ∈ invertedNumbers (n={len(in_inv)}): "
          f"média={sum(in_inv)/len(in_inv):.2f}, mediana={sorted(in_inv)[len(in_inv)//2] if in_inv else '-'}")
    print(f"  next ∉ invertedNumbers (n={len(not_in_inv)}): "
          f"média={sum(not_in_inv)/len(not_in_inv):.2f}, mediana={sorted(not_in_inv)[len(not_in_inv)//2] if not_in_inv else '-'}")
    if in_inv and not_in_inv:
        gap = sum(not_in_inv)/len(not_in_inv) - sum(in_inv)/len(in_inv)
        print(f"  → GAP: {gap:.2f} (números em invertedNumbers acertam {gap:.1f} posições melhor)")

    # Recência
    recent_0_5 = [r["pos"] for r in results if r["recency"] is not None and 0 <= r["recency"] <= 5]
    recent_6_15 = [r["pos"] for r in results if r["recency"] is not None and 6 <= r["recency"] <= 15]
    recent_16p = [r["pos"] for r in results if r["recency"] is not None and r["recency"] >= 16]

    print(f"\n📈 RECÊNCIA (quantas jogadas atrás foi sorteado?):")
    if recent_0_5:
        print(f"  0-5 spins atrás (n={len(recent_0_5)}): média={sum(recent_0_5)/len(recent_0_5):.2f}")
    if recent_6_15:
        print(f"  6-15 spins atrás (n={len(recent_6_15)}): média={sum(recent_6_15)/len(recent_6_15):.2f}")
    if recent_16p:
        print(f"  16+ spins atrás (n={len(recent_16p)}): média={sum(recent_16p)/len(recent_16p):.2f}")

    # Confiança
    alta = [r["pos"] for r in results if r["confidence_label"] == "Alta"]
    media = [r["pos"] for r in results if r["confidence_label"] == "Média"]
    baixa = [r["pos"] for r in results if r["confidence_label"] == "Baixa"]

    print(f"\n⭐ CONFIANÇA:")
    if alta:
        print(f"  Alta (n={len(alta)}): média={sum(alta)/len(alta):.2f}")
    if media:
        print(f"  Média (n={len(media)}): média={sum(media)/len(media):.2f}")
    if baixa:
        print(f"  Baixa (n={len(baixa)}): média={sum(baixa)/len(baixa):.2f}")

    # Salva CSV completo
    out_csv = Path(__file__).resolve().parent / "_validation_results.csv"
    header = ",".join(results[0].keys())
    rows = [header]
    for r in results:
        rows.append(",".join(str(v) for v in r.values()))
    out_csv.write_text("\n".join(rows))
    print(f"\n✓ Detalhe salvo em {out_csv}")

    # Salva JSON de resumo
    summary = {
        "total_snapshots": len(results),
        "positions": {
            "all": {"count": len(positions), "mean": sum(positions)/len(positions), "min": min(positions), "max": max(positions)},
            "in_inverted_numbers": {"count": len(in_inv), "mean": sum(in_inv)/len(in_inv) if in_inv else None},
            "not_in_inverted_numbers": {"count": len(not_in_inv), "mean": sum(not_in_inv)/len(not_in_inv) if not_in_inv else None},
        },
        "recency": {
            "0_5_spins": {"count": len(recent_0_5), "mean": sum(recent_0_5)/len(recent_0_5) if recent_0_5 else None},
            "6_15_spins": {"count": len(recent_6_15), "mean": sum(recent_6_15)/len(recent_6_15) if recent_6_15 else None},
            "16plus_spins": {"count": len(recent_16p), "mean": sum(recent_16p)/len(recent_16p) if recent_16p else None},
        },
        "confidence": {
            "Alta": {"count": len(alta), "mean": sum(alta)/len(alta) if alta else None},
            "Média": {"count": len(media), "mean": sum(media)/len(media) if media else None},
            "Baixa": {"count": len(baixa), "mean": sum(baixa)/len(baixa) if baixa else None},
        },
    }
    out_json = Path(__file__).resolve().parent / "_validation_summary.json"
    out_json.write_text(json.dumps(summary, indent=2))
    print(f"✓ Resumo salvo em {out_json}\n")


if __name__ == "__main__":
    main()
