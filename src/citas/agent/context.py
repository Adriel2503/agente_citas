"""
Modelo de contexto runtime y función de preparación.
"""

from dataclasses import dataclass
from typing import Any

from ..logger import get_logger
from ..schemas import CitasConfig

logger = get_logger(__name__)


@dataclass
class AgentContext:
    """
    Esquema de contexto runtime para el agente.
    Este contexto se inyecta en las tools que lo necesiten.
    """
    id_empresa: int
    duracion_cita_minutos: int | None = None  # None = no enviado por el orquestador
    slots: int | None = None  # None = no enviado por el orquestador
    agendar_usuario: int = 1  # bandera agendar_usuario (1/0) para ScheduleValidator
    usuario_id: int | None = None  # None = no enviado por el orquestador (requerido para CREAR_EVENTO)
    correo_usuario: str | None = None  # None = no enviado por el orquestador (requerido para CREAR_EVENTO)
    agendar_sucursal: int = 0
    id_prospecto: int = 0  # mismo que session_id del orquestador
    session_id: int = 0


def _prepare_agent_context(config: CitasConfig, session_id: int) -> AgentContext:
    """
    Prepara el contexto runtime para inyectar a las tools del agente.

    Los validators de CitasConfig ya normalizaron bool→int, str→int, strip, etc.
    Solo se incluyen campos con valor no-None; el resto queda con el default del dataclass.

    Args:
        config: CitasConfig validado por Pydantic.
        session_id: ID de sesión (int, unificado con orquestador).

    Returns:
        AgentContext configurado.
    """
    params: dict[str, Any] = {
        "id_empresa": config.id_empresa,
        "session_id": session_id,
        "id_prospecto": session_id,
        "agendar_usuario": config.agendar_usuario,
        "agendar_sucursal": config.agendar_sucursal,
    }

    if config.duracion_cita_minutos is not None:
        params["duracion_cita_minutos"] = config.duracion_cita_minutos

    if config.slots is not None:
        params["slots"] = config.slots

    if config.usuario_id is not None:
        params["usuario_id"] = config.usuario_id

    if config.correo_usuario is not None:
        params["correo_usuario"] = config.correo_usuario

    return AgentContext(**params)
