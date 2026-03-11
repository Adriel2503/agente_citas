"""
Instancias de CircuitBreaker para las APIs externas de MaravIA.

Cada API tiene su propio CB con partición por key (id_empresa, id_chatbot, "global").
Para agregar una nueva API, crear una instancia aquí y usarla en el servicio.

La clase CircuitBreaker vive en infra/ (infraestructura genérica).
Las instancias viven aquí (configuración de negocio).
"""

from ..infra import CircuitBreaker
from . import CB_THRESHOLD, CB_RESET_TTL, CB_MAX_KEYS

# ---------------------------------------------------------------------------
# Registry para /health
# ---------------------------------------------------------------------------

_registry: list[CircuitBreaker] = []


def _register(cb: CircuitBreaker) -> CircuitBreaker:
    """Registra un CB en el registro global. Retorna el mismo CB para uso inline."""
    _registry.append(cb)
    return cb


def get_health_issues() -> list[str]:
    """
    Retorna lista de CBs abiertos en formato '{name}_degraded'.
    Usado por /health para reportar degradación sin enumerar los CBs individualmente.
    Agregar un nuevo CB solo requiere usar _register() — /health se actualiza solo.
    """
    return [f"{cb.name}_degraded" for cb in _registry if cb.any_open()]


# ---------------------------------------------------------------------------
# Instancias compartidas entre servicios
# ---------------------------------------------------------------------------

# Keyed by id_empresa.
# Compartido por: horario_reuniones, contexto_negocio, productos_servicios_citas, busqueda_productos, schedule_validator
informacion_cb: CircuitBreaker = _register(CircuitBreaker(
    name="ws_informacion_ia",
    threshold=CB_THRESHOLD,
    reset_ttl=CB_RESET_TTL,
    max_keys=CB_MAX_KEYS,
))

# Keyed by id_chatbot.
# Usado por: preguntas_frecuentes
preguntas_cb: CircuitBreaker = _register(CircuitBreaker(
    name="ws_preguntas_frecuentes",
    threshold=CB_THRESHOLD,
    reset_ttl=CB_RESET_TTL,
    max_keys=CB_MAX_KEYS,
))

# Key fija "global": ws_calendario.php es un servicio compartido de MaravIA.
# Si cae, cae para todas las empresas. Fallos por empresa (Google Calendar)
# llegan como success=false → no abren el circuit.
# Usado por: booking
calendario_cb: CircuitBreaker = _register(CircuitBreaker(
    name="ws_calendario",
    threshold=CB_THRESHOLD,
    reset_ttl=CB_RESET_TTL,
    max_keys=CB_MAX_KEYS,
))

# Keyed by id_empresa. Lecturas: CONSULTAR_DISPONIBILIDAD, SUGERIR_HORARIOS.
# Usado por: schedule_validator, schedule_recommender, availability_client
agendar_reunion_cb: CircuitBreaker = _register(CircuitBreaker(
    name="ws_agendar_reunion",
    threshold=CB_THRESHOLD,
    reset_ttl=CB_RESET_TTL,
    max_keys=CB_MAX_KEYS,
))

__all__ = [
    "informacion_cb", "preguntas_cb", "calendario_cb", "agendar_reunion_cb",
    "get_health_issues",
]
