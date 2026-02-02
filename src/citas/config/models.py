"""
Modelos Pydantic para request/response del agente de citas.
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Request para el endpoint de chat."""
    
    message: str = Field(..., description="Mensaje del cliente")
    session_id: str = Field(..., description="ID de sesión único para la conversación")
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description="Contexto adicional (configuración del bot, etc.)"
    )


class ChatResponse(BaseModel):
    """Response del endpoint de chat."""
    
    reply: str = Field(..., description="Respuesta del agente")
    session_id: str = Field(..., description="ID de sesión")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Metadata adicional (intent detectado, acción realizada, etc.)"
    )


class CitaConfig(BaseModel):
    """Configuración mínima del agente de citas."""
    
    personalidad: str = Field(
        default="amable, profesional y eficiente",
        description="Personalidad del agente"
    )
