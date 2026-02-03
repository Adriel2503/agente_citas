"""
Lógica del agente especializado en citas usando LangChain 1.2+ API moderna.
Versión mejorada con logging, métricas, configuración centralizada y memoria automática.
"""

from typing import Any, Dict
from dataclasses import dataclass

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver

try:
    from .. import config as app_config
    from ..config.models import CitaConfig
    from ..tool.tools import AGENT_TOOLS
    from ..logger import get_logger
    from ..metrics import track_chat_response, track_llm_call, record_chat_error, chat_requests_total
    from ..prompts import build_citas_system_prompt
except ImportError:
    from citas import config as app_config
    from citas.config.models import CitaConfig
    from citas.tool.tools import AGENT_TOOLS
    from citas.logger import get_logger
    from citas.metrics import track_chat_response, track_llm_call, record_chat_error, chat_requests_total
    from citas.prompts import build_citas_system_prompt

logger = get_logger(__name__)

# Checkpointer global para memoria automática
_checkpointer = InMemorySaver()

@dataclass
class AgentContext:
    """
    Esquema de contexto runtime para el agente.
    Este contexto se inyecta en las tools que lo necesiten.
    """
    id_empresa: int
    duracion_cita_minutos: int = 60
    slots: int = 60
    agendar_usuario: int = 1  # bandera agendar_usuario (1/0) para ScheduleValidator
    id_usuario: int = 1  # ID real del usuario/vendedor (para CREAR_EVENTO)
    correo_usuario: str = ""  # email del usuario/vendedor (desde orquestador)
    agendar_sucursal: int = 0
    id_prospecto: int = 0  # mismo que session_id del orquestador
    session_id: int = 0


def _validate_context(context: Dict[str, Any]) -> None:
    """
    Valida que el contexto tenga los parámetros requeridos.
    
    Args:
        context: Contexto con configuración del bot
    
    Raises:
        ValueError: Si faltan parámetros requeridos
    """
    config_data = context.get("config", {})
    required_keys = ["id_empresa"]
    missing = [k for k in required_keys if k not in config_data or config_data[k] is None]
    
    if missing:
        raise ValueError(f"Context missing required keys in config: {missing}")
    
    logger.debug(f"[AGENT] Context validated: id_empresa={config_data.get('id_empresa')}")


def _get_agent(config: Dict[str, Any]):
    """
    Crea el agente con la API moderna de LangChain 1.2+.
    
    El agente se recrea en cada llamada para tener la configuración actualizada
    (personalidad, etc.) del orquestador.
    
    Args:
        config: Diccionario con configuración del agente (personalidad, etc.)
    
    Returns:
        Agente configurado con tools y checkpointer
    """
    logger.debug(f"[AGENT] Creando agente con LangChain 1.2+ API")
    
    # Inicializar modelo
    model = init_chat_model(
        f"openai:{app_config.OPENAI_MODEL}",
        api_key=app_config.OPENAI_API_KEY,
        temperature=app_config.OPENAI_TEMPERATURE,
        max_tokens=app_config.MAX_TOKENS,
        timeout=app_config.OPENAI_TIMEOUT,
    )
    
    # Construir system prompt usando template Jinja2
    # TODO: Pasar historial real cuando se implemente límite de memoria (5 turnos)
    system_prompt = build_citas_system_prompt(
        config=config,
        history=None
    )
    
    # Crear agente con API moderna
    agent = create_agent(
        model=model,
        tools=AGENT_TOOLS,
        system_prompt=system_prompt,
        checkpointer=_checkpointer
    )
    
    logger.debug(f"[AGENT] Agente creado - Tools: {len(AGENT_TOOLS)}, Checkpointer: InMemorySaver")
    
    return agent


