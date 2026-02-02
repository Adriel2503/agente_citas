"""
Agente especializado en citas - MaravIA

Versión 2.0.0 - LangChain 1.2+ API Moderna

Sistema mejorado con:
- LangChain 1.2+ API moderna con create_agent
- Memoria automática con checkpointer
- Runtime context para tools
- Logging centralizado
- Performance async (httpx)
- Cache global con TTL
- Validación de datos con Pydantic
- Métricas y observabilidad (Prometheus)
"""

__version__ = "2.0.0"
__author__ = "MaravIA Team"

# Exportar funciones principales
from .agent import process_cita_message
from .logger import get_logger, setup_logging
from .metrics import (
    track_chat_response,
    track_tool_execution,
    record_booking_success,
    record_booking_failure
)

__all__ = [
    # Core
    "process_cita_message",
    # Logging
    "get_logger",
    "setup_logging",
    # Metrics
    "track_chat_response",
    "track_tool_execution",
    "record_booking_success",
    "record_booking_failure",
]
