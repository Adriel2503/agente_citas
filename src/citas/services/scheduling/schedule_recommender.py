"""
Sugerencias y consulta de disponibilidad de horarios (ws_agendar_reunion.php).

Responsabilidad única: recommendation() — responde "¿qué slots hay disponibles?"
Usa SUGERIR_HORARIOS y, si se da fecha+hora concretas, CONSULTAR_DISPONIBILIDAD.
Para validación estricta de un slot antes de crear la cita, ver schedule_validator.py.
"""

import json
import httpx
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ...logger import get_logger
from ...metrics import track_api_call
from ... import config as app_config
from ..infra import post_with_logging, agendar_reunion_cb as _default_agendar_cb, resilient_call, CircuitBreakerProtocol
from .availability_client import check_slot_availability
from .time_parser import DIAS_ESPANOL

logger = get_logger(__name__)

_ZONA_PERU = ZoneInfo(app_config.TIMEZONE)


class ScheduleRecommender:
    """Genera sugerencias de horarios disponibles para agendar una cita."""

    def __init__(
        self,
        id_empresa: int,
        duracion_cita_minutos: int,
        slots: int,
        agendar_usuario: int = 0,
        agendar_sucursal: int = 0,
        agendar_cb: CircuitBreakerProtocol | None = None,
    ):
        self.id_empresa = id_empresa
        self.duracion_cita = timedelta(minutes=duracion_cita_minutos)
        self.duracion_minutos = duracion_cita_minutos
        self.slots = slots
        self.agendar_usuario = agendar_usuario
        self.agendar_sucursal = agendar_sucursal
        self._agendar_cb = agendar_cb or _default_agendar_cb

    def _format_sugerencia(self, idx: int, sugerencia: dict) -> str | None:
        dia = sugerencia.get("dia", "")
        hora_legible = sugerencia.get("hora_legible", "")
        if not dia or not hora_legible:
            return None
        disponible = sugerencia.get("disponible", True)
        fecha_inicio = sugerencia.get("fecha_inicio", "")
        if dia == "hoy":
            texto = f"Hoy a las {hora_legible}"
        elif dia == "mañana":
            texto = f"Mañana a las {hora_legible}"
        elif fecha_inicio:
            try:
                fecha_obj = datetime.strptime(fecha_inicio, "%Y-%m-%d %H:%M:%S")
                dia_nombre = DIAS_ESPANOL.get(fecha_obj.strftime("%A"), fecha_obj.strftime("%A"))
                texto = f"{dia_nombre} {fecha_obj.strftime('%d/%m')} a las {hora_legible}"
            except ValueError:
                texto = f"{dia} a las {hora_legible}"
        else:
            texto = f"{dia} a las {hora_legible}"
        if not disponible:
            texto += " (ocupado)"
        return f"{idx}. {texto}"

    async def recommendation(
        self,
        fecha_solicitada: str | None = None,
        hora_solicitada: str | None = None,
    ) -> dict[str, Any]:
        """
        Genera recomendaciones de horarios disponibles.
        Si el cliente dio fecha Y hora concretas, primero consulta CONSULTAR_DISPONIBILIDAD para ese slot.
        Si solo fecha (o hoy/mañana sin hora), usa SUGERIR_HORARIOS o horario del día.

        Args:
            fecha_solicitada: Fecha en YYYY-MM-DD que el cliente está consultando. Opcional.
            hora_solicitada: Hora en HH:MM AM/PM que el cliente indicó. Opcional.

        Returns:
            Dict con "text" y opcionalmente "recommendations", "total", "message"
        """
        now_peru = datetime.now(_ZONA_PERU)
        hoy_iso = now_peru.strftime("%Y-%m-%d")
        manana_iso = (now_peru + timedelta(days=1)).strftime("%Y-%m-%d")

        # Si el cliente indicó fecha Y hora concretas, consultar disponibilidad exacta primero
        if fecha_solicitada and hora_solicitada and hora_solicitada.strip():
            try:
                availability = await check_slot_availability(
                    self.id_empresa,
                    fecha_solicitada.strip(),
                    hora_solicitada.strip(),
                    self.duracion_cita,
                    self.slots,
                    self.agendar_usuario,
                    self.agendar_sucursal,
                    cb=self._agendar_cb,
                )
                if availability.get("available"):
                    return {
                        "text": f"El {fecha_solicitada} a las {hora_solicitada.strip()} está disponible. ¿Confirmamos la cita?"
                    }
                error_msg = availability.get("error") or "Ese horario no está disponible."
                return {
                    "text": f"{error_msg} ¿Te gustaría que te sugiera otros horarios?"
                }
            except Exception as e:
                logger.warning("[RECOMMENDATION] Error al consultar disponibilidad para slot concreto: %s", e)
                # Sigue con flujo normal (SUGERIR_HORARIOS)

        # Si el cliente preguntó por una fecha que NO es hoy ni mañana, no usar SUGERIR_HORARIOS
        # (solo devuelve hoy/mañana). El horario de atención se da desde el system prompt.
        if fecha_solicitada:
            try:
                fecha_obj = datetime.strptime(fecha_solicitada.strip(), "%Y-%m-%d")
                fecha_iso = fecha_obj.strftime("%Y-%m-%d")
                if fecha_iso != hoy_iso and fecha_iso != manana_iso:
                    return {"text": "Para esa fecha indica una hora que prefieras y la verifico."}
            except ValueError:
                pass

        # 1. Intentar SUGERIR_HORARIOS (hoy y mañana)
        payload = {
            "codOpe": "SUGERIR_HORARIOS",
            "id_empresa": self.id_empresa,
            "duracion_minutos": self.duracion_minutos,
            "slots": self.slots,
            "agendar_usuario": self.agendar_usuario,
            "agendar_sucursal": self.agendar_sucursal,
        }

        logger.debug(
            "[RECOMMENDATION] JSON enviado a ws_agendar_reunion.php (SUGERIR_HORARIOS): %s",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        try:
            with track_api_call("sugerir_horarios"):
                data = await resilient_call(
                    lambda: post_with_logging(app_config.API_AGENDAR_REUNION_URL, payload),
                    cb=self._agendar_cb,
                    circuit_key=self.id_empresa,
                    service_name="SUGERIR_HORARIOS",
                )

            if data.get("success"):
                sugerencias = data.get("sugerencias", [])
                mensaje = data.get("mensaje", "Horarios disponibles encontrados")
                total = data.get("total", 0)
                if sugerencias and total > 0:
                    sugerencias_texto = [t for i, s in enumerate(sugerencias, 1) if (t := self._format_sugerencia(i, s))]
                    if sugerencias_texto:
                        texto_final = (
                            f"{mensaje}\n\n" + "\n".join(sugerencias_texto)
                            if mensaje
                            else "Horarios sugeridos:\n\n" + "\n".join(sugerencias_texto)
                        )
                        return {
                            "text": texto_final,
                            "recommendations": sugerencias,
                            "total": total,
                            "message": mensaje,
                        }
        except RuntimeError:
            logger.warning("[RECOMMENDATION] Circuit abierto para ws_agendar_reunion")
        except (httpx.TimeoutException, httpx.HTTPError) as e:
            logger.warning("[RECOMMENDATION] Error en SUGERIR_HORARIOS, usando fallback: %s", e)
        except Exception as e:
            logger.warning("[RECOMMENDATION] Error inesperado en SUGERIR_HORARIOS: %s", e)

        # 2. Fallback: sin llamar API (el horario de atención se da desde el system prompt)
        return {"text": "No pude obtener sugerencias ahora. Indica una fecha y hora que prefieras y la verifico."}


__all__ = ["ScheduleRecommender"]
