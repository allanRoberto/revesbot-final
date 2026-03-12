#!/usr/bin/env python3
"""
simulate.py - Simulador de Roleta com Cache Persistente
--------------------------------------------------------
Permite salvar e reutilizar históricos de roleta, com controle total via CLI.

Uso:
    # Buscar novos dados e salvar (opcional --save-as)
    python3 simulate.py roulette1 500 --save-as teste1
    
    # Usar dados salvos anteriormente
    python3 simulate.py roulette1 500 --load teste1
    
    # Forçar nova busca mesmo se existir cache
    python3 simulate.py roulette1 500 --force-fetch
    
    # Listar arquivos salvos
    python3 simulate.py --list-saved
"""

import asyncio
import json
import logging
import os
import signal
import argparse
from pathlib import Path
from typing import List, Optional
from datetime import datetime

import redis.asyncio as redis
from dotenv import load_dotenv

from core.api import RouletteAPI
from helpers.roulettes_list import roulettes

# ─── Configuração ─────────────────────────────────────────────────────────────
load_dotenv()

REDIS_URL = os.getenv("REDIS_CONNECT")
SIM_CHANNEL = os.getenv("SIM_CHANNEL", "new_result_simulate")
SIM_DELAY = float(os.getenv("SIM_DELAY", "0"))
PROGRESS_STEP = int(os.getenv("PROGRESS_STEP", "10"))

# Diretório para salvar os históricos
CACHE_DIR = Path("roulette_cache")
CACHE_DIR.mkdir(exist_ok=True)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Ignorar SIGPIPE se existir
if hasattr(signal, 'SIGPIPE'):
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)

