"""
Modelos Pydantic para request/response del agente de citas.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request para el endpoint de chat."""
    
    message: str = Field(..., description="Mensaje del cliente")
    session_id: int = Field(..., description="ID de sesión (int, unificado con orquestador)")
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Contexto adicional (configuración del bot, etc.)"
    )


class ChatResponse(BaseModel):
    """Response del endpoint de chat."""
    
    reply: str = Field(..., description="Respuesta del agente")
    session_id: int = Field(..., description="ID de sesión (int, unificado con orquestador)")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Metadata adicional (intent detectado, acción realizada, etc.)"
    )


class CitaConfig(BaseModel):
    """
    Configuración mínima del agente de citas.

    Se instancia con CitaConfig(**config_data) en agent.py. Pydantic ignora
    campos extra (id_empresa, duracion_cita_minutos, etc.) que vienen del
    orquestador.

    IMPORTANTE: Si en el futuro se añaden campos obligatorios (sin default),
    asegurarse de que config_data los incluya o que _validate_context los
    valide. De lo contrario CitaConfig(**config_data) lanzará ValidationError.
    """

    personalidad: str = Field(
        default="amable, profesional y eficiente",
        description="Personalidad del agente"
    )
