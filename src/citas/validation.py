"""
Validadores de datos para el agente de citas.
Valida formato de email, fechas, etc. Para citas se acepta solo email (no teléfono).
"""

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError, field_validator

try:
    from .. import config as app_config  # pyright: ignore[reportMissingImports]
except ImportError:
    from citas import config as app_config

# Patrón básico para email (RFC 5322 simplificado)
_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)

# ========== LÓGICA DE VALIDACIÓN (funciones privadas) ==========
# Centralizadas aquí para que BookingData las use en sus field_validator.

def _check_email(v: str) -> str:
    v = v.strip()
    if not v:
        raise ValueError('El email no puede estar vacío.')
    if len(v) > 254:
        raise ValueError('El email es demasiado largo.')
    if not _EMAIL_PATTERN.match(v):
        raise ValueError(
            'El contacto debe ser un email válido (ejemplo: nombre@dominio.com). '
            f'Recibido: {v}'
        )
    return v.lower()


def _check_name(v: str) -> str:
    v = v.strip()
    if len(v) < 2:
        raise ValueError('El nombre debe tener al menos 2 caracteres')
    if re.search(r'\d', v):
        raise ValueError('El nombre no debe contener números')
    if not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s\-\']+$', v):
        raise ValueError('El nombre contiene caracteres no válidos')
    return v.title()


def _check_date(v: str) -> str:
    try:
        date_obj = datetime.strptime(v, "%Y-%m-%d")
        if date_obj.date() < datetime.now(ZoneInfo(app_config.TIMEZONE)).date():
            raise ValueError('La fecha no puede ser en el pasado')
        return v
    except ValueError as e:
        if "does not match format" in str(e):
            raise ValueError('Formato de fecha inválido. Debe ser YYYY-MM-DD (ejemplo: 2026-01-27)')
        raise


def _check_time(v: str) -> str:
    v = v.strip().upper()
    for fmt in ["%I:%M %p", "%I:%M%p", "%H:%M"]:
        try:
            datetime.strptime(v, fmt)
            return v
        except ValueError:
            continue
    raise ValueError(
        'Formato de hora inválido. Debe ser HH:MM AM/PM (ejemplo: 02:30 PM) o HH:MM (ejemplo: 14:30)'
    )


# ========== MODELOS PYDANTIC ==========

class BookingData(BaseModel):
    """Valida todos los datos necesarios para una cita."""

    date: str = Field(..., description="Fecha de la cita")
    time: str = Field(..., description="Hora de la cita")
    customer_name: str = Field(..., description="Nombre del cliente")
    customer_contact: str = Field(..., description="Email del cliente")

    @field_validator('customer_name')
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return _check_name(v)

    @field_validator('customer_contact')
    @classmethod
    def _validate_contact(cls, v: str) -> str:
        return _check_email(v)

    @field_validator('date')
    @classmethod
    def _validate_date(cls, v: str) -> str:
        return _check_date(v)

    @field_validator('time')
    @classmethod
    def _validate_time(cls, v: str) -> str:
        return _check_time(v)


def _format_validation_error(e: ValidationError) -> str:
    """Convierte ValidationError de Pydantic en un mensaje legible para el usuario."""
    errors = e.errors()
    if not errors:
        return str(e)[:500] if len(str(e)) > 500 else str(e)
    msg = errors[0].get("msg", str(e))
    if isinstance(msg, str) and msg.lower().startswith("value error, "):
        return msg[13:].strip()
    return msg if isinstance(msg, str) else str(msg)[:500]


def validate_date_format(date: str) -> tuple[bool, str | None]:
    """
    Comprueba que date sea YYYY-MM-DD (solo formato; no comprueba si está en el pasado).
    Returns:
        (True, None) si es válido; (False, mensaje) si no.
    """
    if not date or not date.strip():
        return (False, "La fecha es obligatoria en formato YYYY-MM-DD (ej. 2026-01-27).")
    s = date.strip()
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return (True, None)
    except ValueError:
        return (False, f"La fecha debe estar en formato YYYY-MM-DD (ej. 2026-01-27). Recibido: {s}.")


def validate_booking_data(
    date: str,
    time: str,
    customer_name: str,
    customer_contact: str
) -> tuple[bool, str | None]:
    """
    Valida todos los datos de una cita.

    Returns:
        (True, None) si todos los datos son válidos
        (False, mensaje_error) si hay algún error
    """
    try:
        BookingData(
            date=date,
            time=time,
            customer_name=customer_name,
            customer_contact=customer_contact
        )
        return (True, None)
    except ValidationError as e:
        return (False, _format_validation_error(e))
    except ValueError as e:
        return (False, str(e))


__all__ = [
    'BookingData',
    'validate_booking_data',
    'validate_date_format',
]