# ─── Classes de Dados ─────────────────────────────────────────────────────────
class RouletteCache:
    """Gerencia o cache de históricos de roleta."""
    
    def __init__(self, cache_dir: Path = CACHE_DIR):
        self.cache_dir = cache_dir
    
    def get_filename(self, slug: str, name: Optional[str] = None) -> Path:
        """Gera o nome do arquivo de cache."""
        if name:
            return self.cache_dir / f"{slug}_{name}.json"
        return self.cache_dir / f"{slug}_default.json"
    
    def save(self, slug: str, history: List[int], name: Optional[str] = None) -> Path:
        """Salva o histórico em arquivo."""
        filepath = self.get_filename(slug, name)
        data = {
            "slug": slug,
            "timestamp": datetime.now().isoformat(),
            "count": len(history),
            "history": history,
            "name": name or "default"
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        logger.info(f"✅ Histórico salvo: {filepath.name} ({len(history)} resultados)")
        return filepath
    
    def load(self, slug: str, name: Optional[str] = None) -> Optional[List[int]]:
        """Carrega o histórico do arquivo."""
        filepath = self.get_filename(slug, name)
        
        if not filepath.exists():
            return None
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            logger.info(f"📂 Histórico carregado: {filepath.name}")
            logger.info(f"   Salvo em: {data['timestamp']}")
            logger.info(f"   Total: {data['count']} resultados")
            
            return data["history"]
        except Exception as e:
            logger.error(f"Erro ao carregar {filepath}: {e}")
            return None
    
    def exists(self, slug: str, name: Optional[str] = None) -> bool:
        """Verifica se existe cache para a roleta."""
        return self.get_filename(slug, name).exists()
    
    def list_saved(self) -> List[dict]:
        """Lista todos os arquivos salvos."""
        saved = []
        for filepath in self.cache_dir.glob("*.json"):
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                saved.append({
                    "file": filepath.name,
                    "slug": data.get("slug"),
                    "name": data.get("name"),
                    "count": data.get("count"),
                    "date": data.get("timestamp", "").split("T")[0]
                })
            except:
                pass
        return saved

# ─── Simulador ────────────────────────────────────────────────────────────────
class RouletteSimulator:
    """Simulador principal de roleta."""
    
    def __init__(self):
        self.redis = redis.from_url(REDIS_URL, decode_responses=True)
        self.api = RouletteAPI()
        self.cache = RouletteCache()
    
    async def fetch_history(self, slug: str, num_results: int, full_results : bool = False) -> List[int]:
        """Busca o histórico via API com retry automático."""
        max_retries = 5
        delay = 1  # tempo inicial em segundos

        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"🔍 Tentativa {attempt}/{max_retries} - Buscando {num_results} resultados para {slug}...")
                resp = await self.api.api(slug, num_results=num_results, full_results=full_results)

                history = []

                if resp and "results" in resp:
                # Extrair apenas os números
                    history = [r["value"] if isinstance(r, dict) else r for r in resp["results"]]

                logger.info(f"✅ {len(history)} resultados obtidos")
                return history, resp["results"]
            except Exception as exc:
                logger.error(f"❌ Erro ao buscar histórico de {slug} (tentativa {attempt}): {exc}")
                if attempt < max_retries:
                    logger.warning(f"⏳ Re-tentando em {delay}s...")
                    await asyncio.sleep(delay)
                    delay *= 2  # backoff exponencial
                else:
                    logger.critical(f"🚨 Todas as {max_retries} tentativas falharam para {slug}")
                    return []
    
    async def publish_results(self, slug: str, history: List[int], full: Optional[List[dict]] = None) -> None:
        """Publica os resultados no Redis."""
        total = len(history)
        if not total:
            logger.warning(f"[{slug}] Sem histórico para simular")
            return

        if full is None:
            full = []
        
        logger.info(f"\n🎰 Iniciando simulação de {slug}")
        logger.info(f"   Total: {total} resultados")
        logger.info(f"   Delay: {SIM_DELAY}s entre publicações")
        logger.info("─" * 50)
        
        next_pct = PROGRESS_STEP
        
        for idx, result in enumerate(reversed(history)):
            # Publicar no Redis
            if SIM_DELAY > 0:
                await asyncio.sleep(SIM_DELAY)
            else:
                await asyncio.sleep(0.005)

            print(result)

            full_result = None
            if full:
                full_index = len(full) - 1 - idx
                if full_index >= 0:
                    full_result = full[full_index]

            await self.redis.publish(
                SIM_CHANNEL, 
                json.dumps({"slug": slug, "result": result, "full_result": full_result})
            )
            
            # Mostrar progresso
            pct = ((idx + 1) * 100) / total
            if pct >= next_pct or idx == total:
                bar_length = 30
                filled = int(bar_length * idx / total)
                bar = "█" * filled + "░" * (bar_length - filled)
                logger.info(f"[{bar}] {pct:5.1f}% ({idx + 1}/{total})")
                next_pct += PROGRESS_STEP
            
               
        
        logger.info(f"✅ Simulação de {slug} concluída!\n")
    
    async def simulate(
        self, 
        slug: str, 
        num_results: int,
        full_results: bool,
        save_as: Optional[str] = None,
        load_from: Optional[str] = None,
        force_fetch: bool = False
    ):
        """Executa a simulação com opções de cache."""
        
        history = None
        
        # Tentar carregar do cache se especificado
        if load_from and not force_fetch:
            history = self.cache.load(slug, load_from)
            if not history:
                logger.warning(f"⚠️  Cache '{load_from}' não encontrado para {slug}")
        
        # Se não tem histórico ainda, buscar
        if history is None:
            # Verificar cache padrão se não forçar busca
            if not force_fetch and not save_as:
                history = self.cache.load(slug, None)
            
            # Se ainda não tem, buscar da API
            if history is None or force_fetch:
                history, full_history = await self.fetch_history(slug, num_results, full_results)
                
                # Salvar se solicitado
                if history and save_as:
                    self.cache.save(slug, history, save_as)
                elif history and not self.cache.exists(slug):
                    # Salvar cache padrão se não existe
                    self.cache.save(slug, history, None)
        
        # Ajustar quantidade se necessário
        if history and len(history) > num_results:
            logger.info(f"📊 Usando apenas {num_results} dos {len(history)} resultados disponíveis")
            history = history[:num_results]
        # Publicar resultados
        if history:
            await self.publish_results(slug, history, full_history)
        else:
            logger.error(f"❌ Nenhum histórico disponível para {slug}")
    
    async def close(self):
        """Fecha conexões."""
        await self.redis.aclose()

