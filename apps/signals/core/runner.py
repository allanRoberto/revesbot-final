# core/runner.py
import asyncio, logging
from core.api      import RouletteAPI
from core.detector import TriggerDetector

from pathlib import Path


from helpers.utils.telegram import (
    send_telegram_message
)

BOOT_MAX_TRIES = 5          # quantas tentativas para obter histórico
BOOT_DELAY     = 3          # segundos entre tentativas


def load_casa_apostas_urls() -> dict[str, str]:
    """
    Lê o arquivo links.txt na raiz do projeto, no formato:
      <roleta_id>|<url>
    e retorna um dict { roleta_id: url }.
    Se não encontrar o arquivo, loga um warning e retorna {}.
    """
    urls: dict[str, str] = {}

    # __file__ -> core/process_roulette.py
    project_root = Path(__file__).resolve().parent.parent
    links_file = project_root / "links.txt"

    if not links_file.exists():
        logging.warning(
            "Arquivo links.txt não encontrado em %s. Usando URLs padrão.",
            links_file
        )
        return urls

    try:
        with links_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or "|" not in line:
                    continue
                roleta_id, url = line.split("|", 1)
                urls[roleta_id.strip()] = url.strip()
    except Exception as e:
        logging.exception("Falha ao ler %s", links_file)

    return urls

# no fim do módulo, carrega uma vez
CASA_APOSTAS_URLS = load_casa_apostas_urls()

def get_mesa_url(roleta_id):
    # Tentar obter URL da casa de apostas do arquivo links.txt
    if roleta_id in CASA_APOSTAS_URLS:
        return CASA_APOSTAS_URLS[roleta_id]
    # URL padrão como fallback
    return f"https://bateu.bet.br/casino/game/{roleta_id}"


async def run_roleta(
    rid: str,
    detector: TriggerDetector,
    api: RouletteAPI,        # ← mesmo objeto para todas as roletas
    sem: asyncio.Semaphore,  # limita quantos bootstraps rodam de uma vez
    poll: float = 0.5,       # intervalo entre pools de 1 spin
):
    async with sem:
    # ────────────── Loop contínuo de spins ──────────────
        try:
            pending_triggers = []
            while True:
                resp = await api.api(rid, 1)
                if resp:
                    spin = resp["results"][0]
                    for evt in detector.feed(spin, emit=True, history=False, rid=rid):
                        yield evt
                        if evt["type"] == "trigger":
                            print(evt)
                            url = get_mesa_url(evt["rid"])
                            analize_message = (
                                f"🥷 VALIDANDO APOSTA ...  🥷\n"
                                f"🥷 ROLETA  {evt['rid']} {url}\n"
                                f"🥷 GATILHO {evt['trigger_by']}\n"
                                f"🥷 ALVO {evt['target']}\n"
                                f"🔥 Vou entrar em {evt['bets']} \n\n"
                                f"🔞 Apostas são para maiores de 18 anos, não há garantias de lucros, aposte com responsabilidade. 🔞"
                            )
                            
                            await send_telegram_message(analize_message)
                        
                            pending_triggers.append({
                                "num": evt["num"],
                                "trigger_by": evt["trigger_by"],
                                "rid" : evt["rid"],
                                "last_numbers" : evt["last_numbers"],
                                "bets": set(evt["bets"]),
                                "remaining": 3
                            })

                    # verifica se o spin atual paga algum gatilho anterior
                    for trigger in list(pending_triggers):
                        if spin in trigger["bets"]:
                            green_message = (
                                f"🥷  ✅ ✅ ✅  GREEN ✅ ✅ ✅  🥷\n"
                                f"🥷 ✅ ✅ ✅  ROLETA {trigger['rid']} ✅ ✅ ✅  🥷\n"
                                f"Qtd fichas: {len(trigger['bets'])}\n"
                                f"Qtd gales: 2\n"
                                f"Últimos números que saíram {trigger['last_numbers']}\n\n"
                                f"🔞 Apostas são para maiores de 18 anos, não há garantias de lucros, aposte com responsabilidade. 🔞"
                                )
                            print(f"✅ Gatilho {trigger['num']} pago com {spin}")
                            pending_triggers.remove(trigger)
                            await send_telegram_message(green_message)

                        else:
                            await send_telegram_message(f"❌ Gale #{trigger['remaining']} na rouleta {trigger['rid']}. último resultado {spin} ...")
                            trigger["remaining"] -= 1
                            if trigger["remaining"] <= 0:
                                red_message = (
                                    f"🥷 ❌❌❌ RED - {trigger['rid']} ❌❌❌ 🥷\n"
                                    f"Últimos números que saíram {trigger['last_numbers']}\n\n"
                                    f"🔞 Apostas são para maiores de 18 anos, não há garantias de lucros, aposte com responsabilidade. 🔞"
                                    )
                                await send_telegram_message(red_message)
                                print(f"❌ Gatilho {trigger['num']} NÃO pago")
                                pending_triggers.remove(trigger)

                await asyncio.sleep(poll)

        except asyncio.CancelledError:          
            raise
