"""
Cliente HTTP compartido para todos los servicios de agent_citas.

Inicialización lazy: el cliente se crea en la primera llamada a get_client()
y se cierra limpiamente en el lifespan del servidor MCP (close_http_client).
Esto permite reutilizar el connection pool entre todas las llamadas a las APIs
de MaravIA (informacion, agendar_reunion, calendario).
"""

from typing import Optional

import httpx

try:
    from .. import config as app_config
except ImportError:
    from citas import config as app_config

_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """Devuelve el cliente HTTP compartido; lo crea en la primera llamada (lazy init)."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=app_config.API_TIMEOUT,
                write=5.0,
                pool=2.0,
            ),
            limits=httpx.Limits(
                max_connections=50,
                max_keepalive_connections=20,
                keepalive_expiry=30.0,
            ),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
    return _client


async def close_http_client() -> None:
    """Cierra el cliente HTTP compartido. Llamar en el teardown del servidor (lifespan)."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


__all__ = ["get_client", "close_http_client"]
