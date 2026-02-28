"""
Lógica del agente especializado en citas usando LangChain 1.2+ API moderna.
Versión mejorada con logging, métricas, configuración centralizada y memoria automática.
"""

import asyncio
import re
from typing import Any
from dataclasses import dataclass

import openai

from cachetools import TTLCache
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

try:
    from .. import config as app_config
    from ..tool.tools import AGENT_TOOLS
    from ..logger import get_logger
    from ..metrics import track_chat_response, track_llm_call, record_chat_error, chat_requests_total, AGENT_CACHE
    from ..prompts import build_citas_system_prompt
except ImportError:
    from citas import config as app_config
    from citas.tool.tools import AGENT_TOOLS
    from citas.logger import get_logger
    from citas.metrics import track_chat_response, track_llm_call, record_chat_error, chat_requests_total, AGENT_CACHE
    from citas.prompts import build_citas_system_prompt

logger = get_logger(__name__)


class CitaStructuredResponse(BaseModel):
    """Schema para response_format del agente. Siempre devuelve reply; url opcional."""

    reply: str
    url: str | None = None


# Checkpointer global para memoria automática
_checkpointer = InMemorySaver()

# Modelo LLM: singleton compartido por todas las empresas.
# init_chat_model es síncrono; no hay riesgo de race condition en asyncio single-thread.
# Todas las empresas usan el mismo modelo (config desde variables de entorno).
_model = None

# Un lock por session_id para serializar requests concurrentes de la misma sesión.
# Evita que dos mensajes del mismo usuario (doble-click / reintento) ejecuten
# agent.ainvoke sobre el mismo thread_id del checkpointer en paralelo.
# Crece con cada sesión nueva; se limpia cuando supera _SESSION_LOCKS_CLEANUP_THRESHOLD.
_session_locks: dict[int, asyncio.Lock] = {}
_SESSION_LOCKS_CLEANUP_THRESHOLD = 500  # multiempresa: muchas sesiones; limpieza periódica

# Cache de agentes compilados: clave = id_empresa.
# TTL independiente del cache de horarios: el system prompt (contexto negocio, FAQs,
# productos) cambia raramente → TTL largo (default 60 min).
# La validación de horario usa horario_cache directamente, siempre fresca.
_agent_cache: TTLCache = TTLCache(
    maxsize=app_config.AGENT_CACHE_MAXSIZE,
    ttl=app_config.AGENT_CACHE_TTL_MINUTES * 60,
)
# Un lock por cache_key para evitar thundering herd al crear el agente por primera vez.
# Crece con cada id_empresa nuevo; se limpia cuando supera _LOCKS_CLEANUP_THRESHOLD.
_agent_cache_locks: dict[tuple, asyncio.Lock] = {}
_LOCKS_CLEANUP_THRESHOLD = 750  # 1.5x cache maxsize; si se supera, se eliminan locks huérfanos

_IMAGE_URL_RE = re.compile(
    r"https?://\S+\.(?:jpg|jpeg|png|gif|webp)(?:\?\S*)?",
    re.IGNORECASE,
)
_MAX_IMAGES = 10  # límite de OpenAI Vision


def _build_content(message: str) -> str | list[dict]:
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

    blocks: list[dict] = []
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


def _validate_context(context: dict[str, Any]) -> None:
    """
    Valida que el contexto tenga los parámetros requeridos.
    
    Args:
        context: Contexto con configuración del bot
    
    Raises:
        ValueError: Si faltan parámetros requeridos
    """
    config_data: dict[str, Any] = context.get("config", {})
    required_keys = ["id_empresa"]
    missing = [k for k in required_keys if k not in config_data or config_data[k] is None]
    
    if missing:
        raise ValueError(f"Context missing required keys in config: {missing}")
    
    logger.debug("[AGENT] Context validated: id_empresa=%s", config_data.get("id_empresa"))


def _cleanup_stale_agent_locks(current_cache_key: tuple) -> None:
    """
    Elimina locks de _agent_cache_locks cuyas claves ya no están en _agent_cache.
    Solo se ejecuta si el dict supera _LOCKS_CLEANUP_THRESHOLD.
    Evita crecimiento indefinido cuando hay muchas empresas distintas.
    """
    if len(_agent_cache_locks) <= _LOCKS_CLEANUP_THRESHOLD:
        return
    removed = 0
    for key in list(_agent_cache_locks.keys()):
        if key == current_cache_key:
            continue
        if key not in _agent_cache:
            lock = _agent_cache_locks.get(key)
            if lock is not None and not lock.locked():
                del _agent_cache_locks[key]
                removed += 1
    if removed:
        logger.debug("[AGENT] Limpieza de locks huérfanos: %s eliminados", removed)


def _cleanup_stale_session_locks(current_session_id: int) -> None:
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
        if lock is not None and not lock.locked():
            del _session_locks[sid]
            removed += 1
    if removed:
        logger.debug("[AGENT] Limpieza de session locks: %s eliminados", removed)


def _get_model():
    """
    Retorna el modelo LLM singleton, creándolo en la primera llamada.
    init_chat_model es síncrono → no hay race condition en asyncio single-thread.
    Compartido por todas las empresas: la config viene de variables de entorno,
    es idéntica para todos.
    """
    global _model
    if _model is None:
        logger.info("[AGENT] Inicializando modelo LLM: %s", app_config.OPENAI_MODEL)
        _model = init_chat_model(
            f"openai:{app_config.OPENAI_MODEL}",
            api_key=app_config.OPENAI_API_KEY,
            temperature=app_config.OPENAI_TEMPERATURE,
            max_tokens=app_config.MAX_TOKENS,
            timeout=app_config.OPENAI_TIMEOUT,
        )
    return _model


