"""
Contexto de negocio: fetch desde API MaravIA para el system prompt.
Usa OBTENER_CONTEXTO_NEGOCIO (ws_informacion_ia.php).
Sin cache propio: el agente (TTL 60 min) ya cachea el system prompt completo.
"""

from typing import Any

from ... import config as app_config
from ...logger import get_logger
from ...infra import post_with_logging, informacion_cb as _default_informacion_cb, resilient_call, CircuitBreakerProtocol

logger = get_logger(__name__)


async def fetch_contexto_negocio(
    id_empresa: Any | None,
    cb: CircuitBreakerProtocol | None = None,
) -> str | None:
    """
    Obtiene el contexto de negocio desde la API para inyectar en el system prompt.
    Circuit breaker compartido (informacion_cb): 3 fallos → abierto 5 min.
    El retry con backoff lo gestiona post_with_logging (tenacity).

    Args:
        id_empresa: ID de la empresa. Si es None o vacío, retorna None.

    Returns:
        String con el contexto de negocio o None si no hay datos o falla.
    """
    if id_empresa is None or id_empresa == "":
        return None

    _cb = cb or _default_informacion_cb
    payload = {"codOpe": "OBTENER_CONTEXTO_NEGOCIO", "id_empresa": id_empresa}
    logger.debug("[CONTEXTO_NEGOCIO] Obteniendo contexto id_empresa=%s", id_empresa)

    try:
        data = await resilient_call(
            lambda: post_with_logging(app_config.API_INFORMACION_URL, payload),
            cb=_cb,
            circuit_key=id_empresa,
            service_name="CONTEXTO_NEGOCIO",
        )
        if not data.get("success"):
            logger.info("[CONTEXTO_NEGOCIO] API sin éxito id_empresa=%s: %s", id_empresa, data.get("error"))
            return None
        contexto = str(data.get("contexto_negocio") or "").strip()
        logger.info("[CONTEXTO_NEGOCIO] Obtenido id_empresa=%s, %s caracteres", id_empresa, len(contexto))
        return contexto or None
    except Exception as e:
        logger.info("[CONTEXTO_NEGOCIO] No se pudo obtener id_empresa=%s: %s", id_empresa, e)
        return None


__all__ = ["fetch_contexto_negocio"]
