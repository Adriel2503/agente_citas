"""
Búsqueda de productos y servicios desde ws_informacion_ia.php.
Usa codOpe: BUSCAR_PRODUCTOS_SERVICIOS_CITAS
"""

import json
import re
from typing import Any, Dict, List, Optional

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


def _clean_description(desc: Optional[str], max_chars: int = 120) -> str:
    """Limpia HTML y trunca la descripción."""
    if not desc or not str(desc).strip():
        return "-"
    text = str(desc).strip()
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = re.sub(r"\s+", " ", text).strip()
    return (text[:max_chars] + "...") if len(text) > max_chars else text


def _format_precio(precio: Any) -> str:
    if precio is None or precio == "":
        return "-"
    try:
        return f"S/. {float(precio):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _format_precio_linea(precio_str: str, es_servicio: bool, unidad: str) -> str:
    """Línea de precio: solo monto para servicio; monto + unidad para producto."""
    if es_servicio:
        return f"- *Precio:* {precio_str}"
    return f"- *Precio:* {precio_str} por {unidad}"


def _format_item(p: Dict[str, Any]) -> List[str]:
    """
    Formato único para Producto y Servicio:
    - Producto: Precio por unidad (nombre_unidad de API).
    - Servicio: Solo precio, sin "por" ni unidad.
    Sin SKU en ninguno.
    """
    nombre = (p.get("nombre") or "-").strip()
    precio_str = _format_precio(p.get("precio_unitario"))
    categoria = (p.get("nombre_categoria") or "-").strip()
    descripcion = _clean_description(p.get("descripcion"))

    tipo = (p.get("nombre_tipo_producto") or "").strip().lower()
    es_servicio = tipo == "servicio"
    unidad = (p.get("nombre_unidad") or "unidad").strip().lower() if not es_servicio else ""

    linea_precio = _format_precio_linea(precio_str, es_servicio, unidad)

    lineas = [
        f"*{nombre}*",
        linea_precio,
        f"- *Categoría:* {categoria}",
        f"- *Descripción:* {descripcion}",
        "",
    ]
    return lineas


def format_productos_para_respuesta(productos: List[Dict[str, Any]]) -> str:
    """Formatea la lista de productos/servicios para la respuesta de la tool."""
    if not productos:
        return "No se encontraron resultados."

    lineas = []
    for p in productos:
        lineas.extend(_format_item(p))
    return "\n".join(lineas).strip()


async def buscar_productos_servicios(
    id_empresa: int,
    busqueda: str,
    limite: int = 10,
    log_search_apis: bool = False,
) -> Dict[str, Any]:
    """
    Busca productos y servicios por término.

    Args:
        id_empresa: ID de la empresa
        busqueda: Término de búsqueda
        limite: Cantidad máxima de resultados (default 10)
        log_search_apis: Si True, registra API, URL, payload y respuesta en info

    Returns:
        Dict con success, productos (lista), error si aplica
    """
    if not busqueda or not str(busqueda).strip():
        return {"success": False, "productos": [], "error": "El término de búsqueda no puede estar vacío"}

    logger.debug(
        "[BUSQUEDA] Parámetros: id_empresa=%s, busqueda=%s, limite=%s",
        id_empresa, busqueda.strip() if busqueda else "", limite,
    )
    payload = {
        "codOpe": "BUSCAR_PRODUCTOS_SERVICIOS_CITAS",
        "id_empresa": id_empresa,
        "busqueda": str(busqueda).strip(),
        "limite": limite,
    }
    if log_search_apis:
        logger.info("[search_productos_servicios] API: ws_informacion_ia.php - BUSCAR_PRODUCTOS_SERVICIOS_CITAS")
        logger.info("  URL: %s", app_config.API_INFORMACION_URL)
        logger.info("  Enviado: %s", json.dumps(payload, ensure_ascii=False))
    logger.debug(
        "[BUSQUEDA] POST %s - %s",
        app_config.API_INFORMACION_URL,
        json.dumps(payload, ensure_ascii=False),
    )

    try:
        data = await post_with_retry(app_config.API_INFORMACION_URL, json=payload)

        if log_search_apis:
            logger.info("  Respuesta: %s", json.dumps(data, ensure_ascii=False))
        if not data.get("success"):
            error_msg = data.get("error") or data.get("message") or "Error desconocido"
            logger.warning("[BUSQUEDA] API no success: %s", error_msg)
            return {"success": False, "productos": [], "error": error_msg}

        productos = data.get("productos", [])
        return {"success": True, "productos": productos, "error": None}

    except httpx.TimeoutException:
        logger.warning("[BUSQUEDA] Timeout al buscar productos")
        return {"success": False, "productos": [], "error": "La búsqueda tardó demasiado. Intenta de nuevo."}
    except httpx.RequestError as e:
        logger.warning("[BUSQUEDA] Error de conexión: %s", e)
        return {"success": False, "productos": [], "error": str(e)}
    except Exception as e:
        logger.exception("[BUSQUEDA] Error inesperado: %s", e)
        return {"success": False, "productos": [], "error": str(e)}


__all__ = ["buscar_productos_servicios", "format_productos_para_respuesta"]