# ─── CLI ──────────────────────────────────────────────────────────────────────
def parse_arguments():
    """Parse argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description="Simulador de Roleta com Cache Persistente",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  %(prog)s roulette1 500                    # Simula 500 resultados (usa cache se existir)
  %(prog)s roulette1 500 --save-as teste1   # Busca novos e salva como 'teste1'
  %(prog)s roulette1 500 --load teste1      # Usa dados salvos como 'teste1'
  %(prog)s roulette1 500 --force-fetch      # Força nova busca ignorando cache
  %(prog)s --list-saved                     # Lista todos os arquivos salvos
        """
    )
    
    # Argumentos principais
    parser.add_argument(
        "slug",
        nargs="?",
        help="Slug da roleta (ex: roulette1)"
    )
    
    parser.add_argument(
        "num_results",
        nargs="?",
        type=int,
        default=500,
        help="Quantidade de resultados (padrão: 500)"
    )

    parser.add_argument(
        "full_results",
        nargs="?",
        type=bool,
        default=False,
        help="Resultados completos com horário (padrão: False)"
    )
    
    # Opções de cache
    cache_group = parser.add_mutually_exclusive_group()
    cache_group.add_argument(
        "--save-as",
        metavar="NOME",
        help="Busca novos dados e salva com este nome"
    )
    
    cache_group.add_argument(
        "--load",
        metavar="NOME",
        help="Carrega dados previamente salvos com este nome"
    )
    
    parser.add_argument(
        "--force-fetch",
        action="store_true",
        help="Força busca na API mesmo se existir cache"
    )
    
    # Comandos auxiliares
    parser.add_argument(
        "--list-saved",
        action="store_true",
        help="Lista todos os arquivos de cache salvos"
    )
    
    parser.add_argument(
        "--list-roulettes",
        action="store_true",
        help="Lista todas as roletas disponíveis"
    )
    
    # Opções adicionais
    parser.add_argument(
        "--delay",
        type=float,
        metavar="SEGUNDOS",
        help=f"Delay entre publicações (padrão: {SIM_DELAY}s)"
    )
    
    return parser.parse_args()

def list_saved_files():
    """Lista todos os arquivos salvos."""
    cache = RouletteCache()
    saved = cache.list_saved()
    
    if not saved:
        print("📂 Nenhum arquivo de cache encontrado")
        return
    
    print("\n📂 Arquivos de cache salvos:")
    print("─" * 60)
    print(f"{'Arquivo':<30} {'Roleta':<15} {'Resultados':<10} {'Data'}")
    print("─" * 60)
    
    for item in sorted(saved, key=lambda x: x['file']):
        print(f"{item['file']:<30} {item['slug']:<15} {item['count']:<10} {item['date']}")
    
    print("─" * 60)
    print(f"Total: {len(saved)} arquivos\n")

def list_available_roulettes():
    """Lista todas as roletas disponíveis."""
    print("\n🎰 Roletas disponíveis:")
    print("─" * 40)
    
    for r in roulettes:
        print(f"  • {r['slug']:<20} - {r.get('name', 'N/A')}")
    
    print("─" * 40)
    print(f"Total: {len(roulettes)} roletas\n")

async def main():
    """Função principal."""
    args = parse_arguments()
    
    # Comandos auxiliares
    if args.list_saved:
        list_saved_files()
        return
    
    if args.list_roulettes:
        list_available_roulettes()
        return
    
    # Validar argumentos para simulação
    if not args.slug:
        print("❌ Erro: É necessário especificar o slug da roleta")
        print("Use --help para mais informações ou --list-roulettes para ver as disponíveis")
        return
    
    # Verificar se a roleta existe
    valid_slugs = [r["slug"] for r in roulettes]
    if args.slug not in valid_slugs:
        print(f"❌ Erro: Roleta '{args.slug}' não encontrada")
        print(f"Roletas válidas: {', '.join(valid_slugs[:5])}...")
        print("Use --list-roulettes para ver todas")
        return
    
    # Ajustar delay se especificado
    if args.delay is not None:
        global SIM_DELAY
        SIM_DELAY = args.delay
    
    # Executar simulação
    simulator = RouletteSimulator()
    

    print(f"Iniciando a simulação da Roleta{args.slug} com {args.num_results} Resultados completos : {args.full_results}")

    try:
        await simulator.simulate(
            slug=args.slug,
            num_results=args.num_results,
            full_results=args.full_results,
            save_as=args.save_as,
            load_from=args.load,
            force_fetch=args.force_fetch
        )
    finally:
        await simulator.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Simulação interrompida pelo usuário")
    except Exception as e:
        logger.error(f"❌ Erro fatal: {e}")
        raise
