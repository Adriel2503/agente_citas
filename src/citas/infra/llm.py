"""
Singleton LLM y checkpointer LangGraph para el agente de citas.

Inicialización lazy del modelo (get_model) igual que get_client en http_client.py.
El checkpointer se crea al importar el módulo (síncrono, seguro en asyncio).

C1: close_checkpointer() es actualmente un no-op; en C1 se reemplazará por
    la lógica de init/close de AsyncRedisSaver (ver PENDIENTES.md C1).
"""

from langchain.chat_models import init_chat_model
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from .. import config as app_config
from ..logger import get_logger

logger = get_logger(__name__)

# Checkpointer LangGraph: creado una sola vez al importar.
# JsonPlusSerializer usa string tuples — NO importa CitaStructuredResponse,
# por lo que infra/ → agent/ no existe como dependencia.
_checkpointer = InMemorySaver(
    serde=JsonPlusSerializer(
        allowed_json_modules=[("citas", "agent", "content", "CitaStructuredResponse")]
    )
)

# Modelo LLM: singleton compartido por todas las empresas.
# init_chat_model es síncrono; no hay riesgo de race condition en asyncio single-thread.
_model = None


def get_model():
    """
    Retorna el modelo LLM singleton, creándolo en la primera llamada.
    init_chat_model es síncrono → no hay race condition en asyncio single-thread.
    Compartido por todas las empresas: la config viene de variables de entorno.
    """
    global _model
    if _model is None:
        logger.info("[LLM] Inicializando modelo LLM: %s", app_config.OPENAI_MODEL)
        _model = init_chat_model(
            f"openai:{app_config.OPENAI_MODEL}",
            api_key=app_config.OPENAI_API_KEY,
            temperature=app_config.OPENAI_TEMPERATURE,
            max_tokens=app_config.MAX_TOKENS,
            timeout=app_config.OPENAI_TIMEOUT,
        )
    return _model


def get_checkpointer():
    """Retorna el checkpointer LangGraph singleton (InMemorySaver)."""
    return _checkpointer


async def close_checkpointer() -> None:
    """
    Cierra el checkpointer al apagar la app.
    Actualmente no-op (InMemorySaver no requiere cierre).
    En C1: reemplazar por la lógica AsyncRedisSaver de PENDIENTES.md.
    Llamar desde main.py lifespan al implementar C1.
    """


__all__ = ["get_model", "get_checkpointer", "close_checkpointer"]
