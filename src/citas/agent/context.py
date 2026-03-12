"""
Modelo de contexto runtime y funciones de validación/preparación.
"""

from dataclasses import dataclass
from typing import Any

from ..logger import get_logger

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


def _validate_context(config: dict[str, Any]) -> None:
    """
    Valida que la config tenga los parámetros requeridos.

    Args:
        config: Config directa del bot (sin wrapper "context")

    Raises:
        ValueError: Si faltan parámetros requeridos
    """
    if "id_empresa" not in config or config["id_empresa"] is None:
        raise ValueError("Config missing required key: id_empresa")

    logger.debug("[AGENT] Config validated: id_empresa=%s", config["id_empresa"])


def _prepare_agent_context(config_data: dict[str, Any], session_id: int) -> AgentContext:
    """
    Prepara el contexto runtime para inyectar a las tools del agente.

    Recibe el dict de config ya aplanado (sin wrapper "context").
    Solo incluye en context_params los campos que el orquestador envió explícitamente
    y con valor no-None. Los campos ausentes quedan con el default del dataclass.

    Args:
        config_data: Config del orquestador con id_empresa y parámetros del agente.
        session_id: ID de sesión (int, unificado con orquestador).

    Returns:
        AgentContext configurado con los valores del orquestador o los defaults del dataclass.
    """
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
        try:
            context_params["usuario_id"] = int(config_data["usuario_id"])
        except (ValueError, TypeError):
            logger.warning("[CONTEXT] usuario_id inválido: %r — ignorando", config_data["usuario_id"])

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
