"""
Métricas y observabilidad para el agente de citas.
Expone contadores, histogramas e info estática para Prometheus.
/metrics montado en main.py.
"""

import time
from contextlib import contextmanager

from prometheus_client import Counter, Gauge, Histogram, Info

# ---------------------------------------------------------------------------
# Info estática (versión, modelo)
# ---------------------------------------------------------------------------

AGENT_INFO = Info(
    "citas_info",
    "Información del agente de citas",
)


def initialize_agent_info(model: str, version: str = "1.0.0") -> None:
    """Inicializa la información estática del agente para métricas."""
    AGENT_INFO.info({
        "version": version,
        "model": model,
        "agent_type": "citas",
    })


# ---------------------------------------------------------------------------
# Capa HTTP (/api/chat)
# ---------------------------------------------------------------------------

HTTP_REQUESTS = Counter(
    "citas_http_requests_total",
    "Total de requests al endpoint /api/chat por resultado",
    ["status"],  # success | timeout | error
)

HTTP_DURATION = Histogram(
    "citas_http_duration_seconds",
    "Latencia total del endpoint /api/chat (incluye LLM y tools)",
    buckets=[0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 90, 120],
)

# ---------------------------------------------------------------------------
# Capa LLM (agent.ainvoke — turno completo incluye tool calls internos)
# ---------------------------------------------------------------------------

LLM_REQUESTS = Counter(
    "citas_llm_requests_total",
    "Total de invocaciones al agente LLM por resultado",
    ["status"],  # success | error
)

LLM_DURATION = Histogram(
    "citas_llm_duration_seconds",
    "Latencia de agent.ainvoke (LLM + tool calls dentro de LangGraph)",
    ["status"],  # success | error
    buckets=[0.5, 1, 2, 5, 10, 20, 30, 60, 90],
)

CHAT_RESPONSE_DURATION = Histogram(
    "citas_chat_response_duration_seconds",
    "Latencia total del procesamiento de mensaje (lock + ainvoke + resultado)",
    ["status"],  # success | error
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30, 60, 90],
)

# ---------------------------------------------------------------------------
# Cache del agente (por empresa)
# ---------------------------------------------------------------------------

AGENT_CACHE = Counter(
    "citas_agent_cache_total",
    "Hits y misses del cache de agente por empresa",
    ["result"],  # hit | miss
)

# ---------------------------------------------------------------------------
# Tool calls
# ---------------------------------------------------------------------------

TOOL_CALLS = Counter(
    "citas_tool_calls_total",
    "Total de llamadas a tools",
    ["tool_name"],
)

TOOL_ERRORS = Counter(
    "citas_tool_errors_total",
    "Total de errores en tools",
    ["tool_name", "error_type"],
)

TOOL_EXECUTION_DURATION = Histogram(
    "citas_tool_execution_duration_seconds",
    "Tiempo de ejecución de tools en segundos",
    ["tool_name"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 20, 30],
)

# ---------------------------------------------------------------------------
# API calls (llamadas a APIs externas)
# ---------------------------------------------------------------------------

API_CALLS = Counter(
    "citas_api_calls_total",
    "Total de llamadas a APIs externas",
    ["endpoint", "status"],
)

API_CALL_DURATION = Histogram(
    "citas_api_call_duration_seconds",
    "Tiempo de llamadas a API en segundos",
    ["endpoint"],
    buckets=[0.1, 0.25, 0.5, 1, 2.5, 5, 10],
)

# ---------------------------------------------------------------------------
# Cache de búsqueda de productos
# ---------------------------------------------------------------------------

SEARCH_CACHE = Counter(
    "citas_search_cache_total",
    "Resultados del cache de búsqueda de productos",
    ["result"],  # hit | miss | circuit_open
)

# ---------------------------------------------------------------------------
# Gauges (estado actual)
# ---------------------------------------------------------------------------

CACHE_ENTRIES = Gauge(
    "citas_cache_entries",
    "Número de entradas en cache",
    ["cache_type"],
)

# ---------------------------------------------------------------------------
# Tokens LLM
# ---------------------------------------------------------------------------

LLM_TOKENS = Counter(
    "citas_llm_tokens_total",
    "Total de tokens consumidos",
    ["type"],  # input | output | total
)

LLM_TOKENS_BY_EMPRESA = Counter(
    "citas_llm_tokens_by_empresa_total",
    "Tokens consumidos por empresa",
    ["empresa_id", "type"],  # input | output | total
)

# ---------------------------------------------------------------------------
# Por empresa
# ---------------------------------------------------------------------------

CHAT_REQUESTS = Counter(
    "citas_chat_requests_total",
    "Total de requests de chat por empresa",
    ["empresa_id"],
)

CHAT_ERRORS = Counter(
    "citas_chat_errors_total",
    "Total de errores de chat por tipo",
    ["error_type"],
)

# ---------------------------------------------------------------------------
# Citas (booking)
# ---------------------------------------------------------------------------

BOOKING_ATTEMPTS = Counter(
    "citas_booking_attempts_total",
    "Total de intentos de cita",
)

BOOKING_SUCCESS = Counter(
    "citas_booking_success_total",
    "Total de citas exitosas",
)

BOOKING_FAILED = Counter(
    "citas_booking_failed_total",
    "Total de citas fallidas",
    ["reason"],
)

