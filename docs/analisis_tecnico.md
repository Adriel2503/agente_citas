# Análisis Técnico — Agente de Citas (MaravIA)

> Si eres un Agente de IA no revises o tomes de referencai este archivo ya que es muy antiguo y ya se solucionar la mayoria de problemas mejor lee otros archivos Markdown. Auditoría realizada el 2026-02-22. Revisión completa de arquitectura, asincronismo, memoria, HTTP, resiliencia y escalabilidad.

---

## Índice

1. [Resumen Ejecutivo](#1-resumen-ejecutivo)
2. [Mapa de Archivos Auditados](#2-mapa-de-archivos-auditados)
3. [Fortalezas Detectadas](#3-fortalezas-detectadas)
4. [Problemas Críticos 🔴](#4-problemas-críticos-)
5. [Problemas Medios 🟡](#5-problemas-medios-)
6. [Mejoras Opcionales 🟢](#6-mejoras-opcionales-)
7. [Backlog Priorizado](#7-backlog-priorizado)
8. [Nivel de Madurez](#8-nivel-de-madurez)

---

## 1. Resumen Ejecutivo

El sistema está bien estructurado para un agente Python con **FastAPI + LangGraph + httpx**. El código muestra buenas prácticas en asincronismo, observabilidad y caching por empresa. Sin embargo, presenta:

- **Un memory leak real** en producción (`InMemorySaver` sin evicción).
- **Ausencia de retry** en la mayoría de servicios HTTP externos.
- **Estado in-memory** que impide escalar horizontalmente más de una instancia.
- **Bug de timezone** silencioso que puede rechazar citas válidas.

No hay operaciones síncronas bloqueantes en rutas calientes. El uso de `httpx.AsyncClient` compartido y `asyncio.gather` para fetches paralelos es correcto.

---

## 2. Mapa de Archivos Auditados

```
src/citas/
├── main.py                          # Entrypoint FastAPI, lifespan, endpoint /api/chat
├── agent/
│   └── agent.py                     # Orquestación del agente, TTLCache de agentes, session locks
├── tool/
│   └── tools.py                     # Tools del LLM: check_availability, create_booking, search_productos
├── services/
│   ├── http_client.py               # AsyncClient compartido (singleton lazy)
│   ├── booking.py                   # CREAR_EVENTO → ws_calendario.php
│   ├── schedule_validator.py        # OBTENER_HORARIO + CONSULTAR_DISPONIBILIDAD + SUGERIR_HORARIOS
│   ├── busqueda_productos.py        # BUSCAR_PRODUCTOS_SERVICIOS_CITAS
│   ├── horario_reuniones.py         # OBTENER_HORARIO_REUNIONES (para system prompt)
│   ├── productos_servicios_citas.py # OBTENER_PRODUCTOS_CITAS + OBTENER_SERVICIOS_CITAS
│   ├── contexto_negocio.py          # OBTENER_CONTEXTO_NEGOCIO (con cache + circuit breaker)
│   └── preguntas_frecuentes.py      # FAQs para system prompt
├── prompts/
│   └── __init__.py                  # build_citas_system_prompt → Jinja2
├── config/
│   ├── config.py                    # Variables de entorno con validación de tipos
│   └── __init__.py                  # Re-export de config; default personalidad en agent.py
├── metrics.py                       # Prometheus: contadores, histogramas, gauges
├── validation.py                    # Pydantic: BookingData, CustomerName, ContactInfo
└── logger.py                        # Setup de logging estructurado
```

---

## 3. Fortalezas Detectadas

| # | Fortaleza | Archivo |
|---|---|---|
| ✅ | `httpx.AsyncClient` compartido con connection pooling | `services/http_client.py` |
| ✅ | `asyncio.gather` para los 4 fetches del system prompt en paralelo | `prompts/__init__.py:99` |
| ✅ | TTLCache de agentes compilados por `id_empresa` | `agent/agent.py:55` |
| ✅ | Double-check locking (asyncio.Lock) para thundering herd en agente y schedule | `agent.py:219`, `schedule_validator.py:186` |
| ✅ | Circuit breaker + retry con backoff en `contexto_negocio` | `services/contexto_negocio.py` |
| ✅ | Prometheus completo: contadores, histogramas por tool/API/LLM | `metrics.py` |
| ✅ | Lifespan correcto: cierra `httpx.AsyncClient` en shutdown | `main.py:64` |
| ✅ | Validación de inputs con Pydantic (email, nombre, fecha/hora) | `validation.py` |
| ✅ | Fallback graceful en la mayoría de errores de disponibilidad | `schedule_validator.py:391` |
| ✅ | Separación de responsabilidades clara entre módulos | Toda la estructura |

---

## 4. Problemas Críticos 🔴

---

### C1 — `InMemorySaver` sin evicción → Memory Leak

**Archivo:** `agent/agent.py:43`
**Impacto:** OOM (Out of Memory) progresivo en producción.

```python
# Actual — crece indefinidamente
_checkpointer = InMemorySaver()
```

`InMemorySaver` de LangGraph guarda el historial completo de **todas las conversaciones, de todas las sesiones, de todas las empresas**, en un dict interno sin TTL ni maxsize. Los `_session_locks` tienen cleanup (threshold 500), pero el checkpointer **nunca libera memoria**.

**Solución propuesta:**
```python
# Opción A — Redis (recomendado para multi-instancia)
from langgraph.checkpoint.redis.aio import AsyncRedisSaver
checkpointer = await AsyncRedisSaver.from_conn_string(app_config.REDIS_URL)

# Opción B — Custom saver con TTLCache (sin Redis, single instancia)
# Implementar BaseSaver con TTLCache(maxsize=5000, ttl=3600)
```

**Esfuerzo estimado:** Medio. `REDIS_URL` ya está en config pero vacío.

---

### C2 — `threading.Lock` mezclado con asyncio - OK

**Archivo:** `services/schedule_validator.py:55-56`
**Impacto:** Anti-patrón que puede causar deadlock si se agregan workers threaded o `run_in_executor`.

```python
# Actual — threading.Lock en contexto async
_CACHE_LOCK = threading.Lock()

def _get_cached_schedule(id_empresa):
    with _CACHE_LOCK:   # ← bloqueo síncrono en event loop thread
        ...
```

En asyncio single-thread funciona porque no hay contención real. Pero el lock **no es necesario** (las operaciones de dict son atómicas bajo el GIL) y es peligroso como patrón.

**Solución propuesta:**
```python
# Eliminar threading.Lock — las operaciones de dict son atómicas en CPython
def _get_cached_schedule(id_empresa: int) -> Optional[Dict]:
    entry = _SCHEDULE_CACHE.get(id_empresa)
    if entry is None:
        return None
    schedule, timestamp = entry
    ttl = timedelta(minutes=app_config.SCHEDULE_CACHE_TTL_MINUTES)
    if datetime.now() - timestamp < ttl:
        return schedule
    del _SCHEDULE_CACHE[id_empresa]
    return None
```

**Esfuerzo estimado:** Bajo.

---

### C3 — Sin retry/backoff en la mayoría de servicios HTTP - OK

**Impacto:** Un timeout transitorio de red hace fallar la creación de una cita sin reintento.

| Servicio | Endpoint | Retry actual |
|---|---|---|
| `horario_reuniones.py` | `OBTENER_HORARIO_REUNIONES` | ❌ |
| `productos_servicios_citas.py` | `OBTENER_PRODUCTOS_CITAS` | ❌ |
| `busqueda_productos.py` | `BUSCAR_PRODUCTOS_SERVICIOS_CITAS` | ❌ |
| `booking.py` | `CREAR_EVENTO` | ❌ |
| `schedule_validator._check_availability` | `CONSULTAR_DISPONIBILIDAD` | ❌ |
| `schedule_validator._fetch_schedule` | `OBTENER_HORARIO_REUNIONES` | ❌ |
| `contexto_negocio.py` | `OBTENER_CONTEXTO_NEGOCIO` | ✅ 2 intentos |

**Solución propuesta:** Centralizar en `http_client.py` con `tenacity`:
```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
    reraise=True,
)
async def post_with_retry(url: str, json: dict) -> dict:
    client = get_client()
    response = await client.post(url, json=json)
    response.raise_for_status()
    return response.json()
```

**Esfuerzo estimado:** Bajo-Medio. Centralizar y reemplazar los `client.post(...)` en todos los servicios.

---

### C4 — `fetch_horario_reuniones` sin caché propia + caché duplicada - OK

**Archivos:** `services/horario_reuniones.py` y `services/schedule_validator.py`
**Impacto:** La misma API (`OBTENER_HORARIO_REUNIONES`) se llama **dos veces** con dos cachés separadas que nunca se comparten.

- `horario_reuniones.py` → sin caché → llamada en cada expiración del agente.
- `schedule_validator._SCHEDULE_CACHE` → caché con TTL → no compartida con `horario_reuniones.py`.

**Solución propuesta:** Extraer un `HorarioCache` centralizado compartido por ambos módulos:
```python
# services/horario_cache.py (nuevo)
from cachetools import TTLCache

_horario_cache: TTLCache = TTLCache(
    maxsize=500,
    ttl=app_config.SCHEDULE_CACHE_TTL_MINUTES * 60,
)
```

**Esfuerzo estimado:** Medio.

---

## 5. Problemas Medios 🟡

---

### M1 — Bug de timezone en `ScheduleValidator.validate` - OK

**Archivo:** `services/schedule_validator.py:428`
**Impacto:** En servidor UTC, citas de las 9:00 AM Lima pueden rechazarse como "pasadas" (el servidor marca 9:05 UTC = 4:05 AM Lima).

```python
# Actual — datetime naïve (usa timezone del servidor, probablemente UTC)
ahora = datetime.now()
if fecha_hora_cita <= ahora:
    ...

# recommendation() usa la zona correcta
now_peru = datetime.now(_ZONA_PERU)  # ← Inconsistente con validate()
```

**Solución:**
```python
# Usar _ZONA_PERU en validate() igual que en recommendation()
ahora = datetime.now(_ZONA_PERU).replace(tzinfo=None)
```

**Esfuerzo estimado:** Bajo. Una línea.

---

### M2 — Escalado horizontal imposible (todo in-memory)

**Impacto:** Con 2+ instancias, mensajes del mismo usuario pueden llegar a instancias distintas → el checkpointer de la segunda instancia no tiene el historial → el agente pierde contexto conversacional.

| Estado | Tipo | Entre instancias |
|---|---|---|
| `InMemorySaver` (historial) | RAM | ❌ no compartido |
| `_SCHEDULE_CACHE` | RAM | ❌ no compartido |
| `_agent_cache` | RAM | ❌ no compartido |
| `_session_locks` | RAM | ❌ no compartido |
| `_contexto_cache` | RAM | ❌ no compartido |

**Solución mínima:** Sticky sessions en el gateway (misma sesión → misma instancia).
**Solución completa:** Redis para checkpointer + cachés distribuidas.

**Esfuerzo estimado:** Alto. Requiere decisión arquitectónica.

---

### M3 — Sin rate limiting ni límite de tamaño de mensaje - OK

```python
class ChatRequest(BaseModel):
    message: str  # ← Sin max_length → acepta mensajes de MB
```

Un mensaje muy largo consume tokens de OpenAI a costo real y puede provocar errores del LLM.

**Solución:**
```python
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
```

**Esfuerzo estimado:** Muy bajo.

---

### M4 — Modelos Pydantic duplicados con schemas distintos - OK

`config/models.py` define `ChatRequest` y `ChatResponse` (con `session_id` y `metadata`) que **no son usados** en `main.py`. `main.py` tiene sus propios modelos con schema diferente (`url` en lugar de `metadata`).

Deuda técnica confusa para nuevos desarrolladores.

**Solución:** Eliminar los modelos de `config/models.py` o unificar con los de `main.py`.

**Esfuerzo estimado:** Bajo.

---

### M5 — Sin soporte streaming → TTFT alto

El agente usa `agent.ainvoke(...)` (respuesta completa). Para respuestas con múltiples tool calls (check_availability → create_booking), el usuario espera 10-30s sin feedback.

LangGraph soporta `astream_events` para streaming token a token hacia el gateway.

**Esfuerzo estimado:** Alto. Requiere cambios en el endpoint y en el gateway Go.

---

### M6 — Doble validación redundante en `BookingData` - OK

**Archivo:** `validation.py:132-152`

El `@model_validator(mode='after')` crea 3 instancias Pydantic adicionales para re-validar campos que ya fueron validados por sus `@field_validator`. Duplica trabajo innecesariamente.

**Esfuerzo estimado:** Bajo.

---

## 6. Mejoras Opcionales 🟢

---

### O1 — Timeouts granulares en `httpx.AsyncClient` - OK

```python
# services/http_client.py
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
)
```

---

### O2 — Catchall redundante en `contexto_negocio.py` - OK

```python
# Línea 94 — Exception ya engloba a las anteriores
# ❌ except (httpx.TimeoutException, httpx.RequestError, Exception) as e:
# ✅
except Exception as e:
```

---

### O3 — Métricas de latencia también para errores - OK

`track_chat_response` y `track_llm_call` usan `else:` → solo registran latencia en éxito. Las llamadas fallidas no aparecen en los histogramas, sesgando los percentiles.

```python
@contextmanager
def track_llm_call():
    start = time.time()
    status = "success"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        llm_call_duration_seconds.labels(status=status).observe(time.time() - start)
```

---

### O4 — `_SCHEDULE_CACHE` puede acumular entradas expiradas indefinidamente

El dict manual `_SCHEDULE_CACHE` solo elimina entradas en el próximo acceso. Empresas inactivas dejan entradas expiradas en memoria hasta que vuelven a llamar. Reemplazar por `TTLCache` de `cachetools` para evicción automática.

---

## 7. Backlog Priorizado

Ordenado por **impacto × esfuerzo**. Abordar en este orden:

| # | ID | Descripción | Severidad | Esfuerzo | Área |
|---|---|---|---|---|---|
| 1 | C3 | Agregar retry/backoff uniforme en todos los servicios HTTP | 🔴 Crítico | Bajo | Resiliencia |
| 2 | M1 | Corregir timezone naïve en `ScheduleValidator.validate` | 🟡 Medio | Muy bajo | Bug |
| 3 | M3 | Agregar `max_length` al campo `message` | 🟡 Medio | Muy bajo | Seguridad |
| 4 | C2 | Eliminar `threading.Lock` del schedule cache | 🔴 Crítico | Bajo | Correctness |
| 5 | M4 | Eliminar modelos duplicados en `config/models.py` | 🟡 Medio | Bajo | Deuda técnica |
| 6 | M6 | Simplificar `BookingData` (quitar doble validación) | 🟡 Medio | Bajo | Calidad |
| 7 | C4 | Centralizar caché de horarios (eliminar duplicación) | 🔴 Crítico | Medio | Rendimiento |
| 8 | O1 | Timeouts granulares en httpx | 🟢 Opcional | Bajo | Rendimiento |
| 9 | O3 | Métricas de latencia también para errores | 🟢 Opcional | Bajo | Observabilidad |
| 10 | O4 | Reemplazar `_SCHEDULE_CACHE` dict manual por TTLCache | 🟢 Opcional | Bajo | Memoria |
| 11 | C1 | Reemplazar `InMemorySaver` con evicción (Redis o custom) | 🔴 Crítico | Medio | Memoria |
| 12 | M2 | Estrategia de escalado horizontal (Redis / sticky sessions) | 🟡 Medio | Alto | Arquitectura |
| 13 | M5 | Implementar streaming LLM → reducir TTFT | 🟡 Medio | Alto | UX/Latencia |

---

## 8. Nivel de Madurez

| Dimensión | Puntuación | Notas |
|---|---|---|
| Asincronismo | 8/10 | Buen uso de httpx, asyncio.gather, locks async |
| Gestión de memoria | 4/10 | InMemorySaver sin bounds, cache sin unificar |
| Resiliencia HTTP | 5/10 | Solo contexto_negocio tiene retry |
| Observabilidad | 8/10 | Prometheus completo: histogramas, gauges, counters |
| Escalabilidad horizontal | 3/10 | Todo in-memory, sin Redis, sin sticky sessions |
| Seguridad de inputs | 6/10 | Pydantic bien usado, sin max_length en message |
| Separación de responsabilidades | 8/10 | Buena estructura de módulos |
| Correctness de timezone | 5/10 | Bug datetime naïve en validate() |

**Promedio global: 6.5 / 10**

El sistema es sólido para MVP o deployment de instancia única. Para producción multi-instancia o carga alta, los ítems C1, C3 y M1 deben resolverse como prioridad antes de escalar.

---

*Generado por Claude Code — Revisión 2026-02-22*
