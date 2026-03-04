"""
Validador de horarios para citas/reuniones.
Verifica formato, horario de atención, slots bloqueados y disponibilidad real.

Responsabilidad única: validate() — responde "¿es válido este slot?"
Para sugerencias de horarios disponibles, ver schedule_recommender.py.
"""

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

try:
    from ..logger import get_logger
    from .. import config as app_config
    from .http_client import post_with_logging
    from .circuit_breaker import agendar_reunion_cb as _default_agendar_cb, informacion_cb as _default_informacion_cb
    from ._resilience import resilient_call, CircuitBreakerProtocol
    from .time_parser import parse_time, parse_time_range, is_time_blocked, DAY_FIELD_MAP, DIAS_NOMBRE
    from .availability_client import check_slot_availability
except ImportError:
    from citas.logger import get_logger
    from citas import config as app_config
    from citas.services.http_client import post_with_logging
    from citas.services.circuit_breaker import agendar_reunion_cb as _default_agendar_cb, informacion_cb as _default_informacion_cb
    from citas.services._resilience import resilient_call, CircuitBreakerProtocol
    from citas.services.time_parser import parse_time, parse_time_range, is_time_blocked, DAY_FIELD_MAP, DIAS_NOMBRE
    from citas.services.availability_client import check_slot_availability

logger = get_logger(__name__)

_ZONA_PERU = ZoneInfo(app_config.TIMEZONE)