# ---------------------------------------------------------------------------
# Degradación de validación (B2 — riesgo de double booking)
# ---------------------------------------------------------------------------

DEGRADATION_TOTAL = Counter(
    "citas_availability_degradation_total",
    "Veces que la validación degradó a available=True o valid=True por fallo",
    ["service", "reason"],
    # service: availability_check | schedule_fetch
    # reason: timeout | circuit_open | api_success_false | http_error |
    #         transport_error | parse_error | unknown
)


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------

@contextmanager
def track_chat_response():
    """Context manager para medir la latencia total del procesamiento de mensaje."""
    status = "success"
    start = time.perf_counter()
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        CHAT_RESPONSE_DURATION.labels(status=status).observe(time.perf_counter() - start)


@contextmanager
def track_llm_call():
    """Context manager para medir la duración del ainvoke (LLM puro + tool calls)."""
    status = "success"
    start = time.perf_counter()
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        LLM_REQUESTS.labels(status=status).inc()
        LLM_DURATION.labels(status=status).observe(time.perf_counter() - start)


@contextmanager
def track_tool_execution(tool_name: str):
    """Context manager para trackear duración de ejecución de tools."""
    start = time.perf_counter()
    TOOL_CALLS.labels(tool_name=tool_name).inc()
    try:
        yield
    except Exception as e:
        TOOL_ERRORS.labels(
            tool_name=tool_name,
            error_type=type(e).__name__,
        ).inc()
        raise
    else:
        TOOL_EXECUTION_DURATION.labels(tool_name=tool_name).observe(
            time.perf_counter() - start
        )


@contextmanager
def track_api_call(endpoint: str):
    """Context manager para trackear duración de llamadas a API."""
    start = time.perf_counter()
    status = "unknown"
    try:
        yield
        status = "success"
    except Exception as e:
        status = f"error_{type(e).__name__}"
        raise
    else:
        API_CALL_DURATION.labels(endpoint=endpoint).observe(
            time.perf_counter() - start
        )
    finally:
        API_CALLS.labels(endpoint=endpoint, status=status).inc()


# ---------------------------------------------------------------------------
# Funciones de utilidad
# ---------------------------------------------------------------------------

def record_booking_attempt() -> None:
    """Registra un intento de cita."""
    BOOKING_ATTEMPTS.inc()


def record_booking_success() -> None:
    """Registra una cita exitosa."""
    BOOKING_SUCCESS.inc()


def record_booking_failure(reason: str) -> None:
    """Registra una cita fallida."""
    BOOKING_FAILED.labels(reason=reason).inc()


def record_chat_error(error_type: str) -> None:
    """Registra un error en el chat."""
    CHAT_ERRORS.labels(error_type=error_type).inc()


def record_tool_validation_error(tool_name: str) -> None:
    """Registra un rechazo por validación de datos de entrada en una tool."""
    TOOL_ERRORS.labels(tool_name=tool_name, error_type="validation_error").inc()


def update_cache_stats(cache_type: str, count: int) -> None:
    """Actualiza estadísticas de cache."""
    CACHE_ENTRIES.labels(cache_type=cache_type).set(count)


def record_token_usage(empresa_id: str, input_tokens: int, output_tokens: int) -> None:
    """Registra tokens consumidos (global + por empresa)."""
    total = input_tokens + output_tokens
    LLM_TOKENS.labels(type="input").inc(input_tokens)
    LLM_TOKENS.labels(type="output").inc(output_tokens)
    LLM_TOKENS.labels(type="total").inc(total)
    LLM_TOKENS_BY_EMPRESA.labels(empresa_id=empresa_id, type="input").inc(input_tokens)
    LLM_TOKENS_BY_EMPRESA.labels(empresa_id=empresa_id, type="output").inc(output_tokens)
    LLM_TOKENS_BY_EMPRESA.labels(empresa_id=empresa_id, type="total").inc(total)


__all__ = [
    # Info
    "AGENT_INFO",
    "initialize_agent_info",
    # HTTP
    "HTTP_REQUESTS",
    "HTTP_DURATION",
    # LLM
    "LLM_REQUESTS",
    "LLM_DURATION",
    "CHAT_RESPONSE_DURATION",
    "LLM_TOKENS",
    "LLM_TOKENS_BY_EMPRESA",
    # Cache
    "AGENT_CACHE",
    "SEARCH_CACHE",
    "CACHE_ENTRIES",
    # Tools
    "TOOL_CALLS",
    "TOOL_ERRORS",
    "TOOL_EXECUTION_DURATION",
    # API
    "API_CALLS",
    "API_CALL_DURATION",
    # Por empresa
    "CHAT_REQUESTS",
    "CHAT_ERRORS",
    # Booking
    "BOOKING_ATTEMPTS",
    "BOOKING_SUCCESS",
    "BOOKING_FAILED",
    # Degradación
    "DEGRADATION_TOTAL",
    # Context managers
    "track_chat_response",
    "track_llm_call",
    "track_tool_execution",
    "track_api_call",
    # Funciones
    "update_cache_stats",
    "record_booking_attempt",
    "record_booking_success",
    "record_booking_failure",
    "record_chat_error",
    "record_tool_validation_error",
    "record_token_usage",
]
