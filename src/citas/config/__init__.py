"""
Configuración del agente de citas. Re-exporta variables de config y modelos.
"""

from .config import (
    OPENAI_API_KEY,
    OPENAI_MODEL,
    OPENAI_TEMPERATURE,
    SERVER_HOST,
    SERVER_PORT,
    LOG_LEVEL,
    LOG_FILE,
    OPENAI_TIMEOUT,
    API_TIMEOUT,
    CHAT_TIMEOUT,
    MAX_TOKENS,
    SCHEDULE_CACHE_TTL_MINUTES,
    API_CALENDAR_URL,
    API_AGENDAR_REUNION_URL,
    API_INFORMACION_URL,
    TIMEZONE,
)
from .models import CitaConfig, ChatRequest, ChatResponse

__all__ = [
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_TEMPERATURE",
    "SERVER_HOST",
    "SERVER_PORT",
    "LOG_LEVEL",
    "LOG_FILE",
    "OPENAI_TIMEOUT",
    "API_TIMEOUT",
    "CHAT_TIMEOUT",
    "MAX_TOKENS",
    "SCHEDULE_CACHE_TTL_MINUTES",
    "API_CALENDAR_URL",
    "API_AGENDAR_REUNION_URL",
    "API_INFORMACION_URL",
    "TIMEZONE",
    "CitaConfig",
    "ChatRequest",
    "ChatResponse",
]
