"""
Funciones especiales: fetch desde API MaravIA para el system prompt.
Usa OBTENER_FUNCIONES_ESPECIALES (ws_informacion_ia.php).
Sin cache propio: el agente (TTL 60 min) ya cachea el system prompt completo.
"""

from typing import Any

from ... import config as app_config
from ...logger import get_logger
from ...infra import post_with_logging, resilient_call, CircuitBreaker
from ...config import informacion_cb as _default_informacion_cb

logger = get_logger(__name__)


async def fetch_funciones_especiales(
    id_empresa: Any | None,
    cb: CircuitBreaker | None = None,
) -> str | None:
    """
    Obtiene las instrucciones especiales de la empresa para inyectar en el system prompt.
    Circuit breaker compartido (informacion_cb): 3 fallos -> abierto 5 min.

    Args:
        id_empresa: ID de la empresa. Si es None o vacío, retorna None.

    Returns:
        String con las instrucciones especiales o None si no hay datos o falla.
    """
    if id_empresa is None or id_empresa == "":
        return None

    _cb = cb or _default_informacion_cb
    payload = {"codOpe": "OBTENER_FUNCIONES_ESPECIALES", "id_empresa": id_empresa}
    logger.debug("[FUNCIONES_ESPECIALES] Obteniendo funciones id_empresa=%s", id_empresa)

    try:
        data = await resilient_call(
            lambda: post_with_logging(app_config.API_INFORMACION_URL, payload),
            cb=_cb,
            circuit_key=id_empresa,
            service_name="FUNCIONES_ESPECIALES",
        )
        if not data.get("success"):
            logger.info("[FUNCIONES_ESPECIALES] API sin éxito id_empresa=%s: %s", id_empresa, data.get("error"))
            return None
        funciones = str(data.get("funciones_especiales") or "").strip()
        logger.info("[FUNCIONES_ESPECIALES] Obtenido id_empresa=%s, %s caracteres", id_empresa, len(funciones))
        return funciones or None
    except Exception as e:
        logger.info("[FUNCIONES_ESPECIALES] No se pudo obtener id_empresa=%s: %s", id_empresa, e)
        return None


__all__ = ["fetch_funciones_especiales"]
