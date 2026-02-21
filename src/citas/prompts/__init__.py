"""
Prompts del agente de citas. Builder del system prompt.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, select_autoescape

try:
    from .. import config as app_config
    from ..logger import get_logger
    from ..services.contexto_negocio import fetch_contexto_negocio
    from ..services.horario_reuniones import fetch_horario_reuniones
    from ..services.productos_servicios_citas import fetch_nombres_productos_servicios, format_nombres_para_prompt
except ImportError:
    from citas import config as app_config
    from citas.logger import get_logger
    from citas.services.contexto_negocio import fetch_contexto_negocio
    from citas.services.horario_reuniones import fetch_horario_reuniones
    from citas.services.productos_servicios_citas import fetch_nombres_productos_servicios, format_nombres_para_prompt

logger = get_logger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent
_ZONA_PERU = ZoneInfo(app_config.TIMEZONE)

_DIAS_ESPANOL = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES_ESPANOL = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

_DEFAULTS: Dict[str, Any] = {
    "personalidad": "amable, profesional y eficiente",
}

_jinja_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(disabled_extensions=()),
)
_citas_template = _jinja_env.get_template("citas_system.j2")


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


async def build_citas_system_prompt(
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
    variables = _apply_defaults(config)

    # Fecha y hora actual en Perú (para que el agente sepa "hoy" y "mañana")
    now = _now_peru()
    variables["fecha_iso"] = variables.get("fecha_iso") or now.strftime("%Y-%m-%d")
    variables["fecha_formateada"] = variables.get("fecha_formateada") or now.strftime("%d/%m/%Y")
    variables["hora_actual"] = now.strftime("%I:%M %p")
    dia_nombre = _DIAS_ESPANOL[now.weekday()]
    mes_nombre = _MESES_ESPANOL[now.month - 1]
    variables["fecha_completa"] = f"{now.day} de {mes_nombre} de {now.year} es {dia_nombre}"
    logger.info(
        "[AGENT] Fecha usada en prompt - Hoy: %s, Hora: %s, Para API: %s",
        variables["fecha_completa"],
        variables["hora_actual"],
        variables["fecha_iso"],
    )

    # Cargar horario, productos/servicios y contexto de negocio en paralelo
    id_empresa = config.get("id_empresa")
    results = await asyncio.gather(
        fetch_horario_reuniones(id_empresa),
        fetch_nombres_productos_servicios(id_empresa),
        fetch_contexto_negocio(id_empresa),
        return_exceptions=True,
    )

    horario_atencion = results[0] if not isinstance(results[0], Exception) else "No hay horario cargado."
    prods_servs = results[1] if not isinstance(results[1], Exception) else ([], [])
    nombres_productos, nombres_servicios = prods_servs
    contexto_negocio = results[2] if not isinstance(results[2], Exception) else None

    variables["horario_atencion"] = horario_atencion
    variables["nombres_productos"] = nombres_productos
    variables["nombres_servicios"] = nombres_servicios
    variables["lista_productos_servicios"] = format_nombres_para_prompt(nombres_productos, nombres_servicios)
    variables["contexto_negocio"] = contexto_negocio

    # Agregar historial
    variables["history"] = history or []
    variables["has_history"] = bool(history)

    return _citas_template.render(**variables)


__all__ = ["build_citas_system_prompt"]
