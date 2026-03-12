import aiohttp
import asyncio

async def send_telegram_message(message: str, max_retries: int = 3, retry_delay: float = 0.5) -> int | None:
    telegram_token = "8025852537:AAFj-j0rDK22RV5dZwdlHcxigLwwNwDo3ws"
    chat_id        = "-1002634558541"
    url            = f"https://api.telegram.org/bot{telegram_token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }

    for attempt in range(1, max_retries + 1):
        async with aiohttp.ClientSession() as sess:
            try:
                async with sess.post(url, data=payload, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        msg_id = data["result"]["message_id"]
                        print(f"Mensagem enviada com sucesso. ID: {msg_id}")
                        return msg_id
                    else:
                        print(f"[Tentativa {attempt}] Erro ao enviar mensagem. HTTP {resp.status}")
            except Exception as e:
                print(f"[Tentativa {attempt}] Erro ao enviar mensagem: {e}")
        
        if attempt < max_retries:
            await asyncio.sleep(retry_delay)

    print("Falha ao enviar mensagem após múltiplas tentativas.")
    return None

async def delete_telegram_message(message_id: int) -> None:
    telegram_token = "8025852537:AAFj-j0rDK22RV5dZwdlHcxigLwwNwDo3ws"
    chat_id        = "-1002634558541"
    url            = f"https://api.telegram.org/bot{telegram_token}/deleteMessage"

    payload = {"chat_id": chat_id, "message_id": message_id}

    async with aiohttp.ClientSession() as sess:
        try:
            async with sess.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    print(f"Mensagem {message_id} excluída.")
                else:
                    print(f"Erro HTTP {resp.status} ao excluir mensagem.")
        except Exception as e:
            print(f"Erro ao excluir mensagem: {e}")