"""
Productos y servicios para citas: fetch desde ws_informacion_ia.php.
Usa OBTENER_PRODUCTOS_CITAS y OBTENER_SERVICIOS_CITAS.
Devuelve solo nombres (máx 10 de cada) para inyectar en el system prompt.
"""

import asyncio
from typing import Any, List, Optional, Tuple

import httpx

try:
    from .. import config as app_config
    from ..logger import get_logger
    from .http_client import post_with_retry
except ImportError:
    from citas import config as app_config
    from citas.logger import get_logger
    from citas.services.http_client import post_with_retry

logger = get_logger(__name__)

_MAX_PRODUCTOS = 10
_MAX_SERVICIOS = 10


async def _fetch_nombres(cod_ope: str, id_empresa: Any, max_items: int, response_key: str) -> List[str]:
    """
    Obtiene una lista de la API y extrae solo los nombres.

    Args:
        cod_ope: OBTENER_PRODUCTOS_CITAS o OBTENER_SERVICIOS_CITAS
        id_empresa: ID de la empresa
        max_items: Máximo de ítems a retornar
        response_key: Clave en la respuesta ("productos" o "servicios")

    Returns:
        Lista de nombres (strings)
    """
    if id_empresa is None or id_empresa == "":
        return []

    payload = {
        "codOpe": cod_ope,
        "id_empresa": id_empresa,
    }
    try:
        logger.debug("[PRODUCTOS_SERVICIOS] POST %s - codOpe=%s", app_config.API_INFORMACION_URL, cod_ope)
        data = await post_with_retry(app_config.API_INFORMACION_URL, json=payload)

        if not data.get("success"):
            logger.warning("[PRODUCTOS_SERVICIOS] API no success para %s: %s", cod_ope, data.get("error"))
            return []

        items = data.get(response_key) or data.get("items") or []
        nombres = []
        for item in items[:max_items]:
            if isinstance(item, dict) and item.get("nombre"):
                nombres.append(str(item["nombre"]).strip())
            elif isinstance(item, str):
                nombres.append(item.strip())
        return nombres

    except httpx.TimeoutException:
        logger.warning("[PRODUCTOS_SERVICIOS] Timeout al obtener %s", cod_ope)
        return []
    except httpx.RequestError as e:
        logger.warning("[PRODUCTOS_SERVICIOS] Error al obtener %s: %s", cod_ope, e)
        return []
    except Exception as e:
        logger.warning("[PRODUCTOS_SERVICIOS] Error inesperado %s: %s", cod_ope, e)
        return []


async def fetch_nombres_productos_servicios(id_empresa: Optional[Any]) -> Tuple[List[str], List[str]]:
    """
    Obtiene listas de nombres de productos y servicios (máx 10 de cada) en paralelo.

    Args:
        id_empresa: ID de la empresa. Si es None, retorna listas vacías.

    Returns:
        Tupla (nombres_productos, nombres_servicios)
    """
    if id_empresa is None or id_empresa == "":
        return [], []

    results = await asyncio.gather(
        _fetch_nombres("OBTENER_PRODUCTOS_CITAS", id_empresa, _MAX_PRODUCTOS, "productos"),
        _fetch_nombres("OBTENER_SERVICIOS_CITAS", id_empresa, _MAX_SERVICIOS, "servicios"),
        return_exceptions=True,
    )
    nombres_productos = results[0] if not isinstance(results[0], Exception) else []
    nombres_servicios = results[1] if not isinstance(results[1], Exception) else []

    logger.info("[PRODUCTOS_SERVICIOS] Respuesta recibida id_empresa=%s: %s productos, %s servicios", id_empresa, len(nombres_productos), len(nombres_servicios))
    return nombres_productos, nombres_servicios


def format_nombres_para_prompt(nombres_productos: List[str], nombres_servicios: List[str]) -> str:
    """
    Formatea las listas para inyectar en el system prompt.
    """
    lineas = []
    if nombres_productos:
        lineas.append("Productos: " + ", ".join(nombres_productos))
    else:
        lineas.append("Productos: (ninguno cargado)")
    if nombres_servicios:
        lineas.append("Servicios: " + ", ".join(nombres_servicios))
    else:
        lineas.append("Servicios: (ninguno cargado)")
    return "\n".join(lineas)


__all__ = ["fetch_nombres_productos_servicios", "format_nombres_para_prompt"]
