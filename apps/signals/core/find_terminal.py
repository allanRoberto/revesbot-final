import logging
import asyncio

from helpers.utils.telegram import (
    send_telegram_message,
    delete_telegram_message
)

from pathlib import Path

from colorama import init, Fore, Back, Style
init(autoreset=True)

from typing import List


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


async def process(roulette_id,numbers,api) : 
    print(f"\n\nProcessando roleta {roulette_id} - {numbers[0:2]}")
    url = get_mesa_url(roulette_id);

    idxs = (0, 1)
    p0, p1 = [numbers[i] for i in idxs]

    terminal_4 = [4, 14, 24]

    terminal_9 = [9,19,29] 

    if(p1 in terminal_4 and p0 in terminal_9 and 5 not in numbers[1:4] and 0 not in numbers[1:4]) : 
        print("Gatilho detectado!")

        numbers_bet = [0, 2, 3, 5, 10, 12, 15, 17, 19, 24, 25, 32]

        message = (
                    f"🥷 MINHA PRÓXIMA ENTRADA 🥷\n"
                    f"🥷 GATILHO {p0} 🥷\n"
                    f"Qtd fichas: {len(numbers_bet)}\n"
                    f"🎰 *Mesa:* [{roulette_id}]({url})\n\n"
                    f"🔥 Vou entrar em {numbers_bet} \n\n"
                )
                        
        await send_telegram_message(message)

        red_message = (
                        f"🥷 ❌❌❌ RED - {roulette_id} ❌❌❌ 🥷\n"
                        f"Últimos números que saíram {numbers[0]},{numbers[1]},{numbers[2]}\n\n"
                        f"🔞 Apostas são para maiores de 18 anos, não há garantias de lucros, aposte com responsabilidade. 🔞"
                        )

        gale = 3
        attempt = 0
        hit = False

        spin_message_ids = []


        while attempt < gale and not hit:
            # pega só o spin mais recente quando for novo
                #aguarda mais um spin
            while True:
                new_spin = await api.api(roulette_id, num_results=1)
                if new_spin:
                    break
                await asyncio.sleep(2)

            r = new_spin["results"][0] 

            if r in numbers_bet:

                green_message = (
                    f"🥷  ✅ ✅ ✅  GREEN ✅ ✅ ✅  🥷\n"
                    f"🥷 ✅ ✅ ✅  ROLETA {roulette_id} ✅ ✅ ✅  🥷\n"
                    f"Qtd fichas: {len(numbers_bet)}\n"
                    f"Qtd gales: {attempt}\n"
                    f"Lucro em fichas nessa aposta: { (36 - len(numbers_bet)*attempt)}\n"
                    f"Últimos números que saíram {numbers[0]},{numbers[1]},{numbers[2]}\n\n"
                    f"🔞 Apostas são para maiores de 18 anos, não há garantias de lucros, aposte com responsabilidade. 🔞"
                )
        
                for mid in spin_message_ids:
                    await delete_telegram_message(mid)
                spin_message_ids.clear()

                

                await send_telegram_message(green_message)
                hit = True
            else:
                mid = await send_telegram_message(f"❌ Gale #{attempt+1} na rouleta {roulette_id} ...")
                spin_message_ids.append(mid)
                attempt += 1
                # aguarda antes da próxima tentativa
                await asyncio.sleep(0.5)

        if not hit:
            for mid in spin_message_ids:
                await delete_telegram_message(mid)
            spin_message_ids.clear()
            await send_telegram_message(red_message)

    else : 
        print("Pulando...")
            