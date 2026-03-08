"""
Servicios del agente de citas: booking, horario_reuniones, schedule_validator,
schedule_recommender, productos_servicios_citas, busqueda_productos.
"""

from .infra import get_client, close_http_client
from .booking import confirm_booking
from .contexto_negocio import fetch_contexto_negocio
from .horario_reuniones import fetch_horario_reuniones
from .schedule_validator import ScheduleValidator
from .schedule_recommender import ScheduleRecommender
from .time_parser import parse_time, parse_time_range, is_time_blocked
from .productos_servicios_citas import fetch_nombres_productos_servicios, format_nombres_para_prompt
from .busqueda_productos import buscar_productos_servicios, format_productos_para_respuesta
from .preguntas_frecuentes import fetch_preguntas_frecuentes, format_preguntas_frecuentes_para_prompt

__all__ = [
    "get_client",
    "close_http_client",
    "confirm_booking",
    "fetch_contexto_negocio",
    "fetch_horario_reuniones",
    "ScheduleValidator",
    "ScheduleRecommender",
    "parse_time",
    "parse_time_range",
    "is_time_blocked",
    "fetch_nombres_productos_servicios",
    "format_nombres_para_prompt",
    "buscar_productos_servicios",
    "format_productos_para_respuesta",
    "fetch_preguntas_frecuentes",
    "format_preguntas_frecuentes_para_prompt",
]
