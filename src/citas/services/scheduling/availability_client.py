"""
Cliente de disponibilidad para ws_agendar_reunion.php (CONSULTAR_DISPONIBILIDAD).

Infraestructura compartida entre ScheduleValidator (validación de slot en paso 12)
y ScheduleRecommender (verificación de slot concreto cuando el usuario da fecha+hora).
"""

import json
import httpx
from datetime import datetime, timedelta
from typing import Any

from ...logger import get_logger
from ...metrics import track_api_call, degradation_total
from ... import config as app_config
from ..infra import post_with_logging, agendar_reunion_cb as _default_agendar_cb, resilient_call, CircuitBreakerProtocol
from .time_parser import parse_time

logger = get_logger(__name__)


async def check_slot_availability(
    id_empresa: Any,
    fecha_str: str,
    hora_str: str,
    duracion_cita: timedelta,
    slots: int,
    agendar_usuario: int,
    agendar_sucursal: int,
    log_api: bool = False,
    cb: CircuitBreakerProtocol | None = None,
) -> dict[str, Any]:
    """
    Consulta CONSULTAR_DISPONIBILIDAD en ws_agendar_reunion.php.

    Compartida por ScheduleValidator (validate) y ScheduleRecommender (recommendation).
    Retorna graceful degradation (available=True) ante cualquier error de red/CB.

    Args:
        id_empresa: ID de la empresa (circuit breaker key).
        fecha_str: Fecha en formato YYYY-MM-DD.
        hora_str: Hora en formato HH:MM AM/PM.
        duracion_cita: Duración de la cita como timedelta.
        slots: Slots disponibles.
        agendar_usuario: 1 = asignar vendedor, 0 = no.
        agendar_sucursal: 1 = asignar sucursal, 0 = no.
        log_api: Si True, loguea URL, payload y respuesta en INFO.
        cb: Circuit breaker inyectable. Si None, usa agendar_reunion_cb global.

    Returns:
        Dict con:
        - available (bool): True si el slot está disponible o ante degradación.
        - error (str | None): Mensaje de error si no está disponible.
    """
    _cb = cb or _default_agendar_cb
    try:
        fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
        hora = parse_time(hora_str)
        if not hora:
            degradation_total.labels(service="availability_check", reason="parse_error").inc()
            return {"available": True, "error": None}

        fecha_hora_inicio = fecha.replace(hour=hora.hour, minute=hora.minute)
        fecha_hora_fin = fecha_hora_inicio + duracion_cita

        payload = {
            "codOpe": "CONSULTAR_DISPONIBILIDAD",
            "id_empresa": id_empresa,
            "fecha_inicio": fecha_hora_inicio.strftime("%Y-%m-%d %H:%M:%S"),
            "fecha_fin": fecha_hora_fin.strftime("%Y-%m-%d %H:%M:%S"),
            "slots": slots,
            "agendar_usuario": agendar_usuario,
            "agendar_sucursal": agendar_sucursal,
        }

        if log_api:
            logger.info("[create_booking] API 2: ws_agendar_reunion.php - CONSULTAR_DISPONIBILIDAD")
            logger.info("  URL: %s", app_config.API_AGENDAR_REUNION_URL)
            logger.info("  Enviado: %s", json.dumps(payload, ensure_ascii=False))
        logger.debug("[AVAILABILITY] Consultando: %s %s", fecha_str, hora_str)
        logger.debug(
            "[AVAILABILITY] JSON enviado a ws_agendar_reunion.php (CONSULTAR_DISPONIBILIDAD): %s",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

        with track_api_call("consultar_disponibilidad"):
            data = await resilient_call(
                lambda: post_with_logging(app_config.API_AGENDAR_REUNION_URL, payload),
                cb=_cb,
                circuit_key=id_empresa,
                service_name="CONSULTAR_DISPONIBILIDAD",
            )

        if log_api:
            logger.info("  Respuesta: %s", json.dumps(data, ensure_ascii=False))
        logger.debug("[AVAILABILITY] Disponible: %s", data.get("disponible"))

        if not data.get("success"):
            logger.warning("[AVAILABILITY] Respuesta sin éxito: %s", data)
            degradation_total.labels(service="availability_check", reason="api_success_false").inc()
            return {"available": True, "error": None}  # Graceful degradation

        if data.get("disponible"):
            return {"available": True, "error": None}
        return {
            "available": False,
            "error": "El horario seleccionado ya está ocupado. Por favor elige otra hora o fecha.",
        }

    except RuntimeError:
        logger.warning("[AVAILABILITY] Circuit abierto para ws_agendar_reunion")
        degradation_total.labels(service="availability_check", reason="circuit_open").inc()
        return {"available": True, "error": None}
    except httpx.TimeoutException:
        logger.warning("[AVAILABILITY] Timeout - graceful degradation")
        degradation_total.labels(service="availability_check", reason="timeout").inc()
        return {"available": True, "error": None}
    except httpx.HTTPError as e:
        logger.warning("[AVAILABILITY] Error HTTP: %s - graceful degradation", e)
        degradation_total.labels(service="availability_check", reason="http_error").inc()
        return {"available": True, "error": None}
    except Exception as e:
        logger.warning("[AVAILABILITY] Error inesperado: %s - graceful degradation", e)
        degradation_total.labels(service="availability_check", reason="unknown").inc()
        return {"available": True, "error": None}


__all__ = ["check_slot_availability"]
