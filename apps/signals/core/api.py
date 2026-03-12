from typing import Any, Dict, List, Union
import asyncio
import httpx
import logging
import os

from dotenv import load_dotenv


load_dotenv()

URL_API = os.environ.get("BASE_URL_API", "")

logger = logging.getLogger(__name__)

class RouletteAPIError(Exception):
    """Erro de camada de API para consultas de histórico de roleta."""
    pass


class RouletteAPI:
    def __init__(self, base_url: str = URL_API):
        self.base_url = base_url.rstrip("/")

    async def api(self, slug: str, num_results: int = 500, full_results : bool = False) -> Dict[str, Any]:
        """
        Consulta o histórico da roleta no endpoint /history/{slug}.
        - Retorna sempre um dicionário com {slug, url, results}.
        - Em caso de falha (HTTP, timeout, JSON inválido ou formato inesperado),
          levanta RouletteAPIError para o chamador tratar (e.g., retries).
        """

        if full_results :
            url = f"{self.base_url}/history-detailed/{slug}?limit={num_results}"
        else :
            url = f"{self.base_url}/history/{slug}?limit={num_results}"

        # Defina timeouts explícitos para evitar pendurar indefinidamente
        timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url)
                # Levanta HTTPStatusError para status >= 400
                resp.raise_for_status()

                try:
                    data: Union[List[int], Dict[str, Any]] = resp.json()
                except Exception as exc:
                    raise RouletteAPIError(
                        f"JSON inválido recebido para {slug} em {url}"
                    ) from exc

                # Aceita dois formatos: lista bruta de ints OU dict com 'results'
                if isinstance(data, list):
                    results = data[:num_results]
                elif isinstance(data, dict):
                    raw = data.get("results", [])
                    if not isinstance(raw, list):
                        raise RouletteAPIError(
                            f"Campo 'results' ausente ou não-lista para {slug} em {url}"
                        )
                    results = raw[:num_results]
                else:
                    raise RouletteAPIError(
                        f"Formato de resposta inesperado ({type(data).__name__}) para {slug} em {url}"
                    )

                logger.info("✅ %d resultados obtidos para %s", len(results), slug)
                return {"slug": slug, "url": url, "results": results}

        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            # Erros de rede/HTTP/timeout mapeados para erro de domínio
            logger.error("❌ Falha HTTP/Timeout ao consultar %s: %s", slug, exc)
            raise RouletteAPIError(f"Falha ao consultar roleta {slug}: {exc}") from exc
        except RouletteAPIError:
            # Repassa erros de formato/JSON já normalizados
            raise
        except Exception as exc:
            # Qualquer outro erro inesperado
            logger.exception("❌ Erro inesperado ao consultar %s", slug)
            raise RouletteAPIError(f"Erro inesperado ao consultar roleta {slug}: {exc}") from exc