class ScheduleValidator:
    """Valida si una fecha y hora son válidas para agendar una cita."""

    def __init__(
        self,
        id_empresa: int,
        duracion_cita_minutos: int = 60,
        slots: int = 60,
        agendar_usuario: int = 0,
        agendar_sucursal: int = 0,
        log_create_booking_apis: bool = False,
        informacion_cb: CircuitBreakerProtocol | None = None,
        agendar_cb: CircuitBreakerProtocol | None = None,
    ):
        self.id_empresa = id_empresa
        self.duracion_cita = timedelta(minutes=duracion_cita_minutos)
        self.slots = slots
        self.agendar_usuario = agendar_usuario
        self.agendar_sucursal = agendar_sucursal
        self.log_create_booking_apis = log_create_booking_apis
        self._informacion_cb = informacion_cb or _default_informacion_cb
        self._agendar_cb = agendar_cb or _default_agendar_cb

    async def _fetch_horario(self) -> dict | None:
        """Obtiene el horario directo desde la API (sin cache)."""
        if self._informacion_cb.is_open(self.id_empresa):
            return None
        payload = {"codOpe": "OBTENER_HORARIO_REUNIONES", "id_empresa": self.id_empresa}
        try:
            data = await resilient_call(
                lambda: post_with_logging(app_config.API_INFORMACION_URL, payload),
                cb=self._informacion_cb,
                circuit_key=self.id_empresa,
                service_name="SCHEDULE_VALIDATOR",
            )
            if data.get("success") and data.get("horario_reuniones"):
                return data["horario_reuniones"]
        except Exception:
            pass
        return None

    async def validate(self, fecha_str: str, hora_str: str) -> dict[str, Any]:
        """
        Valida si la fecha y hora son válidas para agendar.

        Args:
            fecha_str: Fecha en formato YYYY-MM-DD
            hora_str: Hora en formato HH:MM AM/PM

        Returns:
            Dict con:
            - valid: bool
            - error: str (mensaje de error si no es válido)
        """
        # 1. Parsear fecha
        try:
            fecha = datetime.strptime(fecha_str, "%Y-%m-%d")
        except ValueError:
            return {"valid": False, "error": "Formato de fecha inválido. Usa el formato YYYY-MM-DD (ejemplo: 2026-01-25)."}

        # 2. Parsear hora
        hora = parse_time(hora_str)
        if not hora:
            return {"valid": False, "error": "Formato de hora inválido. Usa el formato HH:MM AM/PM (ejemplo: 10:30 AM)."}

        # 3. Combinar fecha y hora
        fecha_hora_cita = fecha.replace(hour=hora.hour, minute=hora.minute)

        # 4. Validar que no sea en el pasado (zona horaria Lima, no la del servidor)
        ahora = datetime.now(_ZONA_PERU).replace(tzinfo=None)
        if fecha_hora_cita <= ahora:
            return {"valid": False, "error": "La fecha y hora seleccionada ya pasó. Por favor elige una fecha y hora futura."}

        # 5. Obtener horario de reuniones
        schedule = await self._fetch_horario()
        if not schedule:
            logger.warning("[SCHEDULE] No se pudo obtener horario, permitiendo cita")
            return {"valid": True, "error": None}

        # 6. Obtener el día de la semana
        dia_semana = fecha.weekday()  # 0=Lunes, 6=Domingo
        campo_dia = DAY_FIELD_MAP.get(dia_semana)
        horario_dia = schedule.get(campo_dia)
        nombre_dia = DIAS_NOMBRE[dia_semana]

        if not horario_dia:
            return {"valid": False, "error": f"No hay horario disponible para el día {nombre_dia}. Por favor elige otro día."}

        # 7. Verificar si el día está marcado como no disponible
        horario_dia_upper = horario_dia.strip().upper()
        if horario_dia_upper in ["NO DISPONIBLE", "CERRADO", "NO ATIENDE", "-", "N/A", ""]:
            return {"valid": False, "error": f"No hay atención el día {nombre_dia}. Por favor elige otro día."}

        # 8. Parsear el rango de horario del día
        rango = parse_time_range(horario_dia)
        if not rango:
            logger.warning("[SCHEDULE] No se pudo parsear horario del día: %s", horario_dia)
            return {"valid": True, "error": None}

        hora_inicio, hora_fin = rango
        horario_formateado = f"{hora_inicio.strftime('%I:%M %p')} a {hora_fin.strftime('%I:%M %p')}"

        # 9. Validar que la hora esté dentro del rango
        if hora.time() < hora_inicio.time():
            return {"valid": False, "error": f"La hora seleccionada es antes del horario de atención. El horario del {nombre_dia} es de {horario_formateado}."}

        if hora.time() >= hora_fin.time():
            return {"valid": False, "error": f"La hora seleccionada es después del horario de atención. El horario del {nombre_dia} es de {horario_formateado}."}

        # 10. Validar que la cita + duración no exceda la hora de cierre
        hora_fin_cita = fecha_hora_cita + self.duracion_cita
        hora_cierre = fecha.replace(hour=hora_fin.hour, minute=hora_fin.minute)

        if hora_fin_cita > hora_cierre:
            return {
                "valid": False,
                "error": f"La cita de {self.duracion_cita.seconds // 60} minutos excedería el horario de atención (cierre: {hora_fin.strftime('%I:%M %p')}). El horario del {nombre_dia} es de {horario_formateado}. Por favor elige una hora más temprana.",
            }

        # 11. Validar horarios bloqueados
        horarios_bloqueados = schedule.get("horarios_bloqueados", "")
        if is_time_blocked(fecha, hora, horarios_bloqueados):
            return {"valid": False, "error": "El horario seleccionado está bloqueado. Por favor elige otra hora."}

        # 12. Verificar disponibilidad contra citas existentes
        availability = await check_slot_availability(
            self.id_empresa, fecha_str, hora_str, self.duracion_cita,
            self.slots, self.agendar_usuario, self.agendar_sucursal,
            self.log_create_booking_apis,
            cb=self._agendar_cb,
        )
        if not availability["available"]:
            return {"valid": False, "error": availability["error"]}

        logger.debug("[VALIDATION] Horario válido: %s %s", fecha_str, hora_str)
        return {"valid": True, "error": None}


__all__ = ["ScheduleValidator"]
