"""
Cliente HTTP compartido para todos los servicios de agent_citas.

Inicialización lazy: el cliente se crea en la primera llamada a get_client()
y se cierra limpiamente en el lifespan del servidor MCP (close_http_client).
Esto permite reutilizar el connection pool entre todas las llamadas a las APIs
de MaravIA (informacion, agendar_reunion, calendario).

post_with_retry: wrapper con retry automático (tenacity) para operaciones de
LECTURA. No usar en operaciones de escritura (CREAR_EVENTO) por riesgo de
duplicados si el servidor recibió la request pero la respuesta timeouteó.
"""

from typing import Any, Dict, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

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


@retry(
    stop=stop_after_attempt(app_config.HTTP_RETRY_ATTEMPTS),
    wait=wait_exponential(min=app_config.HTTP_RETRY_WAIT_MIN, max=app_config.HTTP_RETRY_WAIT_MAX),
    retry=retry_if_exception_type(httpx.TransportError),
    reraise=True,
)
async def post_with_retry(url: str, json: Dict[str, Any]) -> Dict[str, Any]:
    """
    POST con retry automático para errores de red transitoria (hasta 3 intentos).

    Reintenta solo httpx.TransportError (timeouts, connect errors).
    NO reintenta httpx.HTTPStatusError (respuestas 4xx/5xx del servidor).

    Backoff exponencial: 1s → 2s → 4s (máx).

    ADVERTENCIA: usar solo en operaciones de LECTURA idempotentes.
    Para escrituras (ej. CREAR_EVENTO) usar client.post() directamente.
    """
    client = get_client()
    response = await client.post(url, json=json)
    response.raise_for_status()
    return response.json()


__all__ = ["get_client", "close_http_client", "post_with_retry"]
