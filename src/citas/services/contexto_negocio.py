"""
Contexto de negocio: fetch desde API MaravIA para el system prompt.
Usa OBTENER_CONTEXTO_NEGOCIO (ws_informacion_ia.php).
Cache TTL + circuit breaker compartido (informacion_cb). El retry lo provee post_with_retry.
"""

import asyncio
from typing import Any, Dict, Optional

import httpx
from cachetools import TTLCache

try:
    from .. import config as app_config
    from ..logger import get_logger
    from .http_client import post_with_retry
    from .circuit_breaker import informacion_cb
except ImportError:
    from citas import config as app_config
    from citas.logger import get_logger
    from citas.services.http_client import post_with_retry
    from citas.services.circuit_breaker import informacion_cb

logger = get_logger(__name__)

# Cache TTL: mismo criterio que orquestador (max 500 empresas, 1 hora)
_contexto_cache: TTLCache = TTLCache(maxsize=500, ttl=3600)  # id_empresa -> contexto (str)

# Lock por id_empresa para evitar thundering herd (mismo patrón que horario_cache).
_fetch_locks: Dict[Any, asyncio.Lock] = {}


async def fetch_contexto_negocio(id_empresa: Optional[Any]) -> Optional[str]:
    """
    Obtiene el contexto de negocio desde la API para inyectar en el system prompt.
    Incluye cache TTL (1 h) y circuit breaker (3 fallos → abierto 5 min).
    El retry con backoff exponencial lo gestiona post_with_retry (configurable vía HTTP_RETRY_ATTEMPTS).

    Args:
        id_empresa: ID de la empresa (int o str). Si es None, retorna None.

    Returns:
        String con el contexto de negocio o None si no hay o falla.
    """
    if id_empresa is None or id_empresa == "":
        return None

    # 1. Cache
    if id_empresa in _contexto_cache:
        contexto = _contexto_cache[id_empresa]
        logger.debug(
            "[CONTEXTO_NEGOCIO] Cache hit id_empresa=%s (valor=%s)",
            id_empresa, "vacío" if not contexto else "presente"
        )
        logger.info(
            "[CONTEXTO_NEGOCIO] Respuesta recibida id_empresa=%s (cache), longitud=%s caracteres",
            id_empresa, len(contexto) if contexto else 0
        )
        return contexto if contexto else None

    # 2. Circuit breaker compartido (informacion_cb)
    if informacion_cb.is_open(id_empresa):
        return None

    # 3. Serializar fetch por id_empresa (thundering herd prevention)
    lock = _fetch_locks.setdefault(id_empresa, asyncio.Lock())
    async with lock:
        # Double-check: otra coroutine pudo llenar el cache mientras esperábamos
        if id_empresa in _contexto_cache:
            contexto = _contexto_cache[id_empresa]
            return contexto if contexto else None

        # Fetch con retry automático (post_with_retry: hasta 3 intentos, backoff 1s→2s→4s)
        payload = {
            "codOpe": "OBTENER_CONTEXTO_NEGOCIO",
            "id_empresa": id_empresa,
        }
        logger.debug("[CONTEXTO_NEGOCIO] Obteniendo contexto id_empresa=%s", id_empresa)

        try:
            data = await post_with_retry(app_config.API_INFORMACION_URL, json=payload)

            if not data.get("success"):
                logger.info(
                    "[CONTEXTO_NEGOCIO] Respuesta recibida id_empresa=%s, API sin éxito: %s",
                    id_empresa, data.get("error")
                )
                return None

            contexto = str(data.get("contexto_negocio") or "").strip()
            if contexto:
                logger.info(
                    "[CONTEXTO_NEGOCIO] Respuesta recibida id_empresa=%s, longitud=%s caracteres",
                    id_empresa, len(contexto)
                )
            else:
                logger.info("[CONTEXTO_NEGOCIO] Respuesta recibida id_empresa=%s, contexto vacío", id_empresa)

            _contexto_cache[id_empresa] = contexto
            informacion_cb.record_success(id_empresa)
            return contexto if contexto else None

        except httpx.TransportError as e:
            # Solo TransportError abre el circuit (post_with_retry agotó reintentos de red)
            informacion_cb.record_failure(id_empresa)
            logger.info(
                "[CONTEXTO_NEGOCIO] No se pudo obtener contexto id_empresa=%s tras reintentos: %s",
                id_empresa, e,
            )
            return None
        except Exception as e:
            logger.info(
                "[CONTEXTO_NEGOCIO] No se pudo obtener contexto id_empresa=%s: %s",
                id_empresa, e,
            )
            return None
        finally:
            _fetch_locks.pop(id_empresa, None)


__all__ = ["fetch_contexto_negocio"]
