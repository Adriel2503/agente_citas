"""
Lógica del agente especializado en citas usando LangChain 1.2+ API moderna.
Versión mejorada con logging, métricas, configuración centralizada y memoria automática.
"""

import asyncio
import re
from typing import Any, Dict, List, Tuple, Union
from dataclasses import dataclass

from cachetools import TTLCache
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

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


class CitaStructuredResponse(BaseModel):
    """Schema para response_format del agente. Siempre devuelve reply; url opcional."""

    reply: str
    url: str | None = None


# Checkpointer global para memoria automática
_checkpointer = InMemorySaver()

# Un lock por session_id para serializar requests concurrentes de la misma sesión.
# Evita que dos mensajes del mismo usuario (doble-click / reintento) ejecuten
# agent.ainvoke sobre el mismo thread_id del checkpointer en paralelo.
# Crece con cada sesión nueva; se limpia cuando supera _SESSION_LOCKS_CLEANUP_THRESHOLD.
_session_locks: Dict[int, asyncio.Lock] = {}
_SESSION_LOCKS_CLEANUP_THRESHOLD = 500  # multiempresa: muchas sesiones; limpieza periódica

# Cache de agentes compilados: clave = (id_empresa, personalidad).
# TTL acoplado al cache de horarios: cuando el horario caduca, el agente también,
# garantizando que el próximo mensaje recibe un prompt con datos frescos.
_agent_cache: TTLCache = TTLCache(
    maxsize=100,
    ttl=app_config.SCHEDULE_CACHE_TTL_MINUTES * 60,
)
# Un lock por cache_key para evitar thundering herd al crear el agente por primera vez.
# Crece con cada (id_empresa, personalidad) nuevo; se limpia cuando supera _LOCKS_CLEANUP_THRESHOLD.
_agent_cache_locks: Dict[Tuple, asyncio.Lock] = {}
_LOCKS_CLEANUP_THRESHOLD = 150  # 1.5x cache maxsize; si se supera, se eliminan locks huérfanos

_IMAGE_URL_RE = re.compile(
    r"https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?",
    re.IGNORECASE,
)
_MAX_IMAGES = 10  # límite de OpenAI Vision


def _build_content(message: str) -> Union[str, List[dict]]:
    """
    Devuelve string si no hay URLs de imagen (Caso 1),
    o lista de bloques OpenAI Vision si las hay (Casos 2-5).

    Casos:
      1. Solo texto         -> str
      2. Solo 1 URL         -> [{image_url}]
      3. Texto + 1 URL      -> [{text}, {image_url}]
      4. Solo N URLs        -> [{image_url}, ...]
      5. Texto + N URLs     -> [{text}, {image_url}, ...]
    """
    urls = _IMAGE_URL_RE.findall(message)
    if not urls:
        return message  # Caso 1: sin cambio

    urls = urls[:_MAX_IMAGES]
    text = _IMAGE_URL_RE.sub("", message).strip()

    blocks: List[dict] = []
    if text:
        blocks.append({"type": "text", "text": text})
    for url in urls:
        blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


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
    usuario_id: int = 1  # ID real del usuario/vendedor (para CREAR_EVENTO)
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
    
    logger.debug("[AGENT] Context validated: id_empresa=%s", config_data.get("id_empresa"))


async def _cleanup_stale_agent_locks(current_cache_key: Tuple) -> None:
    """
    Elimina locks de _agent_cache_locks cuyas claves ya no están en _agent_cache.
    Solo se ejecuta si el dict supera _LOCKS_CLEANUP_THRESHOLD.
    Evita crecimiento indefinido cuando hay muchas empresas/personalidades distintas.
    """
    if len(_agent_cache_locks) <= _LOCKS_CLEANUP_THRESHOLD:
        return
    removed = 0
    for key in list(_agent_cache_locks.keys()):
        if key == current_cache_key:
            continue
        if key not in _agent_cache:
            lock = _agent_cache_locks.get(key)
            if lock is None:
                continue
            try:
                await asyncio.wait_for(lock.acquire(), timeout=0)
            except asyncio.TimeoutError:
                pass  # Lock en uso, no eliminar
            else:
                del _agent_cache_locks[key]
                lock.release()
                removed += 1
    if removed:
        logger.debug("[AGENT] Limpieza de locks huérfanos: %s eliminados", removed)


async def _cleanup_stale_session_locks(current_session_id: int) -> None:
    """
    Elimina locks de _session_locks que no están en uso.
    Solo se ejecuta si el dict supera _SESSION_LOCKS_CLEANUP_THRESHOLD.
    En multiempresa muchas sesiones acumulan; esto evita crecimiento indefinido.
    """
    if len(_session_locks) <= _SESSION_LOCKS_CLEANUP_THRESHOLD:
        return
    removed = 0
    for sid in list(_session_locks.keys()):
        if sid == current_session_id:
            continue
        lock = _session_locks.get(sid)
        if lock is None:
            continue
        try:
            await asyncio.wait_for(lock.acquire(), timeout=0)
        except asyncio.TimeoutError:
            pass  # Lock en uso, no eliminar
        else:
            del _session_locks[sid]
            lock.release()
            removed += 1
    if removed:
        logger.debug("[AGENT] Limpieza de session locks: %s eliminados", removed)


