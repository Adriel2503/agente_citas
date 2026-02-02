"""
Prompts del agente de citas. Builder del system prompt.
"""

from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from .. import config as app_config
    from ..services.horario_reuniones import fetch_horario_reuniones
except ImportError:
    from citas import config as app_config
    from citas.services.horario_reuniones import fetch_horario_reuniones

_TEMPLATES_DIR = Path(__file__).resolve().parent
_ZONA_PERU = ZoneInfo(app_config.TIMEZONE)

_DEFAULTS: Dict[str, Any] = {
    "personalidad": "amable, profesional y eficiente",
}


def _now_peru() -> datetime:
    """Fecha y hora actual en Perú (America/Lima)."""
    return datetime.now(_ZONA_PERU)


def _apply_defaults(config: Dict[str, Any]) -> Dict[str, Any]:
    """Aplica valores por defecto a la configuración."""
    out = dict(_DEFAULTS)
    for k, v in config.items():
        if v is not None and v != "" and v != []:
            out[k] = v
    return out


def build_citas_system_prompt(
    config: Dict[str, Any],
    history: List[Dict] = None
) -> str:
    """
    Construye el system prompt del agente de citas.
    
    Args:
        config: Diccionario con id_empresa, personalidad, etc.
        history: Lista de turnos previos [{"user": "...", "response": "..."}]
    
    Returns:
        System prompt formateado con historial.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(disabled_extensions=()),
    )
    template = env.get_template("citas_system.j2")
    
    variables = _apply_defaults(config)
    
    # Fecha y hora actual en Perú (para que el agente sepa "hoy" y "mañana")
    now = _now_peru()
    variables["fecha_iso"] = variables.get("fecha_iso") or now.strftime("%Y-%m-%d")
    variables["fecha_formateada"] = variables.get("fecha_formateada") or now.strftime("%d/%m/%Y")
    variables["hora_actual"] = now.strftime("%I:%M %p")
    
    # Horario de atención (OBTENER_HORARIO_REUNIONES) para inyectar en el prompt
    id_empresa = config.get("id_empresa")
    variables["horario_atencion"] = fetch_horario_reuniones(id_empresa)
    
    # Agregar historial
    variables["history"] = history or []
    variables["has_history"] = bool(history)
    
    return template.render(**variables)


__all__ = ["build_citas_system_prompt"]