def _prepare_agent_context(context: Dict[str, Any], session_id: int) -> AgentContext:
    """
    Prepara el contexto runtime para inyectar a las tools del agente.
    
    Usa los valores que vienen del orquestador. Si no vienen, deja que el dataclass
    use sus defaults.
    
    Args:
        context: Contexto del orquestador
        session_id: ID de sesión (int, unificado con orquestador)
    
    Returns:
        AgentContext configurado
    """
    config_data = context.get("config", {})
    
    # id_empresa ya está validado, usar directamente
    context_params = {
        "id_empresa": config_data["id_empresa"],
        "session_id": session_id,
        "id_prospecto": session_id,
    }
    
    # Solo agregar valores que vienen del orquestador (si existen)
    if "duracion_cita_minutos" in config_data and config_data["duracion_cita_minutos"] is not None:
        context_params["duracion_cita_minutos"] = config_data["duracion_cita_minutos"]
    
    if "slots" in config_data and config_data["slots"] is not None:
        context_params["slots"] = config_data["slots"]
    
    # agendar_usuario viene como bool del orquestador, convertir a int (para ScheduleValidator y payload CREAR_EVENTO)
    if "agendar_usuario" in config_data and config_data["agendar_usuario"] is not None:
        agendar_usuario = config_data["agendar_usuario"]
        if isinstance(agendar_usuario, bool):
            context_params["agendar_usuario"] = 1 if agendar_usuario else 0
        elif isinstance(agendar_usuario, int):
            context_params["agendar_usuario"] = agendar_usuario

    # id_usuario: ID real del usuario/vendedor (para CREAR_EVENTO en ws_calendario)
    if "id_usuario" in config_data and config_data["id_usuario"] is not None:
        context_params["id_usuario"] = int(config_data["id_usuario"])

    # correo_usuario: email del vendedor (para CREAR_EVENTO)
    if "correo_usuario" in config_data and config_data["correo_usuario"] is not None:
        context_params["correo_usuario"] = str(config_data["correo_usuario"]).strip()

    # agendar_sucursal: bool o int → int
    if "agendar_sucursal" in config_data and config_data["agendar_sucursal"] is not None:
        agendar_sucursal = config_data["agendar_sucursal"]
        if isinstance(agendar_sucursal, bool):
            context_params["agendar_sucursal"] = 1 if agendar_sucursal else 0
        elif isinstance(agendar_sucursal, int):
            context_params["agendar_sucursal"] = agendar_sucursal

    return AgentContext(**context_params)


async def process_cita_message(
    message: str,
    session_id: int,
    context: Dict[str, Any]
) -> str:
    """
    Procesa un mensaje del cliente sobre citas/reuniones usando LangChain 1.2+ Agent.
    
    El agente tiene acceso a tools internas:
    - check_availability: Consulta horarios disponibles
    - create_booking: Crea cita/evento con validación real
    
    La memoria es automática gracias al checkpointer (InMemorySaver).
    
    Args:
        message: Mensaje del cliente
        session_id: ID de sesión (int, unificado con orquestador)
        context: Contexto adicional (config del bot, id_empresa, etc.)
    
    Returns:
        Respuesta del agente especializado
    """
    # Validación de entrada
    if not message or not message.strip():
        return "No recibí tu mensaje. ¿Podrías repetirlo?"
    
    if session_id is None or session_id < 0:
        raise ValueError("session_id es requerido (entero no negativo)")
    
    # Registrar request (Prometheus labels requieren str)
    chat_requests_total.labels(session_id=str(session_id)).inc()
    
    # Validar contexto
    try:
        _validate_context(context)
    except ValueError as e:
        logger.error(f"[AGENT] Error de contexto: {e}")
        record_chat_error("context_error")
        return f"Error de configuración: {str(e)}"
    
    config_data = context.get("config", {})
    cita_config = CitaConfig(**config_data)
    
    if "personalidad" not in config_data or not config_data.get("personalidad"):
        config_data["personalidad"] = cita_config.personalidad or "amable, profesional y eficiente"
    
    try:
        agent = _get_agent(config_data)
    except Exception as e:
        logger.error(f"[AGENT] Error creando agent: {e}", exc_info=True)
        record_chat_error("agent_creation_error")
        return "Disculpa, tuve un problema de configuración. ¿Podrías intentar nuevamente?"
    
    agent_context = _prepare_agent_context(context, session_id)
    
    # LangGraph checkpointer usa thread_id como str
    config = {
        "configurable": {
            "thread_id": str(session_id)
        }
    }
    try:
        logger.debug(f"[AGENT] Invocando agent - Session: {session_id}, Message: {message[:100]}...")
        
        with track_chat_response():
            with track_llm_call():
                result = await agent.ainvoke(
                    {
                        "messages": [
                            {"role": "user", "content": message}
                        ]
                    },
                    config=config,
                    context=agent_context
                )
        
        messages = result.get("messages", [])
        if messages:
            last_message = messages[-1]
            response_text = last_message.content if hasattr(last_message, 'content') else str(last_message)
        else:
            response_text = "Lo siento, no pude procesar tu solicitud."
        
        logger.debug(f"[AGENT] Respuesta generada: {response_text[:200]}...")
    
    except Exception as e:
        logger.error(f"[AGENT] Error al ejecutar agent: {e}", exc_info=True)
        record_chat_error("agent_execution_error")
        return "Disculpa, tuve un problema al procesar tu mensaje. ¿Podrías intentar nuevamente?"
    
    return response_text
