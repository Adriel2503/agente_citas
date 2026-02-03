"""
Tools internas del agente de citas comerciales.
Estas tools son usadas por el LLM a través de function calling,
NO están expuestas directamente al orquestador.

Versión mejorada con logging, métricas, validación y runtime context (LangChain 1.2+).
"""

from typing import Any, Dict, Optional
from langchain.tools import tool, ToolRuntime

try:
    from ..services.schedule_validator import ScheduleValidator
    from ..services.booking import confirm_booking
    from ..logger import get_logger
    from ..metrics import track_tool_execution
    from ..validation import validate_booking_data
except ImportError:
    from citas.services.schedule_validator import ScheduleValidator
    from citas.services.booking import confirm_booking
    from citas.logger import get_logger
    from citas.metrics import track_tool_execution
    from citas.validation import validate_booking_data

logger = get_logger(__name__)


@tool
async def check_availability(
    service: str,
    date: str,
    time: Optional[str] = None,
    runtime: ToolRuntime = None
) -> str:
    """
    Consulta horarios disponibles para una cita/reunión y fecha (y opcionalmente hora).

    Usa esta herramienta cuando el cliente pregunte por disponibilidad
    o cuando necesites verificar si una fecha/hora específica está libre.

    Si el cliente indicó una hora concreta (ej. "a las 2pm", "a las 14:00"), pásala en time
    para consultar disponibilidad exacta de ese slot (CONSULTAR_DISPONIBILIDAD).
    Si no pasas time, se devuelven sugerencias para hoy/mañana (SUGERIR_HORARIOS).

    Args:
        service: Motivo de la reunión o nombre del servicio (ej: "demostración", "consulta", "reunión de ventas")
        date: Fecha en formato ISO (YYYY-MM-DD)
        time: Hora opcional en formato HH:MM AM/PM (ej. "2:00 PM") o 24h. Si el cliente dijo una hora concreta, pásala aquí.
        runtime: Runtime context automático (inyectado por LangChain)

    Returns:
        Texto con horarios disponibles o sugerencias para esa fecha/hora

    Examples:
        >>> await check_availability("demostración", "2026-01-27")
        "Horarios sugeridos: Lunes 27/01 - 09:00 AM, 10:00 AM, 02:00 PM..."
        >>> await check_availability("reunión de ventas", "2026-01-31", "2:00 PM")
        "El 2026-01-31 a las 2:00 PM está disponible. ¿Confirmamos la cita?"
    """
    logger.debug(f"[TOOL] check_availability - Servicio: {service}, Fecha: {date}, Hora: {time or 'no indicada'}")
    
    # Obtener configuración del runtime context
    ctx = runtime.context if runtime else None
    id_empresa = ctx.id_empresa if ctx else 1
    duracion_cita_minutos = ctx.duracion_cita_minutos if ctx else 60
    slots = ctx.slots if ctx else 60
    agendar_usuario = ctx.agendar_usuario if ctx else 1
    agendar_sucursal = ctx.agendar_sucursal if ctx else 0

    try:
        with track_tool_execution("check_availability"):
            # Crear validator con configuración
            validator = ScheduleValidator(
                id_empresa=id_empresa,
                duracion_cita_minutos=duracion_cita_minutos,
                slots=slots,
                es_cita=True,
                agendar_usuario=agendar_usuario,
                agendar_sucursal=agendar_sucursal
            )
            
            # Obtener recomendaciones. Si viene time, se consulta CONSULTAR_DISPONIBILIDAD para ese slot primero.
            recommendations = await validator.recommendation(
                fecha_solicitada=date,
                hora_solicitada=time.strip() if time and time.strip() else None,
            )
            
            if recommendations and recommendations.get("text"):
                logger.debug(f"[TOOL] check_availability - Recomendaciones obtenidas")
                return recommendations["text"]
            else:
                logger.warning(f"[TOOL] check_availability - Sin recomendaciones, usando fallback")
                return f"Horarios disponibles para {service} el {date}. Consulta directamente para más detalles."
    
    except Exception as e:
        logger.error(f"[TOOL] check_availability - Error: {e}", exc_info=True)
        # Fallback a respuesta genérica
        return f"Horarios típicos disponibles:\n• Mañana: 09:00, 10:00, 11:00\n• Tarde: 14:00, 15:00, 16:00"


