"""
Horario de reuniones: fetch directo desde API MaravIA y formateo para system prompt.
Usa OBTENER_HORARIO_REUNIONES (ws_informacion_ia.php).
El agent cache (60 min) protege esta llamada — se ejecuta una vez por empresa cada 60 min.
"""

from typing import Any

try:
    from .. import config as app_config
    from ..logger import get_logger
    from .http_client import post_with_logging
    from .circuit_breaker import informacion_cb as _default_informacion_cb
    from ._resilience import resilient_call, CircuitBreakerProtocol
    from .time_parser import DIAS_ORDEN
except ImportError:
    from citas import config as app_config
    from citas.logger import get_logger
    from citas.services.http_client import post_with_logging
    from citas.services.circuit_breaker import informacion_cb as _default_informacion_cb
    from citas.services._resilience import resilient_call, CircuitBreakerProtocol
    from citas.services.time_parser import DIAS_ORDEN

logger = get_logger(__name__)


def format_horario_for_system_prompt(horario_reuniones: dict[str, Any]) -> str:
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
    for nombre_dia, clave in DIAS_ORDEN:
        valor = horario_reuniones.get(clave)
        if valor and str(valor).strip():
            rango = str(valor).strip().replace("-", " - ")
            lineas.append(f"- {nombre_dia}: {rango}")
        else:
            lineas.append(f"- {nombre_dia}: Cerrado")

    if not lineas:
        return "No hay horario cargado."
    return "\n".join(lineas)


async def fetch_horario_reuniones(
    id_empresa: Any | None,
    cb: CircuitBreakerProtocol | None = None,
) -> str:
    """
    Obtiene el horario de reuniones desde la API y lo devuelve formateado
    para el system prompt.

    Llama directo a la API sin cache propio — el agent cache (60 min) ya
    garantiza que esta función se ejecuta una sola vez por empresa cada 60 min.

    Args:
        id_empresa: ID de la empresa. Si es None, retorna mensaje por defecto.

    Returns:
        String formateado para el prompt o "No hay horario cargado." si falla.
    """
    if not id_empresa:
        return "No hay horario cargado."

    _cb = cb or _default_informacion_cb
    payload = {"codOpe": "OBTENER_HORARIO_REUNIONES", "id_empresa": id_empresa}
    logger.debug("[HORARIO] Fetching id_empresa=%s", id_empresa)

    try:
        data = await resilient_call(
            lambda: post_with_logging(app_config.API_INFORMACION_URL, payload),
            cb=_cb,
            circuit_key=id_empresa,
            service_name="HORARIO_REUNIONES",
        )
        if data.get("success") and data.get("horario_reuniones"):
            logger.info("[HORARIO] Horario cargado id_empresa=%s", id_empresa)
            return format_horario_for_system_prompt(data["horario_reuniones"])
        logger.info("[HORARIO] Sin horario id_empresa=%s", id_empresa)
    except Exception as e:
        logger.info("[HORARIO] No se pudo obtener id_empresa=%s: %s", id_empresa, e)

    return "No hay horario cargado."


__all__ = ["fetch_horario_reuniones", "format_horario_for_system_prompt"]
