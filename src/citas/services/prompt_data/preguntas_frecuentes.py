"""
Preguntas frecuentes: fetch desde API MaravIA (ws_preguntas_frecuentes.php) para el system prompt.
Formato Pregunta/Respuesta para que el modelo entienda y use las FAQs.
Sin cache propio: el agente (TTL 60 min) ya cachea el system prompt completo.
"""

from typing import Any

from ... import config as app_config
from ...logger import get_logger
from ..infra import post_with_logging, preguntas_cb as _default_preguntas_cb, resilient_call, CircuitBreakerProtocol

logger = get_logger(__name__)


def format_preguntas_frecuentes_para_prompt(items: list[dict[str, Any]]) -> str:
    """
    Formatea la lista de FAQs (solo pregunta y respuesta) para inyectar en el system prompt.
    Usa etiquetas "Pregunta:" y "Respuesta:" para que el modelo entienda el formato.

    Args:
        items: Lista de dicts con "pregunta" y "respuesta".

    Returns:
        String listo para el system prompt.
    """
    if not items:
        return ""

    lineas = []
    for item in items:
        pregunta = (item.get("pregunta") or "").strip()
        respuesta = (item.get("respuesta") or "").strip()
        if not pregunta and not respuesta:
            continue
        categoria = (item.get("categoria") or "").strip()
        if categoria:
            lineas.append(f"[{categoria}]")
        lineas.append(f"Pregunta: {pregunta or '(sin texto)'}")
        lineas.append(f"Respuesta: {respuesta or '(sin texto)'}")
        archivo = (item.get("archivo_ayuda") or "").strip()
        if archivo:
            lineas.append(f"Archivo de ayuda: {archivo}")
        lineas.append("")

    return "\n".join(lineas).strip() if lineas else ""


async def fetch_preguntas_frecuentes(
    id_chatbot: Any | None,
    cb: CircuitBreakerProtocol | None = None,
) -> str:
    """
    Obtiene las preguntas frecuentes desde la API para inyectar en el system prompt.
    Circuit breaker compartido (preguntas_cb): 3 fallos → abierto 5 min.
    El retry con backoff lo gestiona post_with_logging (tenacity).

    Args:
        id_chatbot: ID del chatbot (int o str). Si es None o vacío, retorna "".

    Returns:
        String formateado (Pregunta:/Respuesta:) o "" si no hay datos o falla.
    """
    if id_chatbot is None or id_chatbot == "":
        return ""

    _cb = cb or _default_preguntas_cb
    if _cb.is_open(id_chatbot):
        return ""

    payload = {"id_chatbot": id_chatbot}
    logger.debug("[PREGUNTAS_FRECUENTES] Obteniendo FAQs id_chatbot=%s", id_chatbot)

    try:
        data = await resilient_call(
            lambda: post_with_logging(app_config.API_PREGUNTAS_FRECUENTES_URL, payload),
            cb=_cb,
            circuit_key=id_chatbot,
            service_name="PREGUNTAS_FRECUENTES",
        )
        if not data.get("success"):
            logger.info("[PREGUNTAS_FRECUENTES] API sin éxito id_chatbot=%s: %s", id_chatbot, data.get("error"))
            return ""
        items = data.get("preguntas_frecuentes") or []
        if not items:
            logger.info("[PREGUNTAS_FRECUENTES] Sin preguntas id_chatbot=%s", id_chatbot)
            return ""
        logger.info("[PREGUNTAS_FRECUENTES] %s preguntas obtenidas id_chatbot=%s", len(items), id_chatbot)
        return format_preguntas_frecuentes_para_prompt(items)
    except Exception as e:
        logger.info("[PREGUNTAS_FRECUENTES] No se pudo obtener id_chatbot=%s: %s", id_chatbot, e)
        return ""


__all__ = ["fetch_preguntas_frecuentes", "format_preguntas_frecuentes_para_prompt"]
