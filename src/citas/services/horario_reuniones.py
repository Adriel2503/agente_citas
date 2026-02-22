"""
Horario de reuniones: fetch desde API MaravIA y formateo para system prompt.
Usa OBTENER_HORARIO_REUNIONES (ws_informacion_ia.php).
"""

from typing import Any, Dict, Optional

import httpx

try:
    from .. import config as app_config
    from ..logger import get_logger
    from .http_client import post_with_retry
except ImportError:
    from citas import config as app_config
    from citas.logger import get_logger
    from citas.services.http_client import post_with_retry

logger = get_logger(__name__)

_DIAS_ORDEN = [
    ("Lunes", "reunion_lunes"),
    ("Martes", "reunion_martes"),
    ("Miércoles", "reunion_miercoles"),
    ("Jueves", "reunion_jueves"),
    ("Viernes", "reunion_viernes"),
    ("Sábado", "reunion_sabado"),
    ("Domingo", "reunion_domingo"),
]


def format_horario_for_system_prompt(horario_reuniones: Dict[str, Any]) -> str:
    """
    Formatea el horario de reuniones para inyectar en el system prompt.
    Estructura: lista por día con rango de hora o "Cerrado".

    Args:
        horario_reuniones: Dict con reunion_lunes, reunion_martes, etc.
                          Valores: "10:00-19:00" o null.

    Returns:
        String listo para el system prompt.
    """
    if not horario_reuniones:
        return "No hay horario cargado."

    lineas = []
    for nombre_dia, clave in _DIAS_ORDEN:
        valor = horario_reuniones.get(clave)
        if valor and str(valor).strip():
            rango = str(valor).strip().replace("-", " - ")
            lineas.append(f"- {nombre_dia}: {rango}")
        else:
            lineas.append(f"- {nombre_dia}: Cerrado")

    if not lineas:
        return "No hay horario cargado."
    return "\n".join(lineas)


async def fetch_horario_reuniones(id_empresa: Optional[Any]) -> str:
    """
    Obtiene el horario de reuniones desde la API y lo devuelve formateado para el system prompt.

    Args:
        id_empresa: ID de la empresa (int o str). Si es None, retorna mensaje por defecto.

    Returns:
        String formateado para el prompt o "No hay horario cargado." si falla.
    """
    if id_empresa is None or id_empresa == "":
        return "No hay horario cargado."

    payload = {
        "codOpe": "OBTENER_HORARIO_REUNIONES",
        "id_empresa": id_empresa,
    }
    try:
        logger.debug("[HORARIO] Obteniendo horario para id_empresa=%s", id_empresa)
        data = await post_with_retry(app_config.API_INFORMACION_URL, json=payload)
        if not data.get("success"):
            logger.info("[HORARIO] Respuesta recibida id_empresa=%s, API sin éxito: %s", id_empresa, data.get("error"))
            logger.warning("[HORARIO] API no success: %s", data.get("error"))
            return "No hay horario cargado."
        horario = data.get("horario_reuniones")
        if not horario:
            logger.info("[HORARIO] Respuesta recibida id_empresa=%s, horario vacío", id_empresa)
            return "No hay horario cargado."
        logger.info("[HORARIO] Respuesta recibida id_empresa=%s, horario cargado (%s días)", id_empresa, len(_DIAS_ORDEN))
        return format_horario_for_system_prompt(horario)
    except httpx.TimeoutException as e:
        logger.info("[HORARIO] No se pudo obtener horario id_empresa=%s: %s", id_empresa, e)
        logger.warning("[HORARIO] Timeout al obtener horario para system prompt")
        return "No hay horario cargado."
    except httpx.RequestError as e:
        logger.info("[HORARIO] No se pudo obtener horario id_empresa=%s: %s", id_empresa, e)
        logger.warning("[HORARIO] Error al obtener horario para system prompt: %s", e)
        return "No hay horario cargado."
    except Exception as e:
        logger.info("[HORARIO] No se pudo obtener horario id_empresa=%s: %s", id_empresa, e)
        logger.warning("[HORARIO] Error inesperado: %s", e)
        return "No hay horario cargado."


__all__ = ["fetch_horario_reuniones", "format_horario_for_system_prompt"]
