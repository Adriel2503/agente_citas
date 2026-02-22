"""
Modelos de configuración del agente de citas.
"""

from pydantic import BaseModel, Field


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
