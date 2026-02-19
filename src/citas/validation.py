"""
Validadores de datos para el agente de citas.
Valida formato de email, fechas, etc. Para citas se acepta solo email (no teléfono).
"""

import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

try:
    from .. import config as app_config
except ImportError:
    from citas import config as app_config

# Patrón básico para email (RFC 5322 simplificado)
_EMAIL_PATTERN = re.compile(
    r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
)


class ContactInfo(BaseModel):
    """Valida información de contacto (email para citas)."""
    
    contact: str = Field(..., description="Email del cliente")
    
    @field_validator('contact')
    @classmethod
    def validate_contact(cls, v: str) -> str:
        """
        Valida que sea un email válido. Para citas solo se acepta email.
        """
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
    
    @property
    def is_email(self) -> bool:
        """Retorna True (siempre, ya que solo aceptamos email para citas)."""
        return True


class CustomerName(BaseModel):
    """Valida nombre de cliente."""
    
    name: str = Field(..., min_length=2, max_length=100, description="Nombre del cliente")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Valida que el nombre sea válido."""
        v = v.strip()
        
        # Debe tener al menos 2 caracteres
        if len(v) < 2:
            raise ValueError('El nombre debe tener al menos 2 caracteres')
        
        # No debe contener números
        if re.search(r'\d', v):
            raise ValueError('El nombre no debe contener números')
        
        # Debe contener solo letras, espacios, guiones y apóstrofes
        if not re.match(r'^[a-zA-ZáéíóúÁÉÍÓÚñÑ\s\-\']+$', v):
            raise ValueError('El nombre contiene caracteres no válidos')
        
        return v.title()  # Capitalizar


class BookingDateTime(BaseModel):
    """Valida fecha y hora de la cita."""
    
    date: str = Field(..., description="Fecha en formato YYYY-MM-DD")
    time: str = Field(..., description="Hora en formato HH:MM AM/PM")
    
    @field_validator('date')
    @classmethod
    def validate_date(cls, v: str) -> str:
        """Valida formato de fecha."""
        try:
            date_obj = datetime.strptime(v, "%Y-%m-%d")
            
            # Validar que no sea en el pasado (usa hora de Perú, no del servidor)
            if date_obj.date() < datetime.now(ZoneInfo(app_config.TIMEZONE)).date():
                raise ValueError('La fecha no puede ser en el pasado')
            
            return v
        except ValueError as e:
            if "does not match format" in str(e):
                raise ValueError('Formato de fecha inválido. Debe ser YYYY-MM-DD (ejemplo: 2026-01-27)')
            raise
    
    @field_validator('time')
    @classmethod
    def validate_time(cls, v: str) -> str:
        """Valida formato de hora."""
        v = v.strip().upper()
        
        # Intentar parsear con diferentes formatos
        time_formats = ["%I:%M %p", "%I:%M%p", "%H:%M"]
        
        for fmt in time_formats:
            try:
                datetime.strptime(v, fmt)
                return v
            except ValueError:
                continue
        
        raise ValueError(
            'Formato de hora inválido. Debe ser HH:MM AM/PM (ejemplo: 02:30 PM) o HH:MM (ejemplo: 14:30)'
        )


class BookingData(BaseModel):
    """Valida todos los datos necesarios para una cita."""
    
    date: str = Field(..., description="Fecha de la cita")
    time: str = Field(..., description="Hora de la cita")
    customer_name: str = Field(..., description="Nombre del cliente")
    customer_contact: str = Field(..., description="Email del cliente")
    
    @model_validator(mode='after')
    def validate_booking(self):
        """Valida la cita completa."""
        # Validar nombre
        try:
            CustomerName(name=self.customer_name)
        except ValueError as e:
            raise ValueError(f"Nombre inválido: {e}")
        
        # Validar contacto
        try:
            ContactInfo(contact=self.customer_contact)
        except ValueError as e:
            raise ValueError(f"Contacto inválido: {e}")
        
        # Validar fecha y hora
        try:
            BookingDateTime(date=self.date, time=self.time)
        except ValueError as e:
            raise ValueError(f"Fecha/hora inválida: {e}")
        
        return self


# ========== FUNCIONES DE UTILIDAD ==========

def validate_contact(contact: str) -> tuple[bool, Optional[str]]:
    """
    Valida un contacto y retorna (es_valido, error_mensaje).
    
    Returns:
        (True, None) si es válido
        (False, mensaje_error) si no es válido
    """
    try:
        ContactInfo(contact=contact)
        return (True, None)
    except ValueError as e:
        return (False, str(e))


def validate_customer_name(name: str) -> tuple[bool, Optional[str]]:
    """
    Valida un nombre de cliente y retorna (es_valido, error_mensaje).
    
    Returns:
        (True, None) si es válido
        (False, mensaje_error) si no es válido
    """
    try:
        CustomerName(name=name)
        return (True, None)
    except ValueError as e:
        return (False, str(e))


def validate_datetime(date: str, time: str) -> tuple[bool, Optional[str]]:
    """
    Valida fecha y hora y retorna (es_valido, error_mensaje).
    
    Returns:
        (True, None) si es válido
        (False, mensaje_error) si no es válido
    """
    try:
        BookingDateTime(date=date, time=time)
        return (True, None)
    except ValueError as e:
        return (False, str(e))


def validate_booking_data(
    date: str,
    time: str,
    customer_name: str,
    customer_contact: str
) -> tuple[bool, Optional[str]]:
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
    except ValueError as e:
        return (False, str(e))


__all__ = [
    'ContactInfo',
    'CustomerName',
    'BookingDateTime',
    'BookingData',
    'validate_contact',
    'validate_customer_name',
    'validate_datetime',
    'validate_booking_data',
]