async def _get_agent(config: dict[str, Any]):
    """
    Devuelve el agente compilado para id_empresa.

    Utiliza TTLCache para evitar recrear el cliente OpenAI, las HTTP calls
    del prompt y la compilación del grafo LangGraph en cada mensaje. El TTL
    se gobierna con AGENT_CACHE_TTL_MINUTES (default 60 min), independiente
    del cache de horarios (SCHEDULE_CACHE_TTL_MINUTES).

    Incluye doble verificación con asyncio.Lock por cache_key para serializar
    la primera creación cuando múltiples sesiones de la misma empresa llegan
    concurrentemente (thundering herd).

    Args:
        config: Diccionario con configuración del agente (id_empresa requerido; personalidad, nombre, etc. opcionales).

    Returns:
        Agente configurado con tools y checkpointer
    """
    cache_key: tuple = (config.get("id_empresa"),)

    # Fast path: cache hit (sin await, atómico en asyncio single-thread)
    if cache_key in _agent_cache:
        AGENT_CACHE.labels(result="hit").inc()
        logger.debug("[AGENT] Cache hit - id_empresa=%s", cache_key[0])
        return _agent_cache[cache_key]

    # Slow path: serializar creación para evitar thundering herd
    _cleanup_stale_agent_locks(cache_key)
    lock = _agent_cache_locks.setdefault(cache_key, asyncio.Lock())
    try:
        async with lock:
            # Double-check tras adquirir el lock (otra coroutine pudo haberlo creado)
            if cache_key in _agent_cache:
                AGENT_CACHE.labels(result="hit").inc()
                logger.debug("[AGENT] Cache hit tras lock - id_empresa=%s", cache_key[0])
                return _agent_cache[cache_key]

            AGENT_CACHE.labels(result="miss").inc()
            logger.debug("[AGENT] Creando agente con LangChain 1.2+ API - id_empresa=%s", cache_key[0])

            model = _get_model()

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
                app_config.AGENT_CACHE_TTL_MINUTES * 60,
            )
            return agent
    finally:
        _agent_cache_locks.pop(cache_key, None)


def _prepare_agent_context(context: dict[str, Any], session_id: int) -> AgentContext:
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
    config_data: dict[str, Any] = context.get("config", {})

    # id_empresa ya está validado, usar directamente
    context_params: dict[str, Any] = {
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
    context: dict[str, Any],
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
    _cleanup_stale_session_locks(session_id)
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
        config_data.setdefault("personalidad", "amable, profesional y eficiente")

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
                if structured.reply is None:
                    logger.warning("[AGENT] structured.reply es None - Session: %s", session_id)
                    reply = "No recibí respuesta del asistente, por favor intenta nuevamente."
                elif structured.reply == "":
                    logger.warning("[AGENT] structured.reply es string vacío - Session: %s", session_id)
                    reply = "El asistente envió una respuesta vacía, por favor intenta nuevamente."
                else:
                    reply = structured.reply
                url = structured.url if (structured.url and structured.url.strip()) else None
            else:
                logger.warning("[AGENT] Respuesta fuera de formato estructurado - Session: %s", session_id)
                messages = result.get("messages", [])
                if messages:
                    last_message = messages[-1]
                    reply = last_message.content if hasattr(last_message, "content") else str(last_message)
                    if not reply:
                        logger.warning("[AGENT] last_message.content vacío - Session: %s", session_id)
                        reply = "El asistente respondió en un formato inesperado, por favor intenta nuevamente."
                else:
                    reply = "El asistente respondió en un formato inesperado, por favor intenta nuevamente."
                url = None

            logger.debug("[AGENT] Respuesta generada: %s...", (reply[:200], url))

        except openai.AuthenticationError as e:
            logger.critical("[AGENT][OpenAI-401] API key inválida - Session: %s | %s", session_id, e)
            record_chat_error("openai_auth_error")
            return ("No puedo procesar tu mensaje, la clave de acceso al servicio no es válida.", None)
        except openai.RateLimitError as e:
            logger.warning("[AGENT][OpenAI-429] Rate limit alcanzado - Session: %s | %s", session_id, e)
            record_chat_error("openai_rate_limit")
            return ("Estoy recibiendo demasiadas solicitudes en este momento, por favor intenta en unos segundos.", None)
        except openai.InternalServerError as e:
            logger.error("[AGENT][OpenAI-5xx] Error interno OpenAI - Session: %s | %s", session_id, e)
            record_chat_error("openai_server_error")
            return ("El servicio de inteligencia artificial está presentando problemas, por favor intenta nuevamente.", None)
        except openai.APIConnectionError as e:
            logger.error("[AGENT][OpenAI-conn] Error de conexión con OpenAI - Session: %s | %s", session_id, e)
            record_chat_error("openai_connection_error")
            return ("No pude conectarme al servicio de inteligencia artificial, por favor intenta nuevamente.", None)
        except openai.BadRequestError as e:
            logger.warning("[AGENT][OpenAI-400] Bad request - Session: %s | %s", session_id, e)
            record_chat_error("openai_bad_request")
            return ("Tu mensaje no pudo ser procesado por el servicio, ¿puedes reformularlo?", None)
        except Exception as e:
            logger.error("[AGENT] Error inesperado (%s) - Session: %s | %s", type(e).__name__, session_id, e, exc_info=True)
            record_chat_error("agent_execution_error")
            return ("Disculpa, tuve un problema al procesar tu mensaje. ¿Podrías intentar nuevamente?", None)

    return (reply, url)
