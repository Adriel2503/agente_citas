"""
Función para crear evento en el calendario (ws_calendario.php).
Alineado con CREAR_EVENTO: id_usuario, id_prospecto, titulo, fecha_inicio, fecha_fin,
correo_cliente, correo_usuario, agendar_usuario.
"""

import json
import re
from datetime import datetime, timedelta

import httpx
from typing import Any, Dict

try:
    from ..logger import get_logger
    from ..metrics import track_api_call, record_booking_attempt, record_booking_success, record_booking_failure
    from .. import config as app_config
except ImportError:
    from citas.logger import get_logger
    from citas.metrics import track_api_call, record_booking_attempt, record_booking_success, record_booking_failure
    from citas import config as app_config

logger = get_logger(__name__)


def _parse_time_to_24h(hora: str) -> str:
    """Convierte hora en formato HH:MM AM/PM a HH:MM (24h)."""
    hora = hora.strip()
    match = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)", hora, re.IGNORECASE)
    if not match:
        raise ValueError(f"Hora no válida (esperado HH:MM AM/PM): {hora}")
    h, m, ampm = int(match.group(1)), int(match.group(2)), match.group(3).upper()
    if ampm == "PM" and h != 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{m:02d}:00"


def _build_fecha_inicio_fin(fecha: str, hora: str, duracion_minutos: int) -> tuple:
    """Construye fecha_inicio y fecha_fin en formato YYYY-MM-DD HH:MM:SS."""
    time_24 = _parse_time_to_24h(hora)
    fecha_inicio = f"{fecha} {time_24}"
    try:
        dt_start = datetime.strptime(fecha_inicio, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        raise ValueError(f"Fecha/hora no válidos: {fecha} {hora}")
    dt_end = dt_start + timedelta(minutes=duracion_minutos)
    fecha_fin = dt_end.strftime("%Y-%m-%d %H:%M:%S")
    return fecha_inicio, fecha_fin


async def confirm_booking(
    id_usuario: int,
    id_prospecto: int,
    nombre_completo: str,
    correo_cliente: str,
    fecha: str,
    hora: str,
    servicio: str,
    agendar_usuario: int,
    duracion_cita_minutos: int = 60,
    correo_usuario: str = "",
    log_create_booking_apis: bool = False,
) -> Dict[str, Any]:
    """
    Crea un evento en el calendario (ws_calendario.php, CREAR_EVENTO).

    Args:
        id_usuario: ID del usuario (vendedor) que registra la cita
        id_prospecto: ID del prospecto/cliente (int, mismo que session_id del orquestador)
        nombre_completo: Nombre completo del cliente
        correo_cliente: Email del cliente (correo_cliente en API)
        fecha: Fecha en formato YYYY-MM-DD
        hora: Hora en formato HH:MM AM/PM
        servicio: Servicio/motivo de la cita (usado en titulo)
        agendar_usuario: 1 = asignar vendedor automáticamente, 0 = no
        duracion_cita_minutos: Minutos de la cita para calcular fecha_fin
        correo_usuario: Email del usuario/vendedor (desde orquestador)

    Returns:
        Dict con: success, message, error
    """
    record_booking_attempt()

    try:
        fecha_inicio, fecha_fin = _build_fecha_inicio_fin(fecha, hora, duracion_cita_minutos)
    except ValueError as e:
        logger.warning(f"[BOOKING] Fecha/hora inválidos: {e}")
        record_booking_failure("invalid_datetime")
        return {
            "success": False,
            "message": "Formato de fecha u hora inválido",
            "error": str(e),
        }

    try:
        titulo = f"Reunion para el usuario: {nombre_completo}"

        payload = {
            "codOpe": "CREAR_EVENTO",
            "id_usuario": id_usuario,
            "id_prospecto": id_prospecto,
            "titulo": titulo,
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "correo_cliente": (correo_cliente or "").strip(),
            "correo_usuario": (correo_usuario or "").strip(),
            "agendar_usuario": agendar_usuario,
        }

        if log_create_booking_apis:
            logger.info("[create_booking] API 3: ws_calendario.php - CREAR_EVENTO")
            logger.info("  URL: %s", app_config.API_CALENDAR_URL)
            logger.info("  Enviado: %s", json.dumps(payload, ensure_ascii=False))
        logger.debug(f"[BOOKING] Creando evento: {servicio} - {fecha} {hora} - {nombre_completo}")
        logger.debug(f"[BOOKING] Payload: {payload}")
        logger.debug("[BOOKING] JSON enviado a ws_calendario.php (CREAR_EVENTO): %s", json.dumps(payload, ensure_ascii=False, indent=2))

        with track_api_call("crear_evento"):
            async with httpx.AsyncClient(timeout=app_config.API_TIMEOUT) as client:
                response = await client.post(
                    app_config.API_CALENDAR_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                data = response.json()

        if log_create_booking_apis:
            logger.info("  Respuesta: %s", json.dumps(data, ensure_ascii=False))
        logger.debug(f"[BOOKING] Respuesta API: {data}")

        if data.get("success"):
            message = data.get("message") or "Evento creado correctamente"
            logger.info(f"[BOOKING] Evento creado - {message}")
            record_booking_success()
            result = {
                "success": True,
                "message": message,
                "error": None,
            }
            # Pasar respuesta de ws_calendario para que el agente responda al usuario
            if data.get("google_meet_link"):
                result["google_meet_link"] = data["google_meet_link"]
            result["google_calendar_synced"] = data.get("google_calendar_synced", False)
            if data.get("google_calendar_error"):
                result["google_calendar_error"] = data["google_calendar_error"]
            return result
        else:
            error_msg = data.get("message") or data.get("error") or "Error desconocido"
            logger.warning(f"[BOOKING] Creación fallida: {error_msg}")
            record_booking_failure("api_error")
            return {
                "success": False,
                "message": error_msg,
                "error": error_msg,
            }

    except httpx.TimeoutException:
        logger.error("[BOOKING] Timeout al crear evento")
        record_booking_failure("timeout")
        return {
            "success": False,
            "message": "La conexión tardó demasiado tiempo",
            "error": "timeout",
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"[BOOKING] Error HTTP {e.response.status_code}: {e}")
        record_booking_failure(f"http_{e.response.status_code}")
        return {
            "success": False,
            "message": f"Error del servidor ({e.response.status_code})",
            "error": str(e),
        }

    except httpx.RequestError as e:
        logger.error(f"[BOOKING] Error de conexión: {e}")
        record_booking_failure("connection_error")
        return {
            "success": False,
            "message": "Error al conectar con el servidor",
            "error": str(e),
        }

    except Exception as e:
        logger.error(f"[BOOKING] Error inesperado: {e}", exc_info=True)
        record_booking_failure("unknown_error")
        return {
            "success": False,
            "message": "Error inesperado al crear el evento",
            "error": str(e),
        }


__all__ = ["confirm_booking"]