async def _get_agent(config: Dict[str, Any]):
    """
    Devuelve el agente compilado para la combinación (id_empresa, personalidad).

    Utiliza TTLCache para evitar recrear el cliente OpenAI, las 2 HTTP calls
    del prompt y la compilación del grafo LangGraph en cada mensaje. El TTL
    está acoplado a SCHEDULE_CACHE_TTL_MINUTES para que los datos del prompt
    (horario, productos) se refresquen al mismo tiempo que el cache de horarios.

    Incluye doble verificación con asyncio.Lock por cache_key para serializar
    la primera creación cuando múltiples sesiones de la misma empresa llegan
    concurrentemente (thundering herd).

    Args:
        config: Diccionario con configuración del agente (personalidad, etc.)

    Returns:
        Agente configurado con tools y checkpointer
    """
    cache_key: Tuple = (config.get("id_empresa"), config.get("personalidad", ""))

    # Fast path: cache hit (sin await, atómico en asyncio single-thread)
    if cache_key in _agent_cache:
        logger.debug("[AGENT] Cache hit - id_empresa=%s", cache_key[0])
        return _agent_cache[cache_key]

    # Slow path: serializar creación para evitar thundering herd
    await _cleanup_stale_agent_locks(cache_key)
    lock = _agent_cache_locks.setdefault(cache_key, asyncio.Lock())
    async with lock:
        # Double-check tras adquirir el lock (otra coroutine pudo haberlo creado)
        if cache_key in _agent_cache:
            logger.debug("[AGENT] Cache hit tras lock - id_empresa=%s", cache_key[0])
            return _agent_cache[cache_key]

        logger.debug("[AGENT] Creando agente con LangChain 1.2+ API - id_empresa=%s", cache_key[0])

        # Inicializar modelo
        model = init_chat_model(
            f"openai:{app_config.OPENAI_MODEL}",
            api_key=app_config.OPENAI_API_KEY,
            temperature=app_config.OPENAI_TEMPERATURE,
            max_tokens=app_config.MAX_TOKENS,
            timeout=app_config.OPENAI_TIMEOUT,
        )

        # Construir system prompt usando template Jinja2 (async: carga horario y productos en paralelo)
        system_prompt = await build_citas_system_prompt(
            config=config,
            history=None,
        )

        # Crear agente con API moderna (response_format: reply + url opcional)
        agent = create_agent(
            model=model,
            tools=AGENT_TOOLS,
            system_prompt=system_prompt,
            checkpointer=_checkpointer,
            response_format=CitaStructuredResponse,
        )

        _agent_cache[cache_key] = agent
        logger.debug(
            "[AGENT] Agente cacheado - id_empresa=%s, Tools: %s, TTL: %ss",
            cache_key[0],
            len(AGENT_TOOLS),
            app_config.SCHEDULE_CACHE_TTL_MINUTES * 60,
        )
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

    # usuario_id: ID real del usuario/vendedor (para CREAR_EVENTO en ws_calendario)
    if "usuario_id" in config_data and config_data["usuario_id"] is not None:
        context_params["usuario_id"] = int(config_data["usuario_id"])

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
) -> tuple[str, str | None]:
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
        Tupla (reply, url). url es None cuando no hay medio que adjuntar.
    """
    # Validaciones rápidas FUERA del lock (no tocan estado compartido)
    if not message or not message.strip():
        return ("No recibí tu mensaje. ¿Podrías repetirlo?", None)

    if session_id is None or session_id < 0:
        raise ValueError("session_id es requerido (entero no negativo)")

    # Registrar request con label de baja cardinalidad (por empresa, no por sesión)
    _empresa_id = str((context.get("config") or {}).get("id_empresa", "unknown"))
    chat_requests_total.labels(empresa_id=_empresa_id).inc()

    # Serializar requests concurrentes del mismo usuario para evitar condiciones
    # de carrera sobre el mismo thread_id del checkpointer (InMemorySaver).
    await _cleanup_stale_session_locks(session_id)
    lock = _session_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        # Validar contexto
        try:
            _validate_context(context)
        except ValueError as e:
            logger.error("[AGENT] Error de contexto: %s", e)
            record_chat_error("context_error")
            return (f"Error de configuración: {str(e)}", None)

        config_data = dict(context.get("config") or {})
        cita_config = CitaConfig(**config_data)

        if "personalidad" not in config_data or not config_data.get("personalidad"):
            config_data["personalidad"] = cita_config.personalidad or "amable, profesional y eficiente"

        try:
            agent = await _get_agent(config_data)
        except Exception as e:
            logger.error("[AGENT] Error creando agent: %s", e, exc_info=True)
            record_chat_error("agent_creation_error")
            return ("Disculpa, tuve un problema de configuración. ¿Podrías intentar nuevamente?", None)

        agent_context = _prepare_agent_context(context, session_id)

        # LangGraph checkpointer usa thread_id como str
        config = {
            "configurable": {
                "thread_id": str(session_id)
            }
        }
        try:
            logger.debug("[AGENT] Invocando agent - Session: %s, Message: %s...", session_id, message[:100])

            with track_chat_response():
                with track_llm_call():
                    result = await agent.ainvoke(
                        {
                            "messages": [
                                {"role": "user", "content": _build_content(message)}
                            ]
                        },
                        config=config,
                        context=agent_context
                    )

            structured = result.get("structured_response")
            if isinstance(structured, CitaStructuredResponse):
                reply = structured.reply or "Lo siento, no pude procesar tu solicitud."
                url = structured.url if (structured.url and structured.url.strip()) else None
            else:
                messages = result.get("messages", [])
                if messages:
                    last_message = messages[-1]
                    reply = last_message.content if hasattr(last_message, "content") else str(last_message)
                else:
                    reply = "Lo siento, no pude procesar tu solicitud."
                url = None

            logger.debug("[AGENT] Respuesta generada: %s...", (reply[:200], url))

        except Exception as e:
            logger.error("[AGENT] Error al ejecutar agent: %s", e, exc_info=True)
            record_chat_error("agent_execution_error")
            return ("Disculpa, tuve un problema al procesar tu mensaje. ¿Podrías intentar nuevamente?", None)

    return (reply, url)
