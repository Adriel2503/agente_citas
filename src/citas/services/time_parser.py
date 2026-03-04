"""
Utilidades de parsing de tiempo: puras, sin red, sin async.
Testeables de forma aislada.
"""

import json
from datetime import datetime

# Mapeo int(weekday) → campo BD. Compartido por schedule_validator y horario_reuniones.
DAY_FIELD_MAP: dict[int, str] = {
    0: "reunion_lunes",
    1: "reunion_martes",
    2: "reunion_miercoles",
    3: "reunion_jueves",
    4: "reunion_viernes",
    5: "reunion_sabado",
    6: "reunion_domingo",
}

# Lista ordenada (nombre display, campo BD). Usada por horario_reuniones.
DIAS_ORDEN: list[tuple[str, str]] = [
    ("Lunes",     "reunion_lunes"),
    ("Martes",    "reunion_martes"),
    ("Miércoles", "reunion_miercoles"),
    ("Jueves",    "reunion_jueves"),
    ("Viernes",   "reunion_viernes"),
    ("Sábado",    "reunion_sabado"),
    ("Domingo",   "reunion_domingo"),
]


def parse_time(time_str: str) -> datetime | None:
    """Parsea una hora en formato HH:MM AM/PM o HH:MM."""
    time_str = time_str.strip().upper()
    for fmt in ["%I:%M %p", "%I:%M%p", "%H:%M"]:
        try:
            return datetime.strptime(time_str, fmt)
        except ValueError:
            continue
    return None


def parse_time_range(range_str: str) -> tuple[datetime, datetime] | None:
    """Parsea un rango de horario como '09:00-18:00' o '9:00 AM - 6:00 PM'."""
    if not range_str:
        return None
    # Normalizar: quitar espacios y separar por "-"
    parts = range_str.replace(" ", "").split("-")
    if len(parts) != 2:
        return None
    start = parse_time(parts[0])
    end = parse_time(parts[1])
    if start and end:
        return (start, end)
    return None


def is_time_blocked(
    fecha: datetime,
    hora: datetime,
    horarios_bloqueados: str,
    logger=None,
) -> bool:
    """
    Verifica si la hora está en los horarios bloqueados.

    Args:
        fecha: Fecha de la cita
        hora: Hora de la cita
        horarios_bloqueados: String JSON o CSV con horarios bloqueados
        logger: Logger opcional para warnings

    Returns:
        True si está bloqueado, False en caso contrario
    """
    if not horarios_bloqueados:
        return False

    try:
        try:
            bloqueados = json.loads(horarios_bloqueados)
        except json.JSONDecodeError:
            bloqueados = [b.strip() for b in horarios_bloqueados.split(",")]

        fecha_str = fecha.strftime("%Y-%m-%d")

        for bloqueo in bloqueados:
            if isinstance(bloqueo, dict):
                if bloqueo.get("fecha") == fecha_str:
                    inicio = parse_time(bloqueo.get("inicio", ""))
                    fin = parse_time(bloqueo.get("fin", ""))
                    if inicio and fin and inicio.time() <= hora.time() < fin.time():
                        if logger:
                            logger.debug("[BLOCKED] Hora %s está bloqueada", hora.time())
                        return True
            elif isinstance(bloqueo, str):
                if fecha_str in bloqueo:
                    rango = parse_time_range(bloqueo.replace(fecha_str, "").strip())
                    if rango:
                        inicio, fin = rango
                        if inicio.time() <= hora.time() < fin.time():
                            if logger:
                                logger.debug("[BLOCKED] Hora %s está bloqueada", hora.time())
                            return True

    except Exception as e:
        if logger:
            logger.warning("[SCHEDULE] Error parseando horarios bloqueados: %s", e)

    return False


__all__ = ["parse_time", "parse_time_range", "is_time_blocked", "DAY_FIELD_MAP", "DIAS_ORDEN"]
