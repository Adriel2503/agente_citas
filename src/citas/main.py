"""
Servidor MCP del agente especializado en citas / reuniones.
Usa FastMCP para exponer herramientas según el protocolo MCP.

Versión mejorada con logging, métricas y observabilidad.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Dict
from fastmcp import FastMCP
from prometheus_client import make_asgi_app

try:
    from . import config as app_config
    from .agent import process_cita_message
    from .logger import setup_logging, get_logger
    from .metrics import initialize_agent_info
    from .services.http_client import close_http_client
except ImportError:
    from citas import config as app_config
    from citas.agent import process_cita_message
    from citas.logger import setup_logging, get_logger
    from citas.metrics import initialize_agent_info
    from citas.services.http_client import close_http_client

# Configurar logging antes de cualquier otra cosa
log_level = getattr(logging, app_config.LOG_LEVEL.upper(), logging.INFO)
setup_logging(
    level=log_level,
    log_file=app_config.LOG_FILE if app_config.LOG_FILE else None
)

logger = get_logger(__name__)

# Inicializar información del agente para métricas
initialize_agent_info(model=app_config.OPENAI_MODEL, version="2.0.0")

@asynccontextmanager
async def app_lifespan(server=None):
    """Lifespan del servidor: cierra el cliente HTTP compartido al apagar (compatible FastMCP v2)."""
    try:
        yield {}
    finally:
        await close_http_client()


# Inicializar servidor MCP
mcp = FastMCP(
    name="Agente Citas",
    instructions="Agente especializado en gestión de citas y reuniones",
    lifespan=app_lifespan,
)


@mcp.tool(name="cita_chat")
async def chat(
    message: str,
    session_id: int,
    context: Dict[str, Any] | None = None
) -> str:
    """
    Agente especializado en citas / reuniones.
    
    Esta es la ÚNICA herramienta que el orquestador debe llamar.
    Internamente, el agente usa tools propias para:
    - Consultar disponibilidad de horarios (check_availability)
    - Crear citas/eventos con validación real (create_booking)
    
    El agente maneja la conversación completa de forma autónoma,
    decidiendo cuándo usar cada tool según el contexto.
    La memoria es automática gracias al checkpointer (InMemorySaver).
    
    Args:
        message: Mensaje del cliente que quiere agendar una cita
        session_id: ID de sesión (int, unificado con orquestador)
        context: Contexto adicional requerido:
            - config.id_empresa (int, requerido): ID de la empresa
            - config.usuario_id (int, opcional): ID del usuario/vendedor (para CREAR_EVENTO en ws_calendario)
            - config.correo_usuario (str, opcional): Email del usuario/vendedor (para CREAR_EVENTO)
            - config.agendar_usuario (bool o int, opcional): 1=agendar por usuario, 0=no (default: 1)
            - config.agendar_sucursal (bool o int, opcional): 1=agendar por sucursal, 0=no (default: 0)
            - config.duracion_cita_minutos (int, opcional): Duración en minutos (default: 60)
            - config.slots (int, opcional): Slots disponibles (default: 60)
            - config.personalidad (str, opcional): Personalidad del agente
    
    Returns:
        Respuesta del agente especializado en citas
    
    Examples:
        >>> context = {
        ...     "config": {
        ...         "id_empresa": 123,
        ...         "personalidad": "amable y profesional"
        ...     }
        ... }
        >>> await chat("Quiero agendar una cita", 3671, context)
        "¡Perfecto! ¿Para qué fecha y hora te gustaría la reunión?"
    """
    if context is None:
        context = {}
    
    logger.info("[MCP] Mensaje recibido - Session: %s, Length: %s chars", session_id, len(message))
    logger.debug("[MCP] Message: %s...", message[:100])
    logger.debug("[MCP] Context keys: %s", list(context.keys()))
    
    try:
        reply = await asyncio.wait_for(
            process_cita_message(
                message=message,
                session_id=session_id,
                context=context
            ),
            timeout=app_config.CHAT_TIMEOUT,
        )

        logger.info("[MCP] Respuesta generada - Length: %s chars", len(reply))
        logger.debug("[MCP] Reply: %s...", reply[:200])
        return reply

    except asyncio.TimeoutError:
        error_msg = f"La solicitud tardó más de {app_config.CHAT_TIMEOUT}s. Por favor, intenta de nuevo."
        logger.error("[MCP] Timeout en process_cita_message (CHAT_TIMEOUT=%s)", app_config.CHAT_TIMEOUT)
        return error_msg

    except ValueError as e:
        error_msg = f"Error de configuración: {str(e)}"
        logger.error("[MCP] %s", error_msg)
        return error_msg

    except asyncio.CancelledError:
        raise

    except Exception as e:
        error_msg = f"Error procesando mensaje: {str(e)}"
        logger.error("[MCP] %s", error_msg, exc_info=True)
        return error_msg


# Endpoint de métricas para Prometheus (opcional)
metrics_app = make_asgi_app()


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("INICIANDO AGENTE CITAS - MaravIA")
    logger.info("=" * 60)
    logger.info("Host: %s:%s", app_config.SERVER_HOST, app_config.SERVER_PORT)
    logger.info("Modelo: %s", app_config.OPENAI_MODEL)
    logger.info("Timeout LLM: %ss", app_config.OPENAI_TIMEOUT)
    logger.info("Timeout API: %ss", app_config.API_TIMEOUT)
    logger.info("Cache TTL: %s min", app_config.SCHEDULE_CACHE_TTL_MINUTES)
    logger.info("Log Level: %s", app_config.LOG_LEVEL)
    logger.info("-" * 60)
    logger.info("Tool expuesta al orquestador: cita_chat")
    logger.info("Tools internas del agente:")
    logger.info("- check_availability (consulta horarios)")
    logger.info("- create_booking (crea citas/eventos)")
    logger.info("- search_productos_servicios (busca productos/servicios)")
    logger.info("-" * 60)
    logger.info("Métricas disponibles en /metrics (Prometheus)")
    logger.info("=" * 60)
    
    # Ejecutar servidor MCP
    try:
        mcp.run(
            transport="http",  # HTTP para conectar servicios separados
            host=app_config.SERVER_HOST,
            port=app_config.SERVER_PORT
        )
    except KeyboardInterrupt:
        logger.info("\nServidor detenido por el usuario")
    except Exception as e:
        logger.critical("Error crítico en el servidor: %s", e, exc_info=True)
        raise
