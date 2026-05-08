"""
Verifica se o servidor está rodando a nova configuração (penalty 0.75).

Uso no servidor:
  python3 _verify_server_fix.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
import certifi
from pymongo import MongoClient

def _read_dotenv() -> str | None:
    env_path = Path(".env")
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith("MONGO_URL="):
            return line.split("=", 1)[1].strip()
    return None

def check_code_version():
    """Verifica se o código foi atualizado"""
    print("1️⃣  Verificando código local...\n")

    final_suggestion_file = Path("apps/api/patterns/final_suggestion.py")
    if not final_suggestion_file.exists():
        print(f"❌ Arquivo não encontrado: {final_suggestion_file}")
        return False

    content = final_suggestion_file.read_text()

    # Procura pela nova penalidade (0.75)
    if "mild_inversion_factor = 0.75" in content:
        print("✅ Código CORRIGIDO encontrado (penalty 0.75)")

        # Confirma que a linha está no lugar certo
        if "FIX: Apply mild penalty" in content:
            print("✅ Comentário de FIX presente")
            return True
    else:
        print("❌ Código ainda tem a versão antiga (penalty 0.3)")
        return False

def check_new_snapshots():
    """Verifica se novos snapshots estão sendo gerados"""
    print("\n2️⃣  Verificando novos snapshots...\n")

    url = _read_dotenv()
    if not url:
        print("❌ MONGO_URL não encontrado no .env")
        return False

    try:
        client = MongoClient(url, tls=True, tlsCAFile=certifi.where())
        db = client["roleta_db"]
        snaps = db["suggestion_snapshots"]

        # Pega snapshots dos últimos 2 minutos
        two_min_ago = datetime.now(timezone.utc) - timedelta(minutes=2)
        recent = snaps.count_documents({
            "roulette_id": "pragmatic-auto-roulette",
            "created_at_utc": {"$gte": two_min_ago}
        })

        if recent > 0:
            print(f"✅ Snapshots sendo gerados (últimos 2 min: {recent})")
        else:
            print("⚠️  Nenhum snapshot gerado nos últimos 2 minutos")
            print("   (sistema pode estar inativo ou snapshots demorando)")

        # Pega os últimos 3 snapshots para inspecionar
        print("\n   Últimos 3 snapshots:")
        cursor = snaps.find({"roulette_id": "pragmatic-auto-roulette"}).sort("created_at_utc", -1).limit(3)
        for i, doc in enumerate(cursor, 1):
            ts = doc.get("created_at_utc")
            snap_id = doc.get("snapshot_id", "")[:20]
            payload = doc.get("payload", {})
            inv_nums = len(payload.get("invertedNumbers", []))
            inv_final = len(payload.get("invertedInFinal", []))

            print(f"   {i}. {snap_id}... @ {ts}")
            print(f"      invertedNumbers: {inv_nums}, invertedInFinal: {inv_final}")

        return True

    except Exception as e:
        print(f"❌ Erro ao conectar ao MongoDB: {e}")
        return False

def estimate_penalty_change():
    """Estima se há sinal da mudança no comportamento dos snapshots"""
    print("\n3️⃣  Analisando comportamento (pode levar ~1-2 min)...\n")

    url = _read_dotenv()
    if not url:
        return False

    try:
        client = MongoClient(url, tls=True, tlsCAFile=certifi.where())
        db = client["roleta_db"]

        # Pega últimos 100 snapshots
        snaps = list(db["suggestion_snapshots"].find(
            {"roulette_id": "pragmatic-auto-roulette"}
        ).sort("created_at_utc", -1).limit(100))

        if not snaps:
            print("❌ Sem snapshots para analisar")
            return False

        # Analisa invertedInFinal
        inv_in_final_counts = []
        for snap in snaps:
            payload = snap.get("payload", {})
            inv_final = payload.get("invertedInFinal", [])
            inv_in_final_counts.append(len(inv_final))

        avg_inv_final = sum(inv_in_final_counts) / len(inv_in_final_counts)

        print(f"✅ Analisados {len(snaps)} snapshots recentes")
        print(f"   Média de números em invertedInFinal: {avg_inv_final:.2f}")

        # Se a mudança tiver efeito, espera-se que haja MENOS números em invertedInFinal
        # porque agora não estão sendo penalizados tão severamente
        if avg_inv_final < 5:
            print(f"   ⚠️  Valor baixo - pode estar funcionando com a nova lógica")

        # Pega timestamps para verificar recência
        recent_snap = snaps[0]
        ts = recent_snap.get("created_at_utc")
        age_seconds = (datetime.now(timezone.utc) - ts).total_seconds()

        if age_seconds < 120:
            print(f"\n✅ Sistema ATIVO (último snapshot há {int(age_seconds)}s)")
        else:
            print(f"\n⚠️  Sistema pode estar PARADO (último snapshot há {int(age_seconds)}s)")

        return True

    except Exception as e:
        print(f"❌ Erro na análise: {e}")
        return False

def main():
    print("="*70)
    print("VERIFICAÇÃO: Servidor rodando a nova configuração (penalty 0.75)?")
    print("="*70 + "\n")

    code_ok = check_code_version()
    db_ok = check_new_snapshots()
    behavior_ok = estimate_penalty_change()

    print("\n" + "="*70)
    print("RESUMO:")
    print("="*70)

    if code_ok:
        print("✅ Código: ATUALIZADO")
    else:
        print("❌ Código: DESATUALIZADO (deploy necessário)")

    if db_ok:
        print("✅ Banco: ACESSÍVEL")
    else:
        print("❌ Banco: ERRO DE CONEXÃO")

    print("\nPROXIMOS PASSOS:")
    if not code_ok:
        print("1. Deploy da nova versão do código para o servidor")
        print("2. Reiniciar o serviço (pm2 restart all ou similar)")
        print("3. Aguardar ~5-10 min para novos snapshots serem gerados")
        print("4. Rodar este script novamente para confirmar")
    else:
        print("✅ Servidor está pronto! Aguarde 1-2 dias de dados novos")
        print("   e então rode a validação para medir o impacto real.")

if __name__ == "__main__":
    main()