@tool
async def create_booking(
    service: str,
    date: str,
    time: str,
    customer_name: str,
    customer_contact: str,
    runtime: ToolRuntime = None
) -> str:
    """
    Crea una nueva cita (evento en calendario) con validación y confirmación real.

    Usa esta herramienta SOLO cuando tengas TODOS los datos necesarios:
    - Motivo de la reunión/servicio, Fecha (YYYY-MM-DD), Hora (HH:MM AM/PM)
    - Nombre completo del cliente, Email del cliente (customer_contact)

    La herramienta validará el horario y creará el evento en ws_calendario (CREAR_EVENTO).
    La respuesta puede incluir enlace de videollamada (Google Meet) o mensaje de cita reservada.

    Args:
        service: Motivo de la reunión o servicio (ej: "demostración", "consulta", "reunión de ventas")
        date: Fecha de la cita (YYYY-MM-DD)
        time: Hora de la cita (HH:MM AM/PM)
        customer_name: Nombre completo del cliente
        customer_contact: Email del cliente (ej: cliente@ejemplo.com)
        runtime: Runtime context automático (inyectado por LangChain)

    Returns:
        Mensaje de confirmación, detalles (servicio, fecha, hora, nombre) y, si aplica,
        enlace de videollamada o aviso de "cita ya reservada"; o mensaje de error

    Examples:
        >>> await create_booking("demostración", "2026-01-27", "02:00 PM", "Juan Pérez", "cliente@ejemplo.com")
        "Evento agregado correctamente. Detalles: ... La reunión será por videollamada. Enlace: https://meet.google.com/..."
    """
    logger.debug(f"[TOOL] create_booking - {service} | {date} {time} | {customer_name}")

    # Obtener configuración del runtime context
    ctx = runtime.context if runtime else None
    id_empresa = ctx.id_empresa if ctx else 1
    duracion_cita_minutos = ctx.duracion_cita_minutos if ctx else 60
    slots = ctx.slots if ctx else 60
    agendar_usuario = ctx.agendar_usuario if ctx else 1  # bandera agendar_usuario para ScheduleValidator
    agendar_sucursal = ctx.agendar_sucursal if ctx else 0
    id_prospecto = ctx.id_prospecto if ctx else 0
    id_usuario = getattr(ctx, "id_usuario", 1) if ctx else 1
    correo_usuario = getattr(ctx, "correo_usuario", "") or ""

    try:
        with track_tool_execution("create_booking"):
            # 1. VALIDAR datos de entrada
            logger.debug("[TOOL] create_booking - Validando datos de entrada")
            is_valid, error = validate_booking_data(
                service=service,
                date=date,
                time=time,
                customer_name=customer_name,
                customer_contact=customer_contact
            )

            if not is_valid:
                logger.warning(f"[TOOL] create_booking - Datos inválidos: {error}")
                return f"Datos inválidos: {error}\n\nPor favor verifica la información."

            # 2. VALIDAR horario con ScheduleValidator
            logger.debug("[TOOL] create_booking - Validando horario")
            validator = ScheduleValidator(
                id_empresa=id_empresa,
                duracion_cita_minutos=duracion_cita_minutos,
                slots=slots,
                es_cita=True,
                agendar_usuario=agendar_usuario,
                agendar_sucursal=agendar_sucursal
            )

            validation = await validator.validate(date, time)
            logger.debug(f"[TOOL] create_booking - Validación: {validation}")

            if not validation["valid"]:
                logger.warning(f"[TOOL] create_booking - Horario no válido: {validation['error']}")
                return f"{validation['error']}\n\nPor favor elige otra fecha u hora."

            # 3. Crear evento en ws_calendario (CREAR_EVENTO)
            logger.debug("[TOOL] create_booking - Creando evento en API")
            id_prospecto_val = id_prospecto if (id_prospecto and id_prospecto > 0) else (ctx.session_id if ctx else 0)
            booking_result = await confirm_booking(
                id_usuario=id_usuario,
                id_prospecto=id_prospecto_val,
                nombre_completo=customer_name,
                correo_cliente=customer_contact or "",
                fecha=date,
                hora=time,
                servicio=service,
                agendar_usuario=agendar_usuario,
                duracion_cita_minutos=duracion_cita_minutos,
                correo_usuario=correo_usuario,
            )
            
            logger.debug(f"[TOOL] create_booking - Resultado: {booking_result}")
            
            if booking_result["success"]:
                api_message = booking_result.get("message") or "Evento creado correctamente"
                logger.info(f"[TOOL] create_booking - Éxito")
                lines = [
                    api_message,
                    "",
                    "**Detalles:**",
                    f"• Servicio: {service}",
                    f"• Fecha: {date}",
                    f"• Hora: {time}",
                    f"• Nombre: {customer_name}",
                    "",
                ]
                if booking_result.get("google_meet_link"):
                    lines.append(f"La reunión será por videollamada. Enlace: {booking_result['google_meet_link']}")
                elif booking_result.get("google_calendar_synced") is False:
                    lines.append("Tu cita ya está reservada. No se pudo generar el enlace de videollamada; te contactaremos con los detalles.")
                lines.append("")
                lines.append("¡Te esperamos!")
                return "\n".join(lines)
            else:
                error_msg = booking_result.get("error") or booking_result.get("message") or "No se pudo confirmar la cita"
                logger.warning(f"[TOOL] create_booking - Fallo: {error_msg}")
                return f"{error_msg}\n\nPor favor intenta nuevamente."
    
    except Exception as e:
        logger.error(f"[TOOL] create_booking - Error inesperado: {e}", exc_info=True)
        return f"Error inesperado al crear la cita: {str(e)}\n\nPor favor intenta nuevamente."


# Lista de todas las tools disponibles para el agente
AGENT_TOOLS = [
    check_availability,
    create_booking
]

__all__ = ["check_availability", "create_booking", "AGENT_TOOLS"]
