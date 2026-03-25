"""
Fetchers de datos para el system prompt: contexto, horario, FAQs, productos/servicios.
"""

from .contexto_negocio import fetch_contexto_negocio
from .funciones_especiales import fetch_funciones_especiales
from .horario_reuniones import fetch_horario_reuniones, format_horario_for_system_prompt
from .preguntas_frecuentes import fetch_preguntas_frecuentes, format_preguntas_frecuentes_para_prompt
from .productos_servicios_citas import fetch_nombres_productos_servicios, format_nombres_para_prompt

__all__ = [
    "fetch_contexto_negocio",
    "fetch_funciones_especiales",
    "fetch_horario_reuniones",
    "format_horario_for_system_prompt",
    "fetch_preguntas_frecuentes",
    "format_preguntas_frecuentes_para_prompt",
    "fetch_nombres_productos_servicios",
    "format_nombres_para_prompt",
]
